"""
Enhanced ARB Orchestrator — aligned with the Pre-ARB AI Agent spec.

Key design choices (matching the Supabase edge-function behaviour):
- Sequential domain calls  (not parallel) — protects Gemini 15 RPM free-tier limit
- Synthesis LLM step       — runs after all domain agents; rationalises cross-domain
                             scores, gates ADRs, writes executive rationale (Tier 2)
- report_json merging      — ai_review key added alongside existing form_data
- rag_score based scoring  — domain score = summary.rag_score (1-5, LLM-authoritative)
- Decision logic           — matches TypeScript determineDecision()
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.agents.enhanced_domain_agents import EnhancedDomainValidationAgent, _rag_score_to_severity
from app.services.artefact_service import ArtefactService
from app.db.review_models import Review
from app.db.metadata_models import ChecklistQuestion
from app.core.config import settings
from app.core.db_config import db_config

logger = logging.getLogger(__name__)


class EnhancedARBOrchestrator:
    """Orchestrates per-domain validation and aggregates results."""

    def __init__(self, db: Session):
        self.db              = db
        self.domain_agent    = EnhancedDomainValidationAgent(db)
        self.artefact_service = ArtefactService(db)

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_review(
        self,
        review_id: str,
        checklist_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run complete ARB review and return the merged report dict."""
        t0 = time.time()
        logger.info(f"[ORCHESTRATOR] Starting review={review_id}")

        review = self.db.query(Review).filter(Review.id == review_id).first()
        if not review:
            raise ValueError(f"Review {review_id} not found")

        domains = self._get_domains_from_scope(review.scope_tags or [])
        logger.info(f"[ORCHESTRATOR] Domains to process: {domains}")

        # ── Sequential domain calls ───────────────────────────────────────────
        domain_payloads: List[Dict[str, Any]] = []
        for domain_slug in domains:
            domain_checklist = dict(checklist_data.get("domain_data", {}).get(domain_slug, {}))
            domain_checklist["domain_metadata"] = {
                **self._get_domain_metadata(domain_slug),
                "solution_name": review.solution_name,
            }
            # For solution domain, pass full project info so the LLM can assess it
            if domain_slug == "solution":
                fd = (review.report_json or {}).get("form_data", {})
                domain_checklist["domain_metadata"].update({
                    "problem_statement":        fd.get("problem_statement") or "(not provided)",
                    "business_drivers":         fd.get("business_drivers") or [],
                    "stakeholders":             fd.get("stakeholders") or [],
                    "target_business_outcomes": fd.get("growth_plans") or fd.get("target_business_outcomes") or "(not provided)",
                })
            try:
                payload = await self._call_domain_with_retry(
                    review_id=review_id,
                    domain_slug=domain_slug,
                    domain_checklist=domain_checklist,
                )
                domain_payloads.append({"domain_slug": domain_slug, "payload": payload})
            except Exception as exc:
                logger.error(f"[ORCHESTRATOR] Domain {domain_slug} failed after all retries: {exc}")
                domain_payloads.append({
                    "domain_slug": domain_slug,
                    "payload": {
                        "domain": domain_slug,
                        "session_id": review_id,
                        "summary": {
                            "rag_score": 2, "rag_label": "RED",
                            "overall_readiness": "DEFER",
                            "rationale": f"Domain agent error — manual review required: {exc}",
                            "evidence_quality": "ABSENT",
                            "total_findings": 0, "blocker_count": 0, "mandatory_gaps": 0,
                        },
                        "blockers": [], "recommendations": [],
                        "findings": [], "actions": [], "adrs": [],
                        "error": str(exc),
                    },
                })

            if domain_slug != domains[-1]:
                await asyncio.sleep(db_config(self.db, "agent.domain_delay_seconds", settings.INTER_DOMAIN_DELAY_S))

        # ── Aggregate ─────────────────────────────────────────────────────────
        domain_scores: Dict[str, int] = {}
        domain_summaries: Dict[str, Dict[str, Any]] = {}
        all_findings:  List[Dict[str, Any]] = []
        all_blockers:  List[Dict[str, Any]] = []
        all_recommendations: List[Dict[str, Any]] = []
        all_actions:   List[Dict[str, Any]] = []
        all_adrs:      List[Dict[str, Any]] = []
        total_tokens = 0

        for entry in domain_payloads:
            slug    = entry["domain_slug"]
            payload = entry["payload"]
            summary = payload.get("summary", {})

            raw_score = summary.get("rag_score", 3)
            rag_score = max(1, min(5, int(raw_score)))
            domain_scores[slug] = rag_score
            domain_summaries[slug] = summary

            # Findings enriched with domain slug
            for f in payload.get("findings", []):
                all_findings.append({**f, "domain_slug": slug})

            # Blockers: only trust blockers from domains that actually scored 1 (BLOCKER).
            # LLMs occasionally emit items in blockers[] while scoring the domain AMBER/RED —
            # that is contradictory output; discard to prevent false reject decisions.
            spurious_blockers = payload.get("blockers", [])
            if rag_score == 1:
                for b in spurious_blockers:
                    all_blockers.append({**b, "domain_slug": slug})
            elif spurious_blockers:
                logger.warning(
                    f"[ORCHESTRATOR] Discarding {len(spurious_blockers)} blocker(s) from "
                    f"domain '{slug}' (domain scored rag_score={rag_score}, not 1 — "
                    f"inconsistent LLM output; treating as findings only)"
                )

            all_recommendations.extend(payload.get("recommendations", []))
            all_actions.extend(payload.get("actions", []))
            all_adrs.extend(payload.get("adrs", []))
            total_tokens += payload.get("tokens_used", 0)

        scores = list(domain_scores.values())

        # Tier-1: min aggregate, forced to 1 if any Security/DR blocker exists.
        has_security_dr_blocker = any(
            b.get("is_security_or_dr") for b in all_blockers
        )
        if has_security_dr_blocker:
            aggregate_score = 1
        else:
            aggregate_score = min(scores) if scores else 3

        # ── Tier 2: Synthesis LLM call ────────────────────────────────────────
        synthesis = await self._run_synthesis(
            review_id=review_id,
            solution_name=review.solution_name,
            domain_scores=domain_scores,
            all_findings=all_findings,
            all_blockers=all_blockers,
            all_adrs=all_adrs,
            all_actions=all_actions,
            aggregate_score=aggregate_score,
        )
        total_tokens += synthesis["tokens_used"]

        # Apply synthesis score corrections (Tier-1 floors enforced inside _run_synthesis)
        for slug, corrected in synthesis["final_domain_scores"].items():
            domain_scores[slug] = corrected
            # Keep domain_summaries rag_label in sync with corrected score
            if slug in domain_summaries:
                domain_summaries[slug]["rag_score"] = corrected
                domain_summaries[slug]["rag_label"] = self._score_to_label(corrected)

        # Recompute aggregate after corrections (Tier-1 floor still applies)
        final_scores = list(domain_scores.values())
        aggregate_score = min(final_scores) if final_scores else aggregate_score
        if has_security_dr_blocker:
            aggregate_score = 1

        # Filter ADRs through synthesis gate
        filtered_adr_ids = set(synthesis["filtered_adr_ids"])
        all_adrs = [a for a in all_adrs if a.get("id") in filtered_adr_ids] if filtered_adr_ids else all_adrs

        # Filter blockers through synthesis consolidation (deduplicate cross-domain duplicates)
        retain_blocker_ids = synthesis.get("retain_blocker_ids")
        if retain_blocker_ids is not None:
            retain_set = set(retain_blocker_ids)
            all_blockers = [b for b in all_blockers if (b.get("id") or b.get("blocker_id")) in retain_set]

        # Filter findings through synthesis deduplication (suppress cross-domain duplicates)
        duplicate_finding_ids = set(synthesis.get("duplicate_finding_ids") or [])
        if duplicate_finding_ids:
            before = len(all_findings)
            all_findings = [f for f in all_findings if f.get("id") not in duplicate_finding_ids]
            logger.info(
                f"[ORCHESTRATOR] Suppressed {before - len(all_findings)} duplicate finding(s) "
                f"via synthesis deduplication: {sorted(duplicate_finding_ids)}"
            )

        aggregate_rag_label = self._score_to_label(aggregate_score)
        decision            = self._determine_decision(aggregate_score, all_findings, all_blockers, domain_scores)

        # Collect kb_sources from all domain payloads
        kb_sources: List[str] = []
        for entry in domain_payloads:
            src = entry["payload"].get("summary", {}).get("kb_references") or []
            kb_sources.extend(src)
        kb_sources = list(dict.fromkeys(kb_sources))  # deduplicate, preserve order

        # Extract nfr_scorecard rows emitted by the NFR domain agent
        all_nfr_scorecard: List[Dict[str, Any]] = []
        for entry in domain_payloads:
            rows = entry["payload"].get("nfr_scorecard") or []
            all_nfr_scorecard.extend(rows)

        # Extract per-domain summaries (full DomainSummary objects)
        domain_summaries: Dict[str, Any] = {}
        for entry in domain_payloads:
            slug    = entry["domain_slug"]
            payload = entry["payload"]
            summary = dict(payload.get("summary", {}))
            summary["domain"] = slug
            domain_summaries[slug] = summary

        total_duration_s = time.time() - t0
        logger.info(
            f"[ORCHESTRATOR] Done — decision={decision} agg={aggregate_score}({aggregate_rag_label}) "
            f"findings={len(all_findings)} blockers={len(all_blockers)} "
            f"actions={len(all_actions)} adrs={len(all_adrs)} "
            f"score_corrections={len(synthesis['score_corrections'])} "
            f"removed_adrs={len(synthesis['removed_adr_ids'])} "
            f"suppressed_dup_findings={len(synthesis['duplicate_finding_ids'])} "
            f"tokens={total_tokens} duration={total_duration_s:.2f}s"
        )

        # ── Process NFR Criteria (form-based, for backward compat) ────────────
        nfr_analysis = self._process_nfr_criteria(review, domain_scores)

        # ── Build fullReport (merges into existing report_json) ───────────────
        existing_report_json = review.report_json or {}
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
            "nfr_analysis":         nfr_analysis,
            "kb_sources_cited":     kb_sources,
            "executive_rationale":  synthesis["executive_rationale"],
            "score_corrections":    synthesis["score_corrections"],
            "removed_adr_ids":      synthesis["removed_adr_ids"],
            "processed_at":         datetime.now(timezone.utc).isoformat(),
        }

        return {
            **existing_report_json,
            "ai_review":              ai_review,
            "decision":               decision,
            "aggregate_score":        aggregate_score,
            "aggregate_rag_label":    aggregate_rag_label,
            "recommended_decision":   decision,
            "domain_scores":          domain_scores,
            "domain_summaries":       domain_summaries,
            "findings":               all_findings,
            "blockers":               all_blockers,
            "recommendations":        all_recommendations,
            "actions":                all_actions,
            "adrs":                   all_adrs,
            "nfr_scorecard":          all_nfr_scorecard,
            "kb_sources_cited":       kb_sources,
            "total_tokens_used":      total_tokens,
            "processing_time_seconds": total_duration_s,
            "domains_evaluated":      domains,
            "domain_payloads":        [e["payload"] for e in domain_payloads],
        }

    # ── Checklist preparation ─────────────────────────────────────────────────

    async def prepare_checklist_data(self, review_id: str) -> Dict[str, Any]:
        """Extract checklist items from report_json.form_data.domain_data."""
        review = self.db.query(Review).filter(Review.id == review_id).first()
        if not review or not review.report_json:
            logger.warning(f"[ORCHESTRATOR] No report_json for review {review_id}")
            return {"domain_data": {}}

        form_data = review.report_json.get("form_data", {})
        all_questions = self.db.query(ChecklistQuestion).all()
        question_cache = {q.question_code: q.question_text for q in all_questions}

        domain_data: Dict[str, Any] = {}

        # New schema: form_data.domain_data.{domain}.checklist
        for domain, data in form_data.get("domain_data", {}).items():
            items = []
            checklist = data.get("checklist", {})
            evidence  = data.get("evidence", {})
            for code, answer in checklist.items():
                items.append({
                    "question_code": code,
                    "question_text": question_cache.get(code, code),
                    "answer":        answer,
                    "evidence":      evidence.get(code, ""),
                })
            if items:
                domain_data[domain] = {"checklist_items": items}

        # Legacy schema: form_data.{domain}_checklist (backward compat)
        for key, value in form_data.items():
            if key.endswith("_checklist"):
                domain = key.replace("_checklist", "")
                if domain not in domain_data:  # Don't overwrite new schema if present
                    items = []
                    evidence_key = f"{domain}_evidence"
                    evidence = form_data.get(evidence_key, {})
                    for code, answer in value.items():
                        items.append({
                            "question_code": code,
                            "question_text": question_cache.get(code, code),
                            "answer":        answer,
                            "evidence":      evidence.get(code, ""),
                        })
                    if items:
                        domain_data[domain] = {"checklist_items": items}

        logger.info(f"[ORCHESTRATOR] Checklist prepared for {len(domain_data)} domains")
        return {"domain_data": domain_data}

    def _process_nfr_criteria(self, review: Review, domain_scores: Dict[str, int]) -> Dict[str, Any]:
        """Process NFR criteria from form data and analyze compliance"""
        if not review.report_json:
            return {"criteria": [], "summary": {"total_criteria": 0, "compliant_count": 0, "average_score": 0}}
        
        form_data = review.report_json.get("form_data", {})
        nfr_criteria = form_data.get("nfr_criteria", [])
        
        if not nfr_criteria:
            return {"criteria": [], "summary": {"total_criteria": 0, "compliant_count": 0, "average_score": 0}}
        
        processed_criteria = []
        compliant_count = 0
        total_score = 0
        
        for criterion in nfr_criteria:
            # Calculate compliance based on score
            score = criterion.get("score", 0)
            is_compliant = score >= 7  # 7+ out of 10 considered compliant
            if is_compliant:
                compliant_count += 1
            total_score += score
            
            # Determine compliance level
            if score >= 9:
                compliance_level = "fully_compliant"
            elif score >= 7:
                compliance_level = "compliant"
            elif score >= 5:
                compliance_level = "partially_compliant"
            else:
                compliance_level = "non_compliant"
            
            processed_criteria.append({
                "id": criterion.get("id"),
                "category": criterion.get("category"),
                "criteria": criterion.get("criteria"),
                "target_value": criterion.get("target_value"),
                "actual_value": criterion.get("actual_value"),
                "score": score,
                "compliance_level": compliance_level,
                "is_compliant": is_compliant,
                "evidence": criterion.get("evidence"),
            })
        
        # Calculate summary statistics
        total_criteria = len(processed_criteria)
        average_score = round(total_score / total_criteria, 1) if total_criteria > 0 else 0
        compliance_percentage = round((compliant_count / total_criteria) * 100, 1) if total_criteria > 0 else 0
        
        # Group by category for analysis
        category_analysis = {}
        for criterion in processed_criteria:
            category = criterion["category"]
            if category not in category_analysis:
                category_analysis[category] = {
                    "total": 0,
                    "compliant": 0,
                    "average_score": 0,
                    "scores": []
                }
            
            category_analysis[category]["total"] += 1
            category_analysis[category]["scores"].append(criterion["score"])
            if criterion["is_compliant"]:
                category_analysis[category]["compliant"] += 1
        
        # Calculate category averages
        for category, analysis in category_analysis.items():
            if analysis["scores"]:
                analysis["average_score"] = round(sum(analysis["scores"]) / len(analysis["scores"]), 1)
                analysis["compliance_percentage"] = round((analysis["compliant"] / analysis["total"]) * 100, 1)
            del analysis["scores"]  # Remove raw scores to clean up output
        
        # Generate NFR domain score (affects overall decision)
        nfr_domain_score = min(5, max(1, round(average_score / 2)))  # Convert 0-10 to 1-5 scale
        
        return {
            "criteria": processed_criteria,
            "summary": {
                "total_criteria": total_criteria,
                "compliant_count": compliant_count,
                "non_compliant_count": total_criteria - compliant_count,
                "average_score": average_score,
                "compliance_percentage": compliance_percentage,
                "nfr_domain_score": nfr_domain_score
            },
            "category_analysis": category_analysis
        }

    # ── Tier 2: Synthesis LLM call ────────────────────────────────────────────

    _SYNTHESIS_SYSTEM_PROMPT = """You are a senior Principal Enterprise Architect with 20 years of experience
chairing ARB panels. You are writing the final synthesis of an AI-assisted architectural review. All domain
agents have completed their assessments and you are now producing the executive view.

ARB SCOPE REMINDER: This review covers architectural design completeness only — not operational readiness,
test results, or deployed-state evidence. Your synthesis must stay within this scope.

YOUR SIX RESPONSIBILITIES:

1. SCORE RATIONALISATION — review domain scores for cross-cutting consistency:
   • You MAY LOWER a domain score if cross-domain evidence reveals a compounding risk not visible in
     isolation (e.g. Security RED but DR domain GREEN — DR should reflect the security gap).
   • You MAY NEVER RAISE Security or DR/HA domain scores above RED (rag_score 2) unless the domain
     agent's own findings contain positive architectural evidence supporting a higher score.
   • For all other domains you may raise or lower scores by at most 1 point when cross-domain evidence
     clearly supports it. Document every correction with a specific reason.
   • Output scoreCorrections[] for every change. If no corrections needed, output an empty array.

2. BLOCKER CONSOLIDATION — deduplicate cross-domain blockers:
   Multiple domain agents independently assess overlapping concerns — the same architectural gap
   may appear as a blocker in more than one domain. Consolidate into one canonical blocker per
   distinct issue.

   PRIMARY CONSOLIDATION SIGNAL — check_category:
   Two blockers sharing the same check_category from different domains almost always describe the
   same underlying architectural gap. Confirm that the gap (the missing design element or absent
   control) is the same issue, not merely the same category coincidentally applied.

   CONSOLIDATION RULES:
   • Use check_category as the first grouping key — same category across 2+ domains is a consolidation candidate.
   • Confirm semantic equivalence: the missing design element or absent control must be the same gap,
     even when phrased differently across domains.
   • Where two or more blockers describe the same underlying gap, retain ONE — prefer the blocker
     from the domain most architecturally responsible for that control area.
   • Output retainBlockerIds[] — the exact IDs of the blockers to keep after consolidation.
     All blocker IDs not in this list are treated as redundant duplicates and discarded.
   • If all blockers are distinct issues, retainBlockerIds must include every blocker ID.
   • Never drop a blocker to soften the outcome — only consolidate genuine cross-domain duplicates.

3. ADR GATE — apply the architectural-choice test to every ADR in the input:
   RETAIN an ADR if it records: a deliberate design decision between viable options, a technology
   deviation from EA standards, or a formal exception (WAIVER) for a genuine design risk.
   REMOVE an ADR if it was generated merely because documentation or a plan is absent — those should
   be actions, not ADRs. A missing VAPT plan → action. A decision to skip encryption at rest → ADR.
   Output filteredAdrIds (retained) and removedAdrIds (removed).

4. EXECUTIVE RATIONALE — write 4–6 sentences as a senior EA would speak at an ARB panel:
   Write in first-person plural ("The panel notes…", "We find…", "The architecture demonstrates…").
   Sound like a considered human judgement, not a system-generated checklist.
   • Open with what the solution gets right — acknowledge genuine strengths before gaps.
   • Describe the critical gaps in concrete terms — name the specific controls or design elements
     missing, not just the domain category. Reference the solution by name.
   • If there are blockers, explain WHY they prevent approval — the business or security consequence,
     not just that a standard is violated.
   • Close with a clear path forward: what the SA team must produce, and at what level of completeness,
     before the panel can reconsider.
   Avoid: bullet-point-in-prose style, hedging language ("it appears", "may be"), repeating the same
   gap twice with different words, and generic phrases like "the solution lacks documentation".

5. FINAL DECISION — one of: approve | approve_with_conditions | defer | reject
   Apply these Tier-1 floors using the RETAINED blockers after consolidation:
   • Any Security or DR/HA blocker (is_security_or_dr = true) at rag_score ≤ 1 → reject
   • Any Security or DR/HA blocker at rag_score 2 → defer
   • Non-security/DR blockers or score ≤ 3 → approve_with_conditions
   • Score ≥ 4 and no blockers → approve

6. FINDING DEDUPLICATION — identify findings that describe the same architectural gap from different
   domain perspectives. Domain agents for overlapping areas independently assess many of the same
   control categories, producing findings for the same gap under different IDs.

   PRIMARY DEDUPLICATION SIGNAL — check_category:
   When two or more findings share the same check_category from different domains, they are strong
   candidates for deduplication. Confirm that the gap described (missing design element, absent
   control, incomplete specification) is the same underlying issue.

   DEDUPLICATION RULES:
   • The findings input is grouped by check_category. Groups marked MULTI-DOMAIN contain findings
     from 2+ domains and are your primary candidates.
   • For each multi-domain group: determine whether the findings describe the same gap.
     If yes, identify the canonical finding (prefer the domain most responsible for that control area)
     and mark the others as duplicates.
   • Mark as duplicate ONLY when a clearly superior canonical finding already covers the same gap.
     When findings add genuinely different perspectives or severity levels, retain both.
   • Output duplicateFindingIds[] — IDs of findings made redundant by a canonical finding.
     The canonical finding itself must NOT appear in this list.
   • If no duplicates are found, output an empty array — never force deduplication.

Respond ONLY with a valid JSON object. No preamble, no markdown outside the JSON."""

    def _get_synthesis_system_prompt(self) -> str:
        """Return synthesizer.system from DB if configured, otherwise the hardcoded constant."""
        try:
            from app.db.admin_models import PromptTemplate
            db_prompt = (
                self.db.query(PromptTemplate)
                .filter(PromptTemplate.prompt_key == "synthesizer.system", PromptTemplate.is_active == True)
                .order_by(PromptTemplate.version.desc())
                .first()
            )
            if db_prompt and db_prompt.content:
                return db_prompt.content
        except Exception:
            pass
        return self._SYNTHESIS_SYSTEM_PROMPT

    async def _run_synthesis(
        self,
        review_id: str,
        solution_name: str,
        domain_scores: Dict[str, int],
        all_findings: List[Dict[str, Any]],
        all_blockers: List[Dict[str, Any]],
        all_adrs: List[Dict[str, Any]],
        all_actions: List[Dict[str, Any]],
        aggregate_score: int,
    ) -> Dict[str, Any]:
        """Run Tier-2 synthesis LLM call. Returns safe fallback on any error."""

        def _fallback(reason: str) -> Dict[str, Any]:
            has_sec_dr = any(b.get("is_security_or_dr") for b in all_blockers)
            has_any    = bool(all_blockers)
            if aggregate_score >= 4 and not has_any:
                fd = "approve"
            elif aggregate_score <= 1 and has_sec_dr:
                fd = "reject"
            elif has_sec_dr:
                fd = "defer"
            elif has_any or aggregate_score <= 3:
                fd = "approve_with_conditions"
            else:
                fd = "approve"
            return {
                "final_domain_scores":   dict(domain_scores),
                "score_corrections":     [],
                "retain_blocker_ids":    None,  # None = keep all (fallback doesn't deduplicate)
                "filtered_adr_ids":      [a["id"] for a in all_adrs if a.get("id")],
                "removed_adr_ids":       [],
                "duplicate_finding_ids": [],
                "executive_rationale":   f"Synthesis unavailable ({reason}). Domain scores used as-is.",
                "final_decision":        fd,
                "tokens_used":           0,
            }

        # Build user prompt
        from collections import defaultdict

        score_lines = "\n".join(
            f"  {d:<20} rag_score={s}" for d, s in domain_scores.items()
        )
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

        # Group RED/AMBER findings by check_category so the synthesizer can spot
        # cross-domain overlaps without having to scan a flat 27-item list.
        amber_red = [f for f in all_findings if (f.get("rag_score") or 5) <= 3]
        by_category: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for f in amber_red:
            by_category[f.get("check_category") or "UNKNOWN"].append(f)

        finding_lines: List[str] = []
        for cat, findings in sorted(by_category.items()):
            domains_in_cat = {f.get("domain_slug") or f.get("domain") or "?" for f in findings}
            overlap_flag = "  ← MULTI-DOMAIN — deduplication candidate" if len(domains_in_cat) > 1 else ""
            finding_lines.append(f"\n  check_category: {cat}{overlap_flag}")
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
  "executiveRationale": "4-6 sentence paragraph written in EA voice for the ARB panel",
  "finalDecision": "approve | approve_with_conditions | defer | reject"
}}"""

        logger.info(
            f"[SYNTHESIS] Starting synthesis review={review_id} "
            f"domains={list(domain_scores.keys())} blockers={len(all_blockers)} adrs={len(all_adrs)}"
        )

        try:
            response = await self.domain_agent.llm_service.generate_completion(
                prompt=user_prompt,
                system_prompt=self._get_synthesis_system_prompt(),
                temperature=db_config(self.db, "llm.temperature", settings.LLM_TEMPERATURE),
                max_tokens=int(db_config(self.db, "llm.max_tokens", settings.LLM_MAX_TOKENS)),
                timeout=60,
                db=self.db,
            )
        except Exception as exc:
            logger.warning(f"[SYNTHESIS] LLM call failed ({exc}) — using fallback")
            return _fallback(f"LLM error: {exc}")

        raw = response.get("content", "")
        tokens_used = response.get("tokens_used", 0)

        try:
            parsed = self.domain_agent.llm_service.parse_json_from_llm(raw)
        except Exception as exc:
            logger.warning(f"[SYNTHESIS] JSON parse failed ({exc}) — using fallback")
            return _fallback("parse failure")

        # Apply score corrections with Tier-1 floors
        final_domain_scores = dict(domain_scores)
        score_corrections: List[Dict[str, Any]] = []
        for c in (parsed.get("scoreCorrections") or []):
            dom       = c.get("domain", "")
            if dom not in domain_scores:
                # Synthesis hallucinated a domain not actually run (e.g. used schema example verbatim)
                logger.warning(f"[SYNTHESIS] Ignoring score correction for unknown domain '{dom}'")
                continue
            orig      = domain_scores[dom]
            corrected = max(1, min(5, int(c.get("corrected_score", orig))))
            is_sec_dr = dom in ("security", "infrastructure")
            if is_sec_dr and corrected > orig:
                logger.warning(f"[SYNTHESIS] Blocked raising {dom} score {orig}→{corrected}")
                continue
            if corrected != orig:
                final_domain_scores[dom] = corrected
                score_corrections.append({
                    "domain": dom, "original_score": orig,
                    "corrected_score": corrected, "reason": c.get("reason", ""),
                })

        # Blocker consolidation — filter to canonical set if synthesis provided retainBlockerIds
        all_blocker_ids = {b.get("id", b.get("blocker_id")) for b in all_blockers if b.get("id") or b.get("blocker_id")}
        raw_retain = parsed.get("retainBlockerIds")
        if raw_retain and isinstance(raw_retain, list):
            retain_set = {i for i in raw_retain if i in all_blocker_ids}
            # Safety: if synthesis returned an empty list (shouldn't happen), keep all
            retain_blocker_ids = list(retain_set) if retain_set else list(all_blocker_ids)
        else:
            retain_blocker_ids = None  # keep all

        # ADR gate
        all_adr_ids     = {a["id"] for a in all_adrs if a.get("id")}
        raw_filtered    = parsed.get("filteredAdrIds") or list(all_adr_ids)
        raw_removed     = parsed.get("removedAdrIds")  or []
        filtered_adr_ids = [i for i in raw_filtered if i in all_adr_ids]
        removed_adr_ids  = [i for i in raw_removed  if i in all_adr_ids]

        # Recompute final decision with Tier-1 floors (use retained blockers)
        retained_blockers = (
            [b for b in all_blockers if (b.get("id") or b.get("blocker_id")) in retain_blocker_ids]
            if retain_blocker_ids is not None else all_blockers
        )
        final_scores  = list(final_domain_scores.values())
        final_agg     = min(final_scores) if final_scores else aggregate_score
        has_sec_dr    = any(b.get("is_security_or_dr") for b in retained_blockers)
        has_any       = bool(retained_blockers)
        if has_sec_dr:
            final_agg = 1
        if final_agg >= 4 and not has_any:
            final_decision = "approve"
        elif final_agg <= 1 and has_sec_dr:
            final_decision = "reject"
        elif has_sec_dr:
            final_decision = "defer"
        elif has_any or final_agg <= 3:
            final_decision = "approve_with_conditions"
        else:
            final_decision = "approve"

        executive_rationale = parsed.get("executiveRationale", "")

        # Finding deduplication — validate IDs against the actual finding set
        all_finding_ids = {f.get("id") for f in all_findings if f.get("id")}
        raw_dup_ids = parsed.get("duplicateFindingIds") or []
        duplicate_finding_ids = [fid for fid in raw_dup_ids if fid in all_finding_ids]

        dropped_blockers = len(all_blocker_ids) - len(retain_blocker_ids) if retain_blocker_ids is not None else 0
        logger.info(
            f"[SYNTHESIS] Done — final_decision={final_decision} "
            f"corrections={len(score_corrections)} removed_adrs={len(removed_adr_ids)} "
            f"dropped_duplicate_blockers={dropped_blockers} "
            f"duplicate_findings_suppressed={len(duplicate_finding_ids)} tokens={tokens_used}"
        )

        return {
            "final_domain_scores":   final_domain_scores,
            "score_corrections":     score_corrections,
            "retain_blocker_ids":    retain_blocker_ids,
            "filtered_adr_ids":      filtered_adr_ids,
            "removed_adr_ids":       removed_adr_ids,
            "duplicate_finding_ids": duplicate_finding_ids,
            "executive_rationale":   executive_rationale,
            "final_decision":        final_decision,
            "tokens_used":           tokens_used,
        }

    # ── Retry wrapper ─────────────────────────────────────────────────────────

    async def _call_domain_with_retry(
        self,
        review_id: str,
        domain_slug: str,
        domain_checklist: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Call validate_domain with 1 retry, 10 s apart.

        Attempt 1 — full content.
        Attempt 2 (retry, 10 s) — KB + artefact content reduced by 25 %
                                 to stay within LLM token limits.
        """
        max_attempts  = int(db_config(self.db, "agent.max_retries",          settings.AGENT_MAX_RETRIES))
        retry_delay   = float(db_config(self.db, "agent.retry_delay_seconds",  settings.AGENT_RETRY_DELAY_S))
        scale_on_retry = float(db_config(self.db, "agent.content_scale_on_retry", settings.CONTENT_SCALE_ON_RETRY))
        delays = [0] + [retry_delay] * (max_attempts - 1)
        last_exc: Exception = RuntimeError("no attempts made")
        for attempt, delay in enumerate(delays, start=1):
            if delay > 0:
                logger.warning(
                    f"[ORCHESTRATOR] {domain_slug} attempt {attempt} — "
                    f"retrying in {delay}s after: {last_exc}"
                )
                await asyncio.sleep(delay)
            # Reduce content on retry attempts to stay within token limits
            content_scale = scale_on_retry if attempt > 1 else 1.0
            if content_scale < 1.0:
                logger.info(
                    f"[ORCHESTRATOR] {domain_slug} attempt {attempt} — "
                    f"reducing KB/artefact content to {int(content_scale * 100)}%"
                )
            try:
                return await self.domain_agent.validate_domain(
                    review_id=review_id,
                    domain_slug=domain_slug,
                    checklist_data=domain_checklist,
                    content_scale=content_scale,
                )
            except Exception as exc:
                last_exc = exc
                logger.warning(f"[ORCHESTRATOR] {domain_slug} attempt {attempt} failed: {exc}")
        raise last_exc

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_domains_from_scope(self, scope_tags: List[str]) -> List[str]:
        """Return ordered list of domain slugs to evaluate."""
        from app.db.metadata_models import Domain
        active = {d.slug for d in self.db.query(Domain).filter(Domain.is_active == True).all()}

        ordered = []
        for tag in scope_tags:
            if tag in active and tag not in ordered:
                ordered.append(tag)
        # Always include solution domain first if available
        if "solution" in active and "solution" not in ordered:
            ordered.insert(0, "solution")
        return ordered

    def _score_to_label(self, score: int) -> str:
        if score >= 4:
            return "green"
        if score == 3:
            return "amber"
        return "red"

    def _get_domain_metadata(self, domain_slug: str) -> Dict[str, Any]:
        from app.db.metadata_models import Domain
        domain = self.db.query(Domain).filter(Domain.slug == domain_slug, Domain.is_active == True).first()
        if not domain:
            return {"name": domain_slug.title(), "description": ""}
        return {
            "name":        domain.name,
            "description": domain.description or "",
            "seq_number":  domain.seq_number,
        }

    def _determine_decision(
        self,
        aggregate_score: int,
        findings: List[Dict[str, Any]],
        blockers: List[Dict[str, Any]],
        domain_scores: Dict[str, int],
    ) -> str:
        """Spec-correct decision logic matching the Tier-1 gate rules.

        Security/DR architecture blockers are hard gates (reject/defer).
        Non-security/DR design blockers are conditions (approve_with_conditions).
        """
        has_security_dr_blocker = any(b.get("is_security_or_dr") for b in blockers)
        has_non_sec_dr_blocker  = any(not b.get("is_security_or_dr") for b in blockers)
        blocker_count = len(blockers)

        # Score 5 or 4, no blockers → APPROVE
        if aggregate_score >= 4 and blocker_count == 0:
            return "approve"
        # Security/DR blocker at score 1 → REJECT (unresolvable design gap)
        if aggregate_score <= 1 and has_security_dr_blocker:
            return "reject"
        # Security/DR blocker at score 2+ → DEFER (needs design rework)
        if has_security_dr_blocker:
            return "defer"
        # Non-security/DR blocker or score 2–3 → APPROVE_WITH_CONDITIONS
        if has_non_sec_dr_blocker or aggregate_score <= 3:
            return "approve_with_conditions"
        # Score 4+ no blockers (caught above) — fallback
        return "approve"
