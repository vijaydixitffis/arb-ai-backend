"""
LangGraph node implementations for the ARB parallel orchestrator.

Node execution order (see graph.py for wiring):
  load_context_node
    → [Send("domain_agent_node", …) × N]  ← parallel fan-out
  aggregate_node                           ← fan-in join
  synthesis_node
  build_report_node

All nodes are plain async functions that accept (state, config) and return a
partial state dict. LangGraph merges the returned dict into the running state
using the reducers declared in ARBGraphState.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from langgraph.types import Send
from langchain_core.runnables import RunnableConfig
from sqlalchemy.orm import Session

from app.agents.langgraph_orchestrator.structured_output import DomainReviewPayload
from app.core.config import settings
from app.core.db_config import db_config

logger = logging.getLogger(__name__)


# ── Helpers shared with the custom orchestrator ───────────────────────────────

def _score_to_label(score: int) -> str:
    if score >= 4:
        return "green"
    if score == 3:
        return "amber"
    return "red"


def _determine_decision(
    aggregate_score: int,
    blockers: List[Dict[str, Any]],
) -> str:
    has_sec_dr  = any(b.get("is_security_or_dr") for b in blockers)
    has_non_sec = any(not b.get("is_security_or_dr") for b in blockers)
    n_blockers  = len(blockers)

    if aggregate_score >= 4 and n_blockers == 0:
        return "approve"
    if aggregate_score <= 1 and has_sec_dr:
        return "reject"
    if has_sec_dr:
        return "defer"
    if has_non_sec or aggregate_score <= 3:
        return "approve_with_conditions"
    return "approve"


def _persist_partial(db: Session, review_id: str, domain_slug: str, payload: Dict[str, Any]) -> None:
    """Write one completed domain result into report_json.domain_partial_results."""
    from app.db.review_models import Review
    try:
        review = db.query(Review).filter(Review.id == review_id).first()
        if review:
            existing = dict(review.report_json or {})
            partials  = dict(existing.get("domain_partial_results", {}))
            partials[domain_slug] = payload
            existing["domain_partial_results"] = partials
            review.report_json = existing
            db.commit()
    except Exception as exc:
        logger.warning(f"[LG] Could not persist partial for '{domain_slug}': {exc}")
        try:
            db.rollback()
        except Exception:
            pass


# ── Node 1: load_context_node ─────────────────────────────────────────────────

async def load_context_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Fetch the review record and resolve the ordered domain list."""
    db: Session     = config["configurable"]["db"]
    review_id: str  = state["review_id"]

    from app.db.review_models import Review
    from app.db.metadata_models import Domain

    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise ValueError(f"[LG] Review {review_id} not found")

    active_slugs = {d.slug for d in db.query(Domain).filter(Domain.is_active == True).all()}
    scope        = review.scope_tags or []

    domains: List[str] = []
    for tag in scope:
        if tag in active_slugs and tag not in domains:
            domains.append(tag)
    if "solution" in active_slugs and "solution" not in domains:
        domains.insert(0, "solution")

    logger.info(f"[LG] load_context review={review_id} domains={domains}")

    return {
        "solution_name":  review.solution_name or "",
        "domains":        domains,
        "domain_results": {},
        "failed_domains": [],
        "retry_counts":   {},
    }


# ── Routing function: fan-out after load_context ──────────────────────────────

def route_to_domains(state: Dict[str, Any]) -> List[Send]:
    """Emit one Send per domain slug — LangGraph dispatches these in parallel."""
    return [
        Send("domain_agent", {**state, "current_domain": slug})
        for slug in state["domains"]
    ]


# ── Node 2: domain_agent_node ─────────────────────────────────────────────────

