"""
Export Bank EDMS review outcome data from localhost DB into:
  1. scripts/fixtures/bank_edms_mock_data.json  — used by mock_llm_populator
  2. scripts/fixtures/bank_edms_outcome.sql      — parameterised SQL for direct DB replay

Usage:
    cd backend
    python -m scripts.export_mock_fixture [--review-id <uuid>]

Default source review: Bank EDMS (4102d0fd-e573-4928-b86a-44370de1efe4)
"""

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

# Allow imports from the backend package root
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.db.review_models import (
    Review, DomainScore, Finding, Blocker,
    Recommendation, NFRScorecard, Action, ADR,
)

BANK_EDMS_REVIEW_ID = "4102d0fd-e573-4928-b86a-44370de1efe4"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── Serialisation helpers ──────────────────────────────────────────────────────

def _to_json_safe(val):
    """Recursively convert DB values to JSON-serialisable types."""
    if val is None:
        return None
    if isinstance(val, (datetime,)):
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, list):
        return [_to_json_safe(x) for x in val]
    if isinstance(val, dict):
        return {k: _to_json_safe(v) for k, v in val.items()}
    return val


def _sql_lit(val) -> str:
    """Convert a Python value to a SQL literal string."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        return repr(val)
    if isinstance(val, datetime):
        return f"'{val.isoformat()}'::timestamptz"
    if isinstance(val, date):
        return f"'{val.isoformat()}'::date"
    if isinstance(val, list):
        if not val:
            return "ARRAY[]::text[]"
        escaped = [str(x).replace("'", "''").replace("\\", "\\\\") for x in val]
        inner = ", ".join(f"'{e}'" for e in escaped)
        return f"ARRAY[{inner}]::text[]"
    if isinstance(val, dict):
        raw = json.dumps(val, default=str).replace("'", "''")
        return f"'{raw}'::jsonb"
    # String
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"


def _ins(table: str, cols: list[str], rows: list[dict], target_id_col: str = "review_id") -> str:
    """Generate INSERT statements for a table, replacing review_id with :target_review_id."""
    if not rows:
        return f"-- {table}: no rows\n"
    lines = [f"\n-- {table} ({len(rows)} row(s))"]
    col_list = ", ".join(cols)
    for row in rows:
        vals = []
        for c in cols:
            if c == "id":
                vals.append("gen_random_uuid()")
            elif c == target_id_col:
                vals.append(":'target_review_id'::uuid")
            else:
                vals.append(_sql_lit(row.get(c)))
        val_list = ", ".join(vals)
        lines.append(f"INSERT INTO {table} ({col_list}) VALUES ({val_list});")
    return "\n".join(lines)


# ── Table extractors ───────────────────────────────────────────────────────────

def _export_review(db: Session, review_id: str) -> dict:
    r = db.query(Review).filter(Review.id == review_id).first()
    if not r:
        raise ValueError(f"Review {review_id} not found")
    return {
        "decision":            r.decision,
        "aggregate_rag_score": r.aggregate_rag_score,
        "aggregate_rag_label": r.aggregate_rag_label,
        "recommended_decision": r.recommended_decision,
        "decision_rationale":  r.decision_rationale,
        "kb_sources_cited":    _to_json_safe(r.kb_sources_cited) or [],
        "tokens_used":         r.tokens_used or 0,
        "solution_name":       r.solution_name,
    }


def _export_domain_scores(db: Session, review_id: str) -> list[dict]:
    rows = db.query(DomainScore).filter(DomainScore.review_id == review_id).all()
    return [
        {
            "domain":                r.domain,
            "score":                 r.score,
            "rag_label":             r.rag_label,
            "overall_readiness":     r.overall_readiness,
            "executive_summary":     r.executive_summary,
            "compliant_areas":       _to_json_safe(r.compliant_areas) or [],
            "gap_areas":             _to_json_safe(r.gap_areas) or [],
            "blocker_count":         r.blocker_count or 0,
            "action_count":          r.action_count or 0,
            "adr_count":             r.adr_count or 0,
            "domain_specific_scores": _to_json_safe(r.domain_specific_scores),
            "evidence_quality":      r.evidence_quality,
            "kb_references":         _to_json_safe(r.kb_references) or [],
        }
        for r in rows
    ]


def _export_findings(db: Session, review_id: str) -> list[dict]:
    rows = db.query(Finding).filter(Finding.review_id == review_id).all()
    return [
        {
            # "id" here is the finding_id code (e.g. "SOL-F01"), not the PK UUID.
            # _persist_results uses f.get("id") to populate finding_id column.
            "id":                  r.finding_id,
            "domain":              r.domain,
            "domain_slug":         r.domain,
            "principle_id":        r.principle_id,
            "severity":            r.severity,
            "finding":             r.finding,
            "recommendation":      r.recommendation,
            "check_category":      r.check_category,
            "title":               r.title,
            "rag_score":           r.rag_score,
            "evidence_source":     r.evidence_source,
            "standard_violated":   r.standard_violated,
            "impact":              r.impact,
            "is_blocker":          r.is_blocker,
            "links_to_action_ids": _to_json_safe(r.links_to_action_ids) or [],
            "links_to_adr_id":     r.links_to_adr_id,
            "waiver_eligible":     r.waiver_eligible,
            "kb_reference":        _to_json_safe(r.kb_reference) or [],
            "artifact_ref":        r.artifact_ref,
            "kb_ref":              r.kb_ref,
        }
        for r in rows
    ]


def _export_blockers(db: Session, review_id: str) -> list[dict]:
    rows = db.query(Blocker).filter(Blocker.review_id == review_id).all()
    return [
        {
            "id":                  r.blocker_id,
            "domain":              r.domain,
            "domain_slug":         r.domain,
            "title":               r.title,
            "description":         r.description,
            "violated_standard":   r.violated_standard,
            "impact":              r.impact,
            "resolution_required": r.resolution_required,
            "links_to_finding_id": r.links_to_finding_id,
            "is_security_or_dr":   r.is_security_or_dr,
            "status":              r.status,
            "kb_evidence_ref":     _to_json_safe(r.kb_evidence_ref) or [],
        }
        for r in rows
    ]


def _export_recommendations(db: Session, review_id: str) -> list[dict]:
    rows = db.query(Recommendation).filter(Recommendation.review_id == review_id).all()
    return [
        {
            "id":                   r.recommendation_id,
            "domain":               r.domain,
            "priority":             r.priority,
            "title":                r.title,
            "rationale":            r.rationale,
            "approved_pattern_ref": r.approved_pattern_ref,
            "benefit":              r.benefit,
            "implementation_hint":  r.implementation_hint,
            "applies_to_finding_id": r.applies_to_finding_id,
            "applies_to_adr_id":    r.applies_to_adr_id,
            "is_agent_generated":   r.is_agent_generated,
            "kb_source_ref":        _to_json_safe(r.kb_source_ref) or [],
        }
        for r in rows
    ]


def _export_nfr_scorecard(db: Session, review_id: str) -> list[dict]:
    rows = db.query(NFRScorecard).filter(NFRScorecard.review_id == review_id).all()
    return [
        {
            "nfr_category":       r.nfr_category,
            "rag_score":          r.rag_score,
            "rag_label":          r.rag_label,
            "evidence_provided":  _to_json_safe(r.evidence_provided) or [],
            "gaps":               _to_json_safe(r.gaps) or [],
            "mitigating_condition": r.mitigating_condition,
            "slo_target":         r.slo_target,
            "actual_evidenced":   r.actual_evidenced,
            "is_mandatory_green": r.is_mandatory_green,
        }
        for r in rows
    ]


def _export_actions(db: Session, review_id: str) -> list[dict]:
    rows = db.query(Action).filter(Action.review_id == review_id).all()
    return [
        {
            "id":                          r.action_id,
            "domain":                      r.domain,
            "action_type":                 r.action_type,
            "title":                       r.title,
            # Use "action" key so _persist_results a.get("action") resolves correctly
            "action":                      r.action_text,
            "action_text":                 r.action_text,
            "owner_role":                  r.owner_role,
            "due_days":                    r.due_days or 30,
            "proposed_owner":              r.proposed_owner,
            "proposed_due_date":           r.proposed_due_date,
            "verification_method":         r.verification_method,
            "is_conditional_approval_gate": r.is_conditional_approval_gate,
            "links_to_finding_id":         r.links_to_finding_id,
            "links_to_blocker_id":         r.links_to_blocker_id,
            "links_to_adr_id":             r.links_to_adr_id,
            "priority":                    r.priority,
        }
        for r in rows
    ]


def _export_adrs(db: Session, review_id: str) -> list[dict]:
    rows = db.query(ADR).filter(ADR.review_id == review_id).all()
    return [
        {
            "id":                  r.adr_id,
            "domain":              r.domain,
            "adr_type":            r.adr_type,
            "title":               r.title,
            "decision":            r.decision,
            "rationale":           r.rationale,
            "context":             r.context,
            "owner":               r.owner,
            "proposed_owner":      r.proposed_owner,
            "target_date":         _to_json_safe(r.target_date),
            "proposed_target_date": r.proposed_target_date,
            "waiver_expiry_date":  _to_json_safe(r.waiver_expiry_date),
            "status":              r.status,
            "options_considered":  _to_json_safe(r.options_considered),
            "mitigations":         _to_json_safe(r.mitigations) or [],
            "links_to_finding_ids": _to_json_safe(r.links_to_finding_ids) or [],
            "links_to_action_ids": _to_json_safe(r.links_to_action_ids) or [],
            "kb_references":       _to_json_safe(r.kb_references) or [],
        }
        for r in rows
    ]


# ── SQL generation ─────────────────────────────────────────────────────────────

def _build_sql(review_id: str, data: dict) -> str:
    env = data["review_envelope"]
    lines = [
        "-- Bank EDMS review outcome fixture",
        f"-- Source review: {review_id}",
        "--",
        "-- Usage (psql):",
        "--   psql -U vijaykumardixit arb_ai_agent \\",
        "--     -v target_review_id='<target-uuid>' \\",
        "--     -f bank_edms_outcome.sql",
        "--",
        "-- The script inserts data from this fixture into the target review.",
        "-- The target review must already exist in the reviews table.",
        "",
        "BEGIN;",
        "",
        "-- Update review envelope",
        "UPDATE reviews SET",
        f"  decision             = {_sql_lit(env['decision'])},",
        f"  recommended_decision = {_sql_lit(env['recommended_decision'])},",
        f"  aggregate_rag_score  = {_sql_lit(env['aggregate_rag_score'])},",
        f"  aggregate_rag_label  = {_sql_lit(env['aggregate_rag_label'])},",
        f"  decision_rationale   = {_sql_lit(env['decision_rationale'])},",
        f"  kb_sources_cited     = {_sql_lit(env['kb_sources_cited'])},",
        f"  tokens_used          = {_sql_lit(env['tokens_used'])},",
        "  status               = 'review_ready',",
        "  reviewed_at          = now(),",
        "  agent_run_at         = now()",
        "WHERE id = :'target_review_id'::uuid;",
    ]

    # domain_scores
    ds_cols = [
        "id", "review_id", "domain", "score", "rag_label", "overall_readiness",
        "executive_summary", "compliant_areas", "gap_areas",
        "blocker_count", "action_count", "adr_count",
        "domain_specific_scores", "evidence_quality", "kb_references",
        "created_at", "updated_at",
    ]
    ds_rows = []
    for r in data["domain_scores"]:
        ds_rows.append({**r, "created_at": "NOW()", "updated_at": "NOW()"})
    lines.append(_ins("domain_scores", ds_cols, ds_rows))

    # findings
    f_cols = [
        "id", "review_id", "domain", "finding_id", "principle_id",
        "severity", "finding", "recommendation", "check_category",
        "title", "rag_score", "evidence_source", "standard_violated", "impact",
        "is_blocker", "is_resolved", "links_to_action_ids", "links_to_adr_id",
        "waiver_eligible", "kb_reference", "artifact_ref", "kb_ref", "created_at",
    ]
    f_rows = []
    for r in data["findings"]:
        f_rows.append({
            **r,
            "finding_id": r["id"],   # DB column is finding_id, fixture key is "id"
            "is_resolved": False,
            "created_at": "NOW()",
        })
    lines.append(_ins("findings", f_cols, f_rows))

    # blockers
    b_cols = [
        "id", "review_id", "blocker_id", "domain", "title", "description",
        "violated_standard", "impact", "resolution_required",
        "links_to_finding_id", "is_security_or_dr", "status", "kb_evidence_ref",
        "created_at",
    ]
    b_rows = [{"blocker_id": r["id"], **r, "created_at": "NOW()"} for r in data["blockers"]]
    lines.append(_ins("blockers", b_cols, b_rows))

    # recommendations
    rec_cols = [
        "id", "review_id", "recommendation_id", "domain", "priority", "title",
        "rationale", "approved_pattern_ref", "benefit", "implementation_hint",
        "applies_to_finding_id", "applies_to_adr_id", "is_agent_generated",
        "kb_source_ref", "created_at",
    ]
    rec_rows = [{"recommendation_id": r["id"], **r, "created_at": "NOW()"} for r in data["recommendations"]]
    lines.append(_ins("recommendations", rec_cols, rec_rows))

    # nfr_scorecard
    nfr_cols = [
        "id", "review_id", "nfr_category", "rag_score", "rag_label",
        "evidence_provided", "gaps", "mitigating_condition", "slo_target",
        "actual_evidenced", "is_mandatory_green", "created_at",
    ]
    nfr_rows = [{**r, "created_at": "NOW()"} for r in data["nfr_scorecard"]]
    lines.append(_ins("nfr_scorecard", nfr_cols, nfr_rows))

    # actions
    act_cols = [
        "id", "review_id", "action_id", "domain", "action_type", "title",
        "action_text", "status", "owner_role", "due_days",
        "proposed_owner", "proposed_due_date", "verification_method",
        "is_conditional_approval_gate", "links_to_finding_id",
        "links_to_blocker_id", "links_to_adr_id", "priority", "created_at",
    ]
    act_rows = [{
        "action_id": r["id"], **r,
        "action_text": r.get("action") or r.get("action_text"),
        "status": "open",
        "created_at": "NOW()",
    } for r in data["actions"]]
    lines.append(_ins("actions", act_cols, act_rows))

    # adrs
    adr_cols = [
        "id", "review_id", "adr_id", "domain", "adr_type", "title",
        "decision", "rationale", "context", "owner", "proposed_owner",
        "target_date", "proposed_target_date", "waiver_expiry_date",
        "status", "options_considered", "mitigations",
        "links_to_finding_ids", "links_to_action_ids", "kb_references",
        "created_at", "updated_at",
    ]
    adr_rows = [{
        "adr_id": r["id"], **r,
        "created_at": "NOW()", "updated_at": "NOW()",
    } for r in data["adrs"]]
    lines.append(_ins("adrs", adr_cols, adr_rows))

    lines.append("\nCOMMIT;")
    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def export(review_id: str) -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    db: Session = SessionLocal()
    try:
        print(f"Exporting review {review_id} …")
        data = {
            "source_review_id": review_id,
            "exported_at":      datetime.utcnow().isoformat(),
            "review_envelope":  _export_review(db, review_id),
            "domain_scores":    _export_domain_scores(db, review_id),
            "findings":         _export_findings(db, review_id),
            "blockers":         _export_blockers(db, review_id),
            "recommendations":  _export_recommendations(db, review_id),
            "nfr_scorecard":    _export_nfr_scorecard(db, review_id),
            "actions":          _export_actions(db, review_id),
            "adrs":             _export_adrs(db, review_id),
        }
    finally:
        db.close()

    # Write JSON fixture
    json_path = FIXTURES_DIR / "bank_edms_mock_data.json"
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"✓ JSON fixture: {json_path}")
    print(f"  domain_scores={len(data['domain_scores'])}  findings={len(data['findings'])}"
          f"  blockers={len(data['blockers'])}  recommendations={len(data['recommendations'])}"
          f"  actions={len(data['actions'])}  adrs={len(data['adrs'])}"
          f"  nfr_scorecard={len(data['nfr_scorecard'])}")

    # Write SQL fixture
    sql_path = FIXTURES_DIR / "bank_edms_outcome.sql"
    with open(sql_path, "w") as f:
        f.write(_build_sql(review_id, data))
    print(f"✓ SQL fixture:  {sql_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export Bank EDMS review outcome to fixture files.")
    parser.add_argument("--review-id", default=BANK_EDMS_REVIEW_ID,
                        help=f"Source review UUID (default: {BANK_EDMS_REVIEW_ID})")
    args = parser.parse_args()
    export(args.review_id)
