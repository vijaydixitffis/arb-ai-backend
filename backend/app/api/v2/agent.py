"""
Agent orchestration endpoint.

POST /api/v1/agent/review  {reviewId} → trigger ARB review, persist results.
GET  /api/v1/agent/test-llm           → LLM connectivity check.

Persistence rules (aligned with schema 022):
- reviews: aggregate_rag_score, aggregate_rag_label, recommended_decision,
           decision_rationale, agent_run_at, kb_sources_cited, status, decision
- domain_scores: full DomainSummary (upsert on review_id+domain)
- blockers: new table — delete-then-insert on re-run
- recommendations: new table — delete-then-insert on re-run
- nfr_scorecard: new table — upsert on review_id+nfr_category
- findings: delete-then-insert on re-run; new columns populated
- actions: delete-then-insert on re-run; new columns populated
- adrs: delete-then-insert on re-run; new columns populated
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.core.config import settings
from app.core.db_config import db_config
from app.agents.enhanced_orchestrator import EnhancedARBOrchestrator
from app.agents.enhanced_domain_agents import _rag_score_to_severity

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Auth helper ───────────────────────────────────────────────────────────────

async def get_current_user(authorization: Optional[str] = Header(None)) -> Optional[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    payload = decode_access_token(authorization.split(" ", 1)[1])
    return payload.get("sub") if payload else None


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _normalise_decision(raw: str) -> str:
    mapping = {
        "approve":                 "approve",
        "approve_with_conditions": "approve_with_conditions",
        "approvewithconditions":   "approve_with_conditions",
        "defer":                   "defer",
        "reject":                  "reject",
    }
    return mapping.get((raw or "").lower().replace(" ", "_"), "defer")


def _parse_date(value: Any) -> Optional[date]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _due_date_from_days(due_days: Any) -> Optional[date]:
    if not due_days:
        return None
    try:
        import datetime as dt
        days = int(due_days)
        return (datetime.now(timezone.utc) + dt.timedelta(days=days)).date()
    except (TypeError, ValueError):
        return None


def _str(v: Any) -> Optional[str]:
    s = (v or "").strip() if isinstance(v, str) else str(v).strip() if v else None
    return s or None


def _arr(v: Any) -> Optional[List[str]]:
    if not v:
        return None
    if isinstance(v, list):
        return [str(x) for x in v if x] or None
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mark_agent_failed(db: Session, review_id: str, error_msg: str) -> None:
    """Persist agent_failed status so SA/EA can see and re-trigger the review."""
    from app.db.review_models import Review
    try:
        review = db.query(Review).filter(Review.id == review_id).first()
        if review:
            review.status = "agent_failed"
            existing = review.report_json or {}
            review.report_json = {**existing, "agent_error": error_msg}
            db.commit()
            logger.info(f"[AGENT] Marked review {review_id} as agent_failed")
    except Exception as e:
        logger.error(f"[AGENT] Could not persist agent_failed for {review_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/review")
async def trigger_review(
    request: Dict[str, str],
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger ARB review orchestrator and persist results."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    review_id = request.get("reviewId")
    if not review_id:
        raise HTTPException(status_code=400, detail="reviewId is required")

    # Gate: block re-trigger on truly final governance decisions.
    # agent_failed and review_ready (with domain errors) are explicitly allowed.
    from app.db.review_models import Review as ReviewModel
    review_row = db.query(ReviewModel).filter(ReviewModel.id == review_id).first()
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found")
    _BLOCKED_STATUSES = {"approved", "conditionally_approved", "rejected", "closed"}
    if review_row.status in _BLOCKED_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot re-trigger a review with status '{review_row.status}'",
        )

    is_retrigger = review_row.status in {"agent_failed", "review_ready"}
    use_mock = db_config(db, "llm.use_mock", settings.USE_MOCK_LLM)
    logger.info(
        f"[AGENT] trigger_review review_id={review_id} user={current_user} "
        f"status={review_row.status} retrigger={is_retrigger} mock={use_mock}"
    )

    try:
        if use_mock:
            from app.agents.mock_llm_populator import load_mock_result
            logger.info("[AGENT] USE_MOCK_LLM=true — skipping LLM calls, loading Bank EDMS fixture")
            result = await load_mock_result(review_id, db)
        else:
            orchestrator = EnhancedARBOrchestrator(db)
            result = await orchestrator.run_review(
                review_id=review_id,
                checklist_data=await orchestrator.prepare_checklist_data(review_id),
            )
    except Exception as exc:
        logger.exception(f"[AGENT] Orchestration failed for {review_id}")
        _mark_agent_failed(db, review_id, str(exc))
        raise HTTPException(status_code=500, detail=f"Review orchestration failed: {exc}")

    # Detect partial domain failures — domains that exhausted retries get a
    # synthetic error payload.  Flag them so the frontend can offer re-trigger.
    failed_domains = [
        p.get("domain", p.get("domain_slug", "unknown"))
        for p in result.get("domain_payloads", [])
        if p.get("error")
    ]
    if failed_domains:
        result["has_domain_errors"] = True
        result["failed_domains"]    = failed_domains
        logger.warning(f"[AGENT] review {review_id} has domain errors: {failed_domains}")

    try:
        _persist_results(db, review_id, result)
    except Exception as exc:
        logger.error(f"[AGENT] Persistence error for {review_id}: {exc}", exc_info=True)
        _mark_agent_failed(db, review_id, f"persistence error: {exc}")
        try:
            db.rollback()
        except Exception:
            pass

    return {
        "success":           True,
        "reviewId":          review_id,
        "decision":          result.get("decision"),
        "report":            result,
        "tokensUsed":        result.get("total_tokens_used", 0),
        "hasDomainErrors":   bool(failed_domains),
        "failedDomains":     failed_domains,
    }


@router.get("/test-llm")
async def test_llm(current_user: str = Depends(get_current_user)):
    from app.services.llm_service import llm_service
    try:
        result = await llm_service.generate_completion(
            prompt='{"test": "Say exactly: Hello from ARB AI Agent"}',
            system_prompt='You are a test assistant. Respond only with valid JSON.',
            temperature=0.1,
            max_tokens=64,
            timeout=30,
        )
        return {"success": True, "provider": result.get("provider"),
                "model": result.get("model"), "response": result.get("content"),
                "tokens_used": result.get("tokens_used")}
    except Exception as exc:
        from app.services.llm_service import llm_service as svc
        return {"success": False, "error": str(exc), "provider": svc.provider}


# ── Persistence ───────────────────────────────────────────────────────────────

def _persist_results(db: Session, review_id: str, result: Dict[str, Any]) -> None:
    from app.db.review_models import (
        Review, DomainScore, Finding, ADR, Action,
        Blocker, Recommendation, NFRScorecard,
    )

    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        logger.error(f"[AGENT] Review {review_id} not found — cannot persist")
        return

    # ── 1. Update review envelope ─────────────────────────────────────────────
    review.decision             = _normalise_decision(result.get("decision", "defer"))
    review.recommended_decision = review.decision
    review.status               = "review_ready"
    review.aggregate_rag_score  = result.get("aggregate_score")
    raw_label = result.get("aggregate_rag_label") or ""
    review.aggregate_rag_label  = raw_label.lower() or None
    review.decision_rationale   = _str(result.get("ai_review", {}).get("executive_rationale"))
    review.kb_sources_cited     = _arr(result.get("kb_sources_cited"))
    review.agent_run_at         = datetime.now(timezone.utc)
    review.tokens_used          = result.get("total_tokens_used", 0)
    review.processing_time_ms   = int(result.get("processing_time_seconds", 0) * 1000)
    review.reviewed_at          = datetime.now(timezone.utc)
    review.llm_raw_response     = json.dumps(result.get("ai_review", {}), default=str)

    # Flatten consolidated lists
    all_blockers_list = result.get("blockers", [])
    all_actions_list  = result.get("actions", [])
    review.consolidated_blockers = [
        {k: v for k, v in b.items() if k != "domain_slug"} for b in all_blockers_list
    ]
    review.consolidated_actions = [
        {k: v for k, v in a.items() if k != "domain_slug"} for a in all_actions_list
    ]

    existing = review.report_json or {}
    # Save the full result including domain_payloads, not just ai_review
    review.report_json = {
        **existing,
        **result,  # This includes ai_review, domain_payloads, and all other fields
    }

    try:
        with db.begin_nested():
            db.add(review)
            db.flush()
        logger.info(f"[AGENT] Review envelope updated decision={review.decision} agg={review.aggregate_rag_score}({review.aggregate_rag_label})")
    except Exception as exc:
        logger.error(f"[AGENT] Review row update failed (continuing): {exc}")

    # ── 2. Domain scores (delete stale rows, then upsert) ─────────────────────
    # Delete any domain rows from previous runs that are not in the current result.
    # This removes phantom rows (e.g. a "security" row from a buggy prior run)
    # without discarding rows that are simply being refreshed by this run.
    current_domain_slugs = set(result.get("domain_scores", {}).keys())
    try:
        with db.begin_nested():
            (
                db.query(DomainScore)
                .filter(
                    DomainScore.review_id == review_id,
                    ~DomainScore.domain.in_(current_domain_slugs),
                )
                .delete(synchronize_session=False)
            )
    except Exception as exc:
        logger.error(f"[AGENT] DomainScore stale-row delete failed: {exc}")

    domain_summaries = result.get("domain_summaries", {})
    saved_scores = 0
    for domain_slug, score_val in result.get("domain_scores", {}).items():
        try:
            summary = domain_summaries.get(domain_slug, {})
            existing_ds = (
                db.query(DomainScore)
                .filter(DomainScore.review_id == review_id, DomainScore.domain == domain_slug)
                .first()
            )
            fields = dict(
                score             = int(score_val),
                rag_label         = _str(summary.get("rag_label")),
                overall_readiness = _str(summary.get("overall_readiness")),
                executive_summary = _str(summary.get("executive_summary")),
                compliant_areas   = _arr(summary.get("compliant_areas")),
                gap_areas         = _arr(summary.get("gap_areas")),
                blocker_count     = int(summary.get("blocker_count") or 0),
                action_count      = int(summary.get("action_count") or 0),
                adr_count         = int(summary.get("adr_count") or 0),
                domain_specific_scores = summary.get("domain_specific_scores") or None,
                evidence_quality  = _str(summary.get("evidence_quality")),
                kb_references     = _arr(summary.get("kb_references")),
                generated_at      = datetime.now(timezone.utc),
                model_used        = _str(result.get("ai_review", {}).get("model_used")),
                updated_at        = datetime.now(timezone.utc),
            )
            if existing_ds:
                for k, v in fields.items():
                    setattr(existing_ds, k, v)
            else:
                db.add(DomainScore(review_id=review_id, domain=domain_slug, **fields))
            with db.begin_nested():
                db.flush()
            saved_scores += 1
        except Exception as exc:
            logger.error(f"[AGENT] DomainScore save failed for {domain_slug}: {exc}")
    logger.info(f"[AGENT] Domain scores saved: {saved_scores}/{len(result.get('domain_scores', {}))}")

    # ── 3. Blockers (delete-then-insert) ──────────────────────────────────────
    try:
        with db.begin_nested():
            db.query(Blocker).filter(Blocker.review_id == review_id).delete()
            db.flush()
    except Exception as exc:
        logger.error(f"[AGENT] Blockers delete failed: {exc}")

    saved_blockers = 0
    for blk in all_blockers_list:
        title = _str(blk.get("title")) or _str(blk.get("description", ""))[:120]
        if not title:
            continue
        try:
            domain_slug = blk.get("domain_slug") or blk.get("domain") or ""
            is_sec_dr = bool(blk.get("is_security_or_dr")) or domain_slug in ("security", "SEC")
            with db.begin_nested():
                db.add(Blocker(
                    review_id          = review_id,
                    blocker_id         = _str(blk.get("id")) or f"{domain_slug}-BLK-auto",
                    domain             = domain_slug,
                    title              = title,
                    description        = _str(blk.get("description")) or title,
                    violated_standard  = _str(blk.get("violated_standard")),
                    impact             = _str(blk.get("impact")),
                    resolution_required= _str(blk.get("resolution_required")),
                    links_to_finding_id= _str(blk.get("links_to_finding_id") or blk.get("finding_ref")),
                    is_security_or_dr  = is_sec_dr,
                    status             = "OPEN",
                    kb_evidence_ref    = _arr(blk.get("kb_evidence_ref")),
                ))
                db.flush()
            saved_blockers += 1
        except Exception as exc:
            logger.warning(f"[AGENT] Blocker save skipped: {exc}")
    logger.info(f"[AGENT] Blockers saved: {saved_blockers}/{len(all_blockers_list)}")

    # ── 4. Recommendations (delete-then-insert) ───────────────────────────────
    try:
        with db.begin_nested():
            db.query(Recommendation).filter(Recommendation.review_id == review_id).delete()
            db.flush()
    except Exception as exc:
        logger.error(f"[AGENT] Recommendations delete failed: {exc}")

    saved_recs = 0
    for rec in result.get("recommendations", []):
        title = _str(rec.get("title")) or _str(rec.get("recommendation", ""))[:120]
        if not title:
            continue
        try:
            domain_slug = rec.get("domain_slug") or rec.get("domain") or ""
            with db.begin_nested():
                db.add(Recommendation(
                    review_id            = review_id,
                    recommendation_id    = _str(rec.get("id")) or f"{domain_slug}-REC-auto",
                    domain               = domain_slug,
                    priority             = (_str(rec.get("priority")) or "medium").lower(),
                    title                = title,
                    rationale            = _str(rec.get("rationale")),
                    approved_pattern_ref = _str(rec.get("approved_pattern_ref")),
                    benefit              = _str(rec.get("benefit")),
                    implementation_hint  = _str(rec.get("implementation_hint")),
                    applies_to_finding_id= _str(rec.get("applies_to_finding_id") or rec.get("finding_ref")),
                    applies_to_adr_id    = _str(rec.get("applies_to_adr_id")),
                    is_agent_generated   = True,
                    kb_source_ref        = _arr(rec.get("kb_source_ref")),
                ))
                db.flush()
            saved_recs += 1
        except Exception as exc:
            logger.warning(f"[AGENT] Recommendation save skipped: {exc}")
    logger.info(f"[AGENT] Recommendations saved: {saved_recs}/{len(result.get('recommendations', []))}")

    # ── 5. NFR Scorecard (upsert on review_id + nfr_category) ────────────────
    saved_nfr = 0
    for row in result.get("nfr_scorecard", []):
        nfr_cat = (_str(row.get("nfr_category")) or "").lower()
        if not nfr_cat:
            continue
        try:
            raw_score = int(row.get("rag_score") or 3)
            rag_score = max(1, min(5, raw_score))
            rag_label = (row.get("rag_label") or ("green" if rag_score >= 4 else "amber" if rag_score == 3 else "red")).lower()
            is_mandatory    = nfr_cat in ("security", "dr")
            evidence_provided = _arr(row.get("evidence_provided")) or []
            gaps              = _arr(row.get("gaps")) or []
            with db.begin_nested():
                existing_nfr = (
                    db.query(NFRScorecard)
                    .filter(NFRScorecard.review_id == review_id, NFRScorecard.nfr_category == nfr_cat)
                    .first()
                )
                if existing_nfr:
                    existing_nfr.rag_score           = rag_score
                    existing_nfr.rag_label           = rag_label
                    existing_nfr.evidence_provided   = evidence_provided
                    existing_nfr.gaps                = gaps
                    existing_nfr.mitigating_condition= _str(row.get("mitigating_condition"))
                    existing_nfr.slo_target          = _str(row.get("slo_target"))
                    existing_nfr.actual_evidenced    = _str(row.get("actual_evidenced"))
                    existing_nfr.is_mandatory_green  = is_mandatory
                else:
                    db.add(NFRScorecard(
                        review_id          = review_id,
                        nfr_category       = nfr_cat,
                        rag_score          = rag_score,
                        rag_label          = rag_label,
                        evidence_provided  = evidence_provided,
                        gaps               = gaps,
                        mitigating_condition= _str(row.get("mitigating_condition")),
                        slo_target         = _str(row.get("slo_target")),
                        actual_evidenced   = _str(row.get("actual_evidenced")),
                        is_mandatory_green = is_mandatory,
                    ))
                db.flush()
                saved_nfr += 1
        except Exception as exc:
            logger.warning(f"[AGENT] NFR scorecard row save skipped ({nfr_cat}): {exc}")
    logger.info(f"[AGENT] NFR scorecard rows saved: {saved_nfr}/{len(result.get('nfr_scorecard', []))}")

    # ── 6. Findings (delete-then-insert) ─────────────────────────────────────
    try:
        with db.begin_nested():
            db.query(Finding).filter(Finding.review_id == review_id).delete()
            db.flush()
    except Exception as exc:
        logger.error(f"[AGENT] Findings delete failed: {exc}")

    all_findings: List[Dict[str, Any]] = list(result.get("findings", []))

    # Build recommendation text lookup from recommendations list (fallback)
    rec_by_finding_ref: Dict[str, str] = {}
    for rec in result.get("recommendations", []):
        ref  = rec.get("applies_to_finding_id") or rec.get("finding_ref") or rec.get("id")
        text = _str(rec.get("title") or rec.get("recommendation"))
        if ref and text:
            rec_by_finding_ref[ref] = text

    saved_findings = 0
    for f in all_findings:
        finding_text = _str(f.get("finding") or f.get("description"))
        if not finding_text:
            logger.warning(f"[AGENT] skipping finding with empty text — domain={f.get('domain_slug') or f.get('domain')}")
            continue
        try:
            raw_score  = f.get("rag_score", 3)
            rag_score  = max(1, min(5, int(raw_score))) if str(raw_score).isdigit() else 3
            severity   = _rag_score_to_severity(rag_score)
            finding_id = _str(f.get("id"))
            principle_id = _str(f.get("principle_id")) or finding_id or None
            recommendation = _str(f.get("recommendation")) or rec_by_finding_ref.get(finding_id or "", "")
            is_blocker = bool(f.get("is_blocker")) or (rag_score <= 1)

            with db.begin_nested():
                db.add(Finding(
                    review_id          = review_id,
                    domain             = f.get("domain_slug") or f.get("domain") or "",
                    finding_id         = finding_id,
                    principle_id       = principle_id,
                    severity           = severity,
                    title              = _str(f.get("title")),
                    finding            = finding_text,
                    rag_score          = rag_score,
                    check_category     = _str(f.get("check_category")),
                    evidence_source    = _str(f.get("evidence_source") or f.get("artifact_ref")),
                    standard_violated  = _str(f.get("standard_violated")),
                    impact             = _str(f.get("impact")),
                    recommendation     = recommendation or None,
                    is_blocker         = is_blocker,
                    is_resolved        = False,
                    links_to_action_ids= _arr(f.get("links_to_action_ids")),
                    links_to_adr_id    = _str(f.get("links_to_adr_id")),
                    waiver_eligible    = bool(f.get("waiver_eligible")),
                    kb_reference       = _arr(f.get("kb_reference")),
                    artifact_ref       = _str(f.get("artifact_ref") or f.get("evidence_source")),
                    kb_ref             = _str(f.get("kb_ref")),
                ))
                db.flush()
                saved_findings += 1
        except Exception as exc:
            logger.warning(f"[AGENT] finding save skipped: {exc} — id={f.get('id')}")
    logger.info(f"[AGENT] Findings saved: {saved_findings}/{len(all_findings)}")

    # ── 7. Actions (delete-then-insert) ──────────────────────────────────────
    try:
        with db.begin_nested():
            db.query(Action).filter(Action.review_id == review_id).delete()
            db.flush()
    except Exception as exc:
        logger.error(f"[AGENT] Actions delete failed: {exc}")

    saved_actions = 0
    for act in all_actions_list:
        action_text = _str(act.get("action") or act.get("title") or act.get("action_text"))
        if not action_text:
            continue
        try:
            raw_days = act.get("due_days")
            try:
                due_days = int(raw_days) if raw_days is not None else None
            except (TypeError, ValueError):
                due_days = None

            with db.begin_nested():
                db.add(Action(
                    review_id                  = review_id,
                    action_id                  = _str(act.get("id")),
                    domain                     = _str(act.get("domain_slug") or act.get("domain")),
                    action_type                = (_str(act.get("action_type")) or "").lower() or None,
                    title                      = _str(act.get("title")),
                    action_text                = action_text,
                    proposed_owner             = _str(act.get("proposed_owner") or act.get("owner_role")),
                    owner_role                 = _str(act.get("owner_role") or act.get("proposed_owner")) or "solution_architect",
                    proposed_due_date          = _str(act.get("proposed_due_date")),
                    due_days                   = due_days,
                    due_date                   = _due_date_from_days(due_days),
                    verification_method        = _str(act.get("verification_method")),
                    is_conditional_approval_gate = bool(act.get("is_conditional_approval_gate")),
                    links_to_finding_id        = _str(act.get("links_to_finding_id") or act.get("finding_ref")),
                    links_to_blocker_id        = _str(act.get("links_to_blocker_id")),
                    links_to_adr_id            = _str(act.get("links_to_adr_id")),
                    priority                   = _str(act.get("priority")),
                    status                     = "open",
                ))
                db.flush()
                saved_actions += 1
        except Exception as exc:
            logger.warning(f"[AGENT] action save skipped: {exc}")
    logger.info(f"[AGENT] Actions saved: {saved_actions}/{len(all_actions_list)}")

    # ── 8. ADRs (delete-then-insert) ─────────────────────────────────────────
    try:
        with db.begin_nested():
            db.query(ADR).filter(ADR.review_id == review_id).delete()
            db.flush()
    except Exception as exc:
        logger.error(f"[AGENT] ADRs delete failed: {exc}")

    saved_adrs = 0
    for i, adr in enumerate(result.get("adrs", []), start=1):
        decision_text  = _str(adr.get("decision"))
        rationale_text = _str(adr.get("rationale"))
        if not decision_text or not rationale_text:
            logger.warning(f"[AGENT] skipping ADR-{i} with empty decision/rationale")
            continue
        try:
            adr_type       = (_str(adr.get("adr_type") or adr.get("type")) or "new_decision").lower()
            waiver_expiry  = _parse_date(adr.get("waiver_expiry_date"))
            domain_slug    = _str(adr.get("domain_slug") or adr.get("domain"))

            with db.begin_nested():
                db.add(ADR(
                    review_id             = review_id,
                    adr_id                = _str(adr.get("id")) or f"ADR-{review_id[:8]}-{i:03d}",
                    domain                = domain_slug,
                    adr_type              = adr_type,
                    title                 = _str(adr.get("title") or decision_text[:160]),
                    decision              = decision_text,
                    rationale             = rationale_text,
                    context               = _str(adr.get("context")),
                    consequences          = _str(adr.get("consequences")),
                    mitigations           = _arr(adr.get("mitigations")),
                    options_considered    = adr.get("options_considered") or None,
                    owner                 = _str(adr.get("owner") or adr.get("proposed_owner")),
                    proposed_owner        = _str(adr.get("proposed_owner") or adr.get("owner")),
                    proposed_target_date  = _str(adr.get("proposed_target_date")),
                    target_date           = _parse_date(adr.get("target_date")),
                    waiver_expiry_date    = waiver_expiry,
                    links_to_finding_ids  = _arr(adr.get("links_to_finding_ids")),
                    links_to_action_ids   = _arr(adr.get("links_to_action_ids")),
                    kb_references         = _arr(adr.get("kb_references")),
                    status                = "proposed",
                ))
                db.flush()
                saved_adrs += 1
        except Exception as exc:
            logger.warning(f"[AGENT] ADR save skipped: {exc} — adr_id={adr.get('id', f'ADR-{i}')}")
    logger.info(f"[AGENT] ADRs saved: {saved_adrs}/{len(result.get('adrs', []))}")

    try:
        db.commit()
        logger.info(f"[AGENT] All results committed for review={review_id}")
    except Exception as exc:
        logger.error(f"[AGENT] Final commit failed: {exc}")
        try:
            db.rollback()
        except Exception:
            pass