async def domain_agent_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Run one domain agent, validate its output, persist partial result."""
    db:          Session = config["configurable"]["db"]
    rate_limiter         = config["configurable"]["rate_limiter"]
    review_id:   str     = state["review_id"]
    domain_slug: str     = state["current_domain"]
    checklist_data       = state.get("checklist_data", {})

    from app.agents.enhanced_domain_agents import EnhancedDomainValidationAgent
    from app.db.metadata_models import Domain

    domain_obj   = db.query(Domain).filter(Domain.slug == domain_slug, Domain.is_active == True).first()
    domain_meta  = {
        "name":        domain_obj.name        if domain_obj else domain_slug.title(),
        "description": domain_obj.description if domain_obj else "",
        "solution_name": state.get("solution_name", ""),
    }
    if domain_slug == "solution":
        from app.db.review_models import Review
        review = db.query(Review).filter(Review.id == review_id).first()
        fd = (review.report_json or {}).get("form_data", {}) if review else {}
        domain_meta.update({
            "problem_statement":        fd.get("problem_statement") or "(not provided)",
            "business_drivers":         fd.get("business_drivers") or [],
            "stakeholders":             fd.get("stakeholders") or [],
            "target_business_outcomes": fd.get("growth_plans") or fd.get("target_business_outcomes") or "(not provided)",
        })

    domain_checklist = dict(checklist_data.get("domain_data", {}).get(domain_slug, {}))
    domain_checklist["domain_metadata"] = domain_meta

    max_attempts = int(db_config(db, "agent.max_retries", settings.AGENT_MAX_RETRIES))
    retry_counts = dict(state.get("retry_counts", {}))
    attempt      = retry_counts.get(domain_slug, 0)

    stub_payload = {
        "domain": domain_slug,
        "error": "max retries exceeded",
        "summary": {
            "rag_score": 2, "rag_label": "red",
            "overall_readiness": "DEFER",
            "executive_summary": f"Domain review failed after {max_attempts} attempts.",
            "compliant_areas": [], "gap_areas": ["Domain agent failed — re-run required"],
            "blocker_count": 0, "action_count": 0, "adr_count": 0,
            "evidence_quality": "ABSENT",
        },
        "findings": [{
            "id": f"{domain_slug.upper()[:3]}-F01",
            "check_category": "AGENT_FAILURE",
            "rag_score": 2, "rag_label": "red",
            "title": f"{domain_slug} domain review failed — re-run required",
            "finding": "Domain agent failed. Re-trigger the review.",
            "is_blocker": False,
        }],
        "blockers": [], "recommendations": [], "actions": [], "adrs": [],
        "tokens_used": 0,
    }

    agent = EnhancedDomainValidationAgent(db)

    async with rate_limiter:
        logger.info(f"[LG] domain_agent_node start domain={domain_slug} attempt={attempt + 1}/{max_attempts}")
        try:
            raw = await agent.validate_domain(
                review_id=review_id,
                domain_slug=domain_slug,
                checklist_data=domain_checklist,
                content_scale=settings.CONTENT_SCALE_ON_RETRY if attempt > 0 else 1.0,
            )
            # Coerce through Pydantic — validates structure, normalises field types.
            validated = DomainReviewPayload(**{**raw, "domain": domain_slug})
            payload   = validated.model_dump()
            _persist_partial(db, review_id, domain_slug, payload)
            logger.info(f"[LG] domain_agent_node done domain={domain_slug} rag={payload['summary']['rag_score']}")
            return {
                "domain_results": {domain_slug: payload},
                "retry_counts":   {**retry_counts, domain_slug: attempt + 1},
            }
        except Exception as exc:
            logger.warning(f"[LG] domain_agent_node failed domain={domain_slug} attempt={attempt + 1}: {exc}")
            # Always return stub — never re-raise out of a domain node.
            # Re-raising escapes the checkpointer context manager and aborts all
            # parallel branches. Stub data surfaces the failure gracefully so the
            # review can complete and be re-triggered for failed domains only.
            _persist_partial(db, review_id, domain_slug, stub_payload)
            return {
                "domain_results": {domain_slug: stub_payload},
                "failed_domains": [domain_slug],
                "retry_counts":   {**retry_counts, domain_slug: attempt + 1},
            }


# ── Node 3: aggregate_node ────────────────────────────────────────────────────

async def aggregate_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Collect all domain results, compute aggregate scores and flat item lists.

    Mirrors the aggregation block in EnhancedARBOrchestrator.run_review() lines 162-216.
    """
    domain_results: Dict[str, Any] = state.get("domain_results", {})

    domain_scores:       Dict[str, int]      = {}
    domain_summaries:    Dict[str, Any]      = {}
    all_findings:        List[Dict[str, Any]] = []
    all_blockers:        List[Dict[str, Any]] = []
    all_recommendations: List[Dict[str, Any]] = []
    all_actions:         List[Dict[str, Any]] = []
    all_adrs:            List[Dict[str, Any]] = []
    all_nfr_scorecard:   List[Dict[str, Any]] = []
    kb_sources:          List[str]            = []
    total_tokens = 0

    for slug, payload in domain_results.items():
        summary   = payload.get("summary", {})
        raw_score = summary.get("rag_score", 3)
        rag_score = max(1, min(5, int(raw_score)))
        domain_scores[slug] = rag_score

        summary_copy        = dict(summary)
        summary_copy["domain"] = slug
        domain_summaries[slug] = summary_copy

        for f in payload.get("findings", []):
            all_findings.append({**f, "domain_slug": slug})

        # Only trust blockers from domains that scored 1 (BLOCKER) — same rule as custom path.
        raw_blockers = payload.get("blockers", [])
        if rag_score == 1:
            for b in raw_blockers:
                all_blockers.append({**b, "domain_slug": slug})
        elif raw_blockers:
            logger.warning(
                f"[LG] Discarding {len(raw_blockers)} blocker(s) from '{slug}' "
                f"(rag_score={rag_score}, not 1 — inconsistent LLM output)"
            )

        all_recommendations.extend(payload.get("recommendations", []))
        for a in payload.get("actions", []):
            all_actions.append({**a, "domain_slug": slug})
        for adr in payload.get("adrs", []):
            all_adrs.append({**adr, "domain_slug": slug})

        nfr_rows = payload.get("nfr_scorecard") or []
        all_nfr_scorecard.extend(nfr_rows)

        src = summary.get("kb_references") or []
        kb_sources.extend(src)
        total_tokens += payload.get("tokens_used", 0)

    # Tier-1: min aggregate; force 1 if any Security/DR blocker.
    has_sec_dr = any(b.get("is_security_or_dr") for b in all_blockers)
    scores     = list(domain_scores.values())
    aggregate_score = 1 if has_sec_dr else (min(scores) if scores else 3)

    kb_sources = list(dict.fromkeys(kb_sources))  # deduplicate, preserve order

    logger.info(
        f"[LG] aggregate_node agg={aggregate_score} findings={len(all_findings)} "
        f"blockers={len(all_blockers)} actions={len(all_actions)} adrs={len(all_adrs)}"
    )

    return {
        "domain_scores":       domain_scores,
        "domain_summaries":    domain_summaries,
        "all_findings":        all_findings,
        "all_blockers":        all_blockers,
        "all_recommendations": all_recommendations,
        "all_actions":         all_actions,
        "all_adrs":            all_adrs,
        "all_nfr_scorecard":   all_nfr_scorecard,
        "kb_sources":          kb_sources,
        "total_tokens":        total_tokens,
        "aggregate_score":     aggregate_score,
    }


