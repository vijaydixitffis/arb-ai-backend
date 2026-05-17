"""
Mock LLM populator — returns a pre-baked review result dict from the Bank EDMS
fixture file instead of calling any LLM API.

Activated when USE_MOCK_LLM=true in .env.  The result dict matches the format
that _persist_results() in agent.py expects (same keys as EnhancedARBOrchestrator
.run_review() returns).

Only domains selected in the review's scope_tags are populated — same domain
resolution logic as EnhancedARBOrchestrator._get_domains_from_scope().

Fixture file: backend/scripts/fixtures/bank_edms_mock_data.json
Generate / refresh with: cd backend && python -m scripts.export_mock_fixture
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Set

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

FIXTURE_PATH = Path(__file__).parent.parent.parent / "scripts" / "fixtures" / "bank_edms_mock_data.json"

# Some tables (actions, ADRs, recommendations) store abbreviated domain codes
# instead of full slugs.  Map both so filtering works uniformly.
_CODE_TO_SLUG: dict[str, str] = {
    "SOL": "solution",
    "BUS": "business",
    "APP": "application",
    "INT": "integration",
    "DAT": "data",
    "INF": "infrastructure",
    "DSO": "devsecops",
    "NFR": "nfr",
    "SEC": "security",
}


def _resolve_domains(scope_tags: List[str], db: Session) -> List[str]:
    """Mirror EnhancedARBOrchestrator._get_domains_from_scope()."""
    from app.db.metadata_models import Domain
    active: Set[str] = {d.slug for d in db.query(Domain).filter(Domain.is_active == True).all()}

    ordered: List[str] = []
    for tag in scope_tags:
        if tag in active and tag not in ordered:
            ordered.append(tag)
    if "solution" in active and "solution" not in ordered:
        ordered.insert(0, "solution")
    return ordered


async def load_mock_result(review_id: str, db: Session) -> dict:
    """Load the Bank EDMS fixture and return it filtered to the review's selected domains."""
    if not FIXTURE_PATH.exists():
        raise FileNotFoundError(
            f"Mock fixture not found at {FIXTURE_PATH}. "
            "Run: cd backend && python -m scripts.export_mock_fixture"
        )

    with open(FIXTURE_PATH) as fh:
        data = json.load(fh)

    # Determine which domains are selected for this review
    from app.db.review_models import Review
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise ValueError(f"Review {review_id} not found")

    selected_domains = _resolve_domains(review.scope_tags or [], db)
    selected_set = set(selected_domains)
    logger.info("[MOCK_LLM] review=%s selected_domains=%s", review_id, selected_domains)

    # Filter all domain-keyed collections to selected domains only
    all_domain_scores = data.get("domain_scores", [])
    filtered_ds = [ds for ds in all_domain_scores if ds["domain"] in selected_set]

    def _domain_slug(item: dict) -> str:
        raw = item.get("domain_slug") or item.get("domain") or ""
        return _CODE_TO_SLUG.get(raw.upper(), raw.lower())

    def _by_domain(items: list) -> list:
        return [x for x in items if _domain_slug(x) in selected_set]

    filtered_findings        = _by_domain(data.get("findings", []))
    filtered_blockers        = _by_domain(data.get("blockers", []))
    filtered_recommendations = _by_domain(data.get("recommendations", []))
    filtered_actions         = _by_domain(data.get("actions", []))
    filtered_adrs            = _by_domain(data.get("adrs", []))

    # NFR scorecard rows belong to the NFR domain — include only if nfr is in scope
    filtered_nfr = data.get("nfr_scorecard", []) if "nfr" in selected_set else []

    env = data["review_envelope"]

    # Recalculate aggregate score from filtered domain scores (min of selected)
    filtered_scores = [ds["score"] for ds in filtered_ds]
    aggregate_score = min(filtered_scores) if filtered_scores else env.get("aggregate_rag_score")
    score_to_label = lambda s: "green" if s >= 4 else "amber" if s == 3 else "red"
    aggregate_label = score_to_label(aggregate_score) if isinstance(aggregate_score, int) else env.get("aggregate_rag_label")

    domain_scores:    dict = {ds["domain"]: int(ds["score"]) for ds in filtered_ds}
    domain_summaries: dict = {ds["domain"]: ds for ds in filtered_ds}

    result = {
        "decision":               env.get("decision", "defer"),
        "aggregate_score":        aggregate_score,
        "aggregate_rag_label":    aggregate_label,
        "total_tokens_used":      env.get("tokens_used", 0),
        "processing_time_seconds": 0,
        "kb_sources_cited":       env.get("kb_sources_cited") or [],

        "ai_review": {
            "executive_rationale":  env.get("decision_rationale", ""),
            "model_used":           "mock",
            "recommended_decision": env.get("recommended_decision"),
        },

        "domain_scores":    domain_scores,
        "domain_summaries": domain_summaries,

        "findings":        filtered_findings,
        "blockers":        filtered_blockers,
        "recommendations": filtered_recommendations,
        "nfr_scorecard":   filtered_nfr,
        "actions":         filtered_actions,
        "adrs":            filtered_adrs,
    }

    logger.info(
        "[MOCK_LLM] Loaded fixture — domains=%d findings=%d blockers=%d "
        "actions=%d adrs=%d nfr=%d",
        len(domain_scores),
        len(filtered_findings),
        len(filtered_blockers),
        len(filtered_actions),
        len(filtered_adrs),
        len(filtered_nfr),
    )
    return result