# ── Node 4: synthesis_node ────────────────────────────────────────────────────

async def synthesis_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Tier-2 synthesis via LangChain with_structured_output(SynthesisOutput).

    Replaces the regex-stripped parse_json_from_llm() approach in the custom path.
    Applies the same score correction and Tier-1 floor logic as _run_synthesis().
    """
    db: Session = config["configurable"]["db"]

    review_id       = state["review_id"]
    solution_name   = state.get("solution_name", "")
    domain_scores   = state.get("domain_scores", {})
    all_findings    = state.get("all_findings", [])
    all_blockers    = state.get("all_blockers", [])
    all_adrs        = state.get("all_adrs", [])
    aggregate_score = state.get("aggregate_score", 3)

    logger.info(
        f"[LG] synthesis_node start review={review_id} "
        f"agg={aggregate_score} domains={list(domain_scores.keys())} "
        f"findings={len(all_findings)} blockers={len(all_blockers)} adrs={len(all_adrs)}"
    )

    fallback_decision = _determine_decision(aggregate_score, all_blockers)
    fallback_result = {
        "final_domain_scores":   dict(domain_scores),
        "score_corrections":     [],
        "retain_blocker_ids":    None,
        "filtered_adr_ids":      [a.get("id") for a in all_adrs if a.get("id")],
        "removed_adr_ids":       [],
        "duplicate_finding_ids": [],
        "executive_rationale":   "Synthesis step unavailable. Domain scores used as-is.",
        "final_decision":        fallback_decision,
        "tokens_used":           0,
    }

    # ── Build synthesis prompt ────────────────────────────────────────────────
    try:
        from app.agents.enhanced_orchestrator import EnhancedARBOrchestrator
        system_prompt = EnhancedARBOrchestrator(db)._get_synthesis_system_prompt()
    except Exception as exc:
        logger.warning(f"[LG] synthesis_node failed to load system prompt ({exc}) — using fallback")
        return {"synthesis_result": fallback_result}

    score_lines = "\n".join(f"  {d:<20} rag_score={s}" for d, s in domain_scores.items())
    blocker_lines = "\n".join(
        f"  id={b.get('id', b.get('blocker_id', '?'))} "
        f"check_category={b.get('check_category', '?')} "
        f"[{'SEC/DR' if b.get('is_security_or_dr') else 'OTHER '}] "
        f"{b.get('domain_slug', b.get('domain', ''))} — {b.get('title', '')} "
        f"(is_security_or_dr={b.get('is_security_or_dr')})"
        for b in all_blockers
    ) or "  (none)"
    adr_lines = "\n".join(
        f"  {a.get('id', '?')} | {a.get('adr_type', '?')} | {a.get('title', a.get('decision', ''))}"
        for a in all_adrs
    ) or "  (none)"

    amber_red  = [f for f in all_findings if (f.get("rag_score") or 5) <= 3]
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in amber_red:
        by_cat[f.get("check_category") or "UNKNOWN"].append(f)

    finding_lines: List[str] = []
    for cat, findings in sorted(by_cat.items()):
        domains_in_cat = {f.get("domain_slug") or f.get("domain") or "?" for f in findings}
        flag = "  ← MULTI-DOMAIN — deduplication candidate" if len(domains_in_cat) > 1 else ""
        finding_lines.append(f"\n  check_category: {cat}{flag}")
        for f in findings:
            dom = f.get("domain_slug") or f.get("domain") or "?"
            finding_lines.append(
                f"    id={f.get('id', '?')}  domain={dom}  rag={f.get('rag_score', '?')}  {f.get('title', '')}"
            )
    finding_summary = "\n".join(finding_lines)[:4000] or "  (no RED/AMBER findings)"

    user_prompt = f"""== SYNTHESIS INPUT ==
review_id:       {review_id}
solution_name:   {solution_name}
aggregate_score: {aggregate_score}

== DOMAIN SCORES FROM DOMAIN AGENTS ==
{score_lines}

== BLOCKERS (with check_category for consolidation) ==
{blocker_lines}

== ADRs TO GATE ==
{adr_lines}

== RED/AMBER FINDINGS GROUPED BY check_category ==
(Groups marked MULTI-DOMAIN contain findings from 2+ domains — primary deduplication candidates)
{finding_summary}

== OUTPUT SCHEMA ==
{{
  "scoreCorrections": [
    {{"domain": "example_domain", "original_score": 3, "corrected_score": 2, "reason": "Specific cross-domain reason"}}
  ],
  "retainBlockerIds": ["INF-BLK-01", "NFR-BLK-05"],
  "filteredAdrIds": ["ADR-SOL-01"],
  "removedAdrIds":  [],
  "duplicateFindingIds": ["NFR-F03", "NFR-F05"],
  "executiveRationale": "4-6 sentence paragraph written in EA voice for the ARB panel summarising the overall assessment, key risks, and recommended path forward",
  "finalDecision": "approve | approve_with_conditions | defer | reject"
}}"""

    # ── LLM call via LLMService (same path as domain agents — reliable for all providers) ──
    from app.services.llm_service import llm_service, LLMService
    logger.info(f"[LG] synthesis_node calling LLM provider={settings.LLM_PROVIDER}")
    try:
        response = await llm_service.generate_completion(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=int(settings.LLM_MAX_TOKENS),
            timeout=120,
            db=db,
        )
    except BaseException as exc:
        logger.warning(f"[LG] synthesis_node LLM call failed ({type(exc).__name__}: {exc}) — using fallback")
        fallback_result["executive_rationale"] = f"Synthesis step unavailable ({type(exc).__name__}). Domain scores used as-is."
        return {"synthesis_result": fallback_result}

    raw = response.get("content", "")
    tokens_used = response.get("tokens_used", 0)
    logger.info(f"[LG] synthesis_node LLM call complete tokens={tokens_used}")

    try:
        parsed: Dict[str, Any] = LLMService.parse_json_from_llm(raw)
    except Exception as exc:
        logger.warning(f"[LG] synthesis_node JSON parse failed ({exc}) — using fallback")
        return {"synthesis_result": fallback_result}

    # ── Apply score corrections with Tier-1 floors ───────────────────────────
    final_domain_scores = dict(domain_scores)
    score_corrections: List[Dict[str, Any]] = []
    for c in (parsed.get("scoreCorrections") or []):
        dom = c.get("domain", "")
        if dom not in domain_scores:
            logger.warning(f"[LG] Ignoring score correction for unknown domain '{dom}'")
            continue
        orig      = domain_scores[dom]
        corrected = max(1, min(5, int(c.get("corrected_score", orig))))
        is_sec_dr = dom in ("infrastructure", "nfr")
        if is_sec_dr and corrected > orig:
            logger.warning(f"[LG] Blocked raising {dom} score {orig}→{corrected}")
            continue
        if corrected != orig:
            final_domain_scores[dom] = corrected
            score_corrections.append({
                "domain": dom, "original_score": orig,
                "corrected_score": corrected, "reason": c.get("reason", ""),
            })

    # ── Blocker consolidation ─────────────────────────────────────────────────
    all_blocker_ids = {b.get("id", b.get("blocker_id")) for b in all_blockers if b.get("id") or b.get("blocker_id")}
    raw_retain = parsed.get("retainBlockerIds")
    if raw_retain and isinstance(raw_retain, list):
        retain_set = {i for i in raw_retain if i in all_blocker_ids}
        retain_blocker_ids = list(retain_set) if retain_set else list(all_blocker_ids)
    else:
        retain_blocker_ids = None  # keep all

    # ── ADR gate ──────────────────────────────────────────────────────────────
    all_adr_ids      = {a.get("id") for a in all_adrs if a.get("id")}
    filtered_adr_ids = [i for i in (parsed.get("filteredAdrIds") or list(all_adr_ids)) if i in all_adr_ids]
    removed_adr_ids  = [i for i in (parsed.get("removedAdrIds") or []) if i in all_adr_ids]

    # ── Finding deduplication ─────────────────────────────────────────────────
    all_finding_ids       = {f.get("id") for f in all_findings if f.get("id")}
    duplicate_finding_ids = [fid for fid in (parsed.get("duplicateFindingIds") or []) if fid in all_finding_ids]

    # ── Recompute final decision with Tier-1 floors ───────────────────────────
    retained_blockers = (
        [b for b in all_blockers if (b.get("id") or b.get("blocker_id")) in retain_blocker_ids]
        if retain_blocker_ids is not None else all_blockers
    )
    final_scores  = list(final_domain_scores.values())
    final_agg     = min(final_scores) if final_scores else aggregate_score
    has_sec_dr    = any(b.get("is_security_or_dr") for b in retained_blockers)
    if has_sec_dr:
        final_agg = 1
    final_decision = _determine_decision(final_agg, retained_blockers)

    logger.info(
        f"[LG] synthesis_node done final_decision={final_decision} "
        f"corrections={len(score_corrections)} removed_adrs={len(removed_adr_ids)} "
        f"dup_findings={len(duplicate_finding_ids)}"
    )

    synthesis_result = {
        "final_domain_scores":   final_domain_scores,
        "score_corrections":     score_corrections,
        "retain_blocker_ids":    retain_blocker_ids,
        "filtered_adr_ids":      filtered_adr_ids,
        "removed_adr_ids":       removed_adr_ids,
        "duplicate_finding_ids": duplicate_finding_ids,
        "executive_rationale":   parsed.get("executiveRationale", ""),
        "final_decision":        final_decision,
        "tokens_used":           tokens_used,
    }
    return {"synthesis_result": synthesis_result}


# ── Node 5: build_report_node ─────────────────────────────────────────────────

async def build_report_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Assemble the final report dict — identical schema to EnhancedARBOrchestrator.run_review().

    _persist_results() in agent.py consumes this dict unchanged.
    """
    db: Session         = config["configurable"]["db"]
    review_id: str      = state["review_id"]
    synthesis           = state.get("synthesis_result", {})
    domain_scores       = dict(state.get("domain_scores", {}))
    domain_summaries    = dict(state.get("domain_summaries", {}))
    all_findings        = list(state.get("all_findings", []))
    all_blockers        = list(state.get("all_blockers", []))
    all_recommendations = list(state.get("all_recommendations", []))
    all_actions         = list(state.get("all_actions", []))
    all_adrs            = list(state.get("all_adrs", []))
    all_nfr_scorecard   = list(state.get("all_nfr_scorecard", []))
    kb_sources          = list(state.get("kb_sources", []))
    total_tokens        = (state.get("total_tokens") or 0) + (synthesis.get("tokens_used") or 0)
    failed_domains      = list(state.get("failed_domains", []))
    domains             = list(state.get("domains", []))

    # Apply synthesis corrections to domain_scores
    for slug, corrected in synthesis.get("final_domain_scores", {}).items():
        domain_scores[slug] = corrected
        if slug in domain_summaries:
            domain_summaries[slug]["rag_score"]  = corrected
            domain_summaries[slug]["rag_label"]  = _score_to_label(corrected)

    final_scores    = list(domain_scores.values())
    aggregate_score = min(final_scores) if final_scores else (state.get("aggregate_score") or 3)
    has_sec_dr      = any(b.get("is_security_or_dr") for b in all_blockers)
    if has_sec_dr:
        aggregate_score = 1
    aggregate_rag_label = _score_to_label(aggregate_score)

    # Filter ADRs through synthesis gate
    filtered_adr_ids = set(synthesis.get("filtered_adr_ids") or [])
    if filtered_adr_ids:
        all_adrs = [a for a in all_adrs if a.get("id") in filtered_adr_ids]

    # Filter blockers through synthesis consolidation
    retain_blocker_ids = synthesis.get("retain_blocker_ids")
    if retain_blocker_ids is not None:
        retain_set  = set(retain_blocker_ids)
        all_blockers = [b for b in all_blockers if (b.get("id") or b.get("blocker_id")) in retain_set]

    # Suppress duplicate findings
    dup_ids = set(synthesis.get("duplicate_finding_ids") or [])
    if dup_ids:
        all_findings = [f for f in all_findings if f.get("id") not in dup_ids]

    decision = synthesis.get("final_decision") or _determine_decision(aggregate_score, all_blockers)

    # Fetch existing report_json to preserve form_data and other non-AI keys
    from app.db.review_models import Review
    review = db.query(Review).filter(Review.id == review_id).first()
    existing_report_json = review.report_json if review else {}

    ai_review = {
        "decision":             decision,
        "aggregate_score":      aggregate_score,
        "aggregate_rag_label":  aggregate_rag_label,
        "domain_scores":        domain_scores,
        "domain_summaries":     domain_summaries,
        "findings":             all_findings,
        "blockers":             all_blockers,
        "recommendations":      all_recommendations,
        "actions":              all_actions,
        "adrs":                 all_adrs,
        "nfr_scorecard":        all_nfr_scorecard,
        "kb_sources_cited":     kb_sources,
        "executive_rationale":  synthesis.get("executive_rationale", ""),
        "score_corrections":    synthesis.get("score_corrections", []),
        "removed_adr_ids":      synthesis.get("removed_adr_ids", []),
        "processed_at":         datetime.now(timezone.utc).isoformat(),
    }

    synthesis_fell_back = (synthesis.get("executive_rationale") or "").startswith("Synthesis step unavailable")

    final_report = {
        **(existing_report_json or {}),
        "ai_review":                    ai_review,
        "decision":                     decision,
        "aggregate_score":              aggregate_score,
        "aggregate_rag_label":          aggregate_rag_label,
        "recommended_decision":         decision,
        "domain_scores":                domain_scores,
        "domain_summaries":             domain_summaries,
        "findings":                     all_findings,
        "blockers":                     all_blockers,
        "recommendations":              all_recommendations,
        "actions":                      all_actions,
        "adrs":                         all_adrs,
        "nfr_scorecard":                all_nfr_scorecard,
        "kb_sources_cited":             kb_sources,
        "total_tokens_used":            total_tokens,
        "domains_evaluated":            domains,
        "domain_payloads":              [state["domain_results"].get(s, {}) for s in domains],
        "failed_domains":               failed_domains,
        "synthesis_ran":                not synthesis_fell_back,
        "synthesis_score_corrections":  len(synthesis.get("score_corrections", [])),
        "synthesis_removed_adrs":       len(synthesis.get("removed_adr_ids", [])),
        "synthesis_dedup_findings":     len(synthesis.get("duplicate_finding_ids", [])),
    }

    logger.info(
        f"[LG] build_report_node done review={review_id} "
        f"decision={decision} agg={aggregate_score}({aggregate_rag_label}) "
        f"findings={len(all_findings)} failed_domains={failed_domains}"
    )

    return {"final_report": final_report}
