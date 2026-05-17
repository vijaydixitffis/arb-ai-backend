from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import StreamingResponse
from typing import List, Optional, Dict, Any
import logging
import asyncio
from app.core.database import get_db
from app.core.security import decode_access_token
from app.services.review_service import ReviewService
from app.utils.schema_validation import validate_review_data_structure, validate_submission_completeness, get_validation_summary
from sqlalchemy.orm import Session
import io

logger = logging.getLogger(__name__)

router = APIRouter()

async def get_current_user(authorization: Optional[str] = Header(None)) -> tuple[Optional[str], Optional[str]]:
    """Extract user ID and role from JWT token"""
    if not authorization:
        return None, None
    if not authorization.startswith("Bearer "):
        return None, None
    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        return None, None
    return payload.get("sub"), payload.get("role")

@router.get("")
async def get_reviews(user_id: str = None, current_user: tuple = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get ARB reviews - all authenticated users can read"""
    user_id_token, user_role = current_user
    if not user_id_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    service = ReviewService(db)
    reviews = service.get_all_reviews()
    
    # SA, EA, ARB Admin can read all reviews
    # Filter by user if user_id is provided (for getUserReviews)
    if user_id:
        reviews = [r for r in reviews if str(r.sa_user_id) == user_id]
    
    # Convert to dict format for JSON response
    return [
        {
            "id": str(review.id),
            "created_at": review.created_at.isoformat() if review.created_at else None,
            "submitted_at": review.submitted_at.isoformat() if review.submitted_at else None,
            "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
            "sa_user_id": str(review.sa_user_id) if review.sa_user_id else None,
            "solution_name": review.solution_name,
            "scope_tags": review.scope_tags,
            "status": review.status,
            "decision": review.decision,
            "llm_model": review.llm_model,
            "tokens_used": review.tokens_used,
            "processing_time_ms": review.processing_time_ms,
            "llm_raw_response": review.llm_raw_response,
            "ea_user_id": str(review.ea_user_id) if review.ea_user_id else None,
            "ea_override_notes": review.ea_override_notes,
            "ea_overridden_at": review.ea_overridden_at.isoformat() if review.ea_overridden_at else None,
            "report_json": review.report_json
        }
        for review in reviews
    ]

@router.get("/{review_id}")
async def get_review(review_id: str, current_user: tuple = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get a specific ARB review with full domain breakdown for EA dossier view."""
    user_id_token, user_role = current_user
    if not user_id_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    service = ReviewService(db)
    review = service.get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    from app.db.review_models import DomainScore, Finding, ADR, Action
    from sqlalchemy import text

    from app.db.review_models import (
        DomainScore, Finding, ADR, Action, Blocker, Recommendation, NFRScorecard, EAReviewRecord
    )

    domain_scores  = db.query(DomainScore).filter(DomainScore.review_id == review.id).all()
    findings_db    = db.query(Finding).filter(Finding.review_id == review.id).all()
    adrs_db        = db.query(ADR).filter(ADR.review_id == review.id).all()
    actions_db     = db.query(Action).filter(Action.review_id == review.id).all()
    blockers_db    = db.query(Blocker).filter(Blocker.review_id == review.id).all()
    recs_db        = db.query(Recommendation).filter(Recommendation.review_id == review.id).all()
    nfr_db         = db.query(NFRScorecard).filter(NFRScorecard.review_id == review.id).all()
    ea_record      = db.query(EAReviewRecord).filter(EAReviewRecord.review_id == review.id).first()

    ai_review = (review.report_json or {}).get("ai_review", {})

    # -- Convert DB findings to frontend format --------------------------------
    def _finding_dict(f: Finding) -> dict:
        rag = f.rag_score or (1 if f.severity == "critical" else 2 if f.severity == "major" else 3)
        return {
            "id":               str(f.id),
            "finding_id":       f.finding_id,
            "domain_slug":      f.domain,
            "domain":           f.domain,
            "principle_id":     f.principle_id,
            "severity":         f.severity,
            "title":            f.title,
            "finding":          f.finding,
            "description":      f.description if hasattr(f, 'description') else f.finding,
            "recommendation":   f.recommendation,
            "check_category":   f.check_category,
            "rag_score":        rag,
            "evidence_source":  f.evidence_source,
            "standard_violated":f.standard_violated,
            "impact":           f.impact,
            "is_blocker":       f.is_blocker,
            "waiver_eligible":  f.waiver_eligible,
            "links_to_action_ids": f.links_to_action_ids,
            "links_to_adr_id":  f.links_to_adr_id,
            "kb_reference":     f.kb_reference,
            "artifact_ref":     f.artifact_ref,
            "kb_ref":           f.kb_ref,
            "is_resolved":      f.is_resolved,
        }

    findings_list = [_finding_dict(f) for f in findings_db]
    if not findings_list:
        findings_list = ai_review.get("findings", []) + ai_review.get("blockers", [])

    # -- Group findings, actions, ADRs, recs by domain slug -------------------
    def _group(items, slug_key="domain_slug"):
        grouped: dict = {}
        for item in items:
            slug = (item.get(slug_key) or item.get("domain") or "")
            if slug:
                grouped.setdefault(slug, []).append(item)
        return grouped

    findings_by_domain = _group(findings_list)
    actions_by_domain  = _group([
        {"domain_slug": ac.domain or "", "id": str(ac.id),
         "action_id": ac.action_id, "action_text": ac.action_text,
         "title": ac.title, "action_type": ac.action_type,
         "owner_role": ac.owner_role, "proposed_owner": ac.proposed_owner,
         "priority": ac.priority, "due_days": ac.due_days,
         "due_date": ac.due_date.isoformat() if ac.due_date else None,
         "proposed_due_date": ac.proposed_due_date,
         "verification_method": ac.verification_method,
         "is_conditional_approval_gate": ac.is_conditional_approval_gate,
         "links_to_finding_id": ac.links_to_finding_id,
         "links_to_blocker_id": ac.links_to_blocker_id,
         "links_to_adr_id": ac.links_to_adr_id,
         "status": ac.status}
        for ac in actions_db
    ])
    adrs_by_domain = _group([
        {"domain_slug": a.domain or "", "id": str(a.id),
         "adr_id": a.adr_id, "adr_type": a.adr_type,
         "title": a.title or a.decision,
         "decision": a.decision, "rationale": a.rationale,
         "context": a.context, "consequences": a.consequences,
         "mitigations": a.mitigations, "options_considered": a.options_considered,
         "owner": a.owner, "status": a.status,
         "waiver_expiry_date": a.waiver_expiry_date.isoformat() if a.waiver_expiry_date else None,
         "target_date": a.target_date.isoformat() if a.target_date else None,
         "links_to_finding_ids": a.links_to_finding_ids,
         "links_to_action_ids": a.links_to_action_ids,
         "kb_references": a.kb_references}
        for a in adrs_db
    ])
    recs_by_domain = _group([
        {"domain_slug": r.domain, "id": str(r.id),
         "recommendation_id": r.recommendation_id,
         "priority": r.priority, "title": r.title,
         "rationale": r.rationale, "approved_pattern_ref": r.approved_pattern_ref,
         "benefit": r.benefit, "implementation_hint": r.implementation_hint,
         "applies_to_finding_id": r.applies_to_finding_id,
         "applies_to_adr_id": r.applies_to_adr_id,
         "recommendation": r.title,  # compat alias
         "is_agent_generated": r.is_agent_generated,
         "kb_source_ref": r.kb_source_ref}
        for r in recs_db
    ])

    # -- Build per-domain summary dict from DB --------------------------------
    def _rag_label(score: int) -> str:
        if score >= 4: return "GREEN"
        if score == 3: return "AMBER"
        return "RED"

    domain_slugs = list({ds.domain for ds in domain_scores})
    if not domain_slugs:
        domain_slugs = list(ai_review.get("domain_scores", {}).keys())

    domain_summaries: dict = {}
    ai_domain_summaries = ai_review.get("domain_summaries", {})

    for slug in domain_slugs:
        ds = next((d for d in domain_scores if d.domain == slug), None)
        score = ds.score if ds else ai_review.get("domain_scores", {}).get(slug, 3)
        f_list   = findings_by_domain.get(slug, [])
        a_list   = actions_by_domain.get(slug, [])
        r_list   = adrs_by_domain.get(slug, [])
        rec_list = recs_by_domain.get(slug, [])
        ai_sum   = ai_domain_summaries.get(slug, {})

        domain_summaries[slug] = {
            "score":                int(score),
            "rag_label":            _rag_label(int(score)),
            "overall_readiness":    ds.overall_readiness if ds else ai_sum.get("overall_readiness"),
            "executive_summary":    ds.executive_summary if ds else ai_sum.get("executive_summary"),
            "compliant_areas":      ds.compliant_areas if ds else ai_sum.get("compliant_areas", []),
            "gap_areas":            ds.gap_areas if ds else ai_sum.get("gap_areas", []),
            "evidence_quality":     ds.evidence_quality if ds else ai_sum.get("evidence_quality"),
            "domain_specific_scores": ds.domain_specific_scores if ds else ai_sum.get("domain_specific_scores"),
            "kb_references":        ds.kb_references if ds else ai_sum.get("kb_references", []),
            "model_used":           ds.model_used if ds else None,
            "total_findings":       len(f_list),
            "blocker_count":        ds.blocker_count if ds else sum(1 for f in f_list if f.get("is_blocker")),
            "critical_count":       sum(1 for f in f_list if (f.get("rag_score") or 5) <= 2),
            "action_count":         ds.action_count if ds else len(a_list),
            "adr_count":            ds.adr_count if ds else len(r_list),
            "findings":             sorted(f_list, key=lambda x: x.get("rag_score", 3)),
            "actions":              a_list,
            "adrs":                 r_list,
            "recommendations":      rec_list,
        }

    # -- NFR scorecard from DB ------------------------------------------------
    nfr_scorecard_list = [
        {
            "nfr_category":      r.nfr_category,
            "rag_score":         r.rag_score,
            "rag_label":         r.rag_label,
            "evidence_provided": r.evidence_provided or [],
            "gaps":              r.gaps or [],
            "mitigating_condition": r.mitigating_condition,
            "slo_target":        r.slo_target,
            "actual_evidenced":  r.actual_evidenced,
            "is_mandatory_green":r.is_mandatory_green,
        }
        for r in sorted(nfr_db, key=lambda x: x.rag_score)
    ]
    if not nfr_scorecard_list:
        nfr_scorecard_list = ai_review.get("nfr_scorecard", [])

    nfr_analysis = ai_review.get("nfr_analysis", {})

    # -- EA Review structured record ------------------------------------------
    ea_review_data = None
    if ea_record:
        ea_review_data = {
            "id":              str(ea_record.id),
            "ea_name":         ea_record.ea_name,
            "reviewed_at":     ea_record.reviewed_at.isoformat() if ea_record.reviewed_at else None,
            "ea_decision":     ea_record.ea_decision,
            "overrides":       ea_record.overrides or [],
            "ea_annotations":  ea_record.ea_annotations,
            "rework_gaps":     ea_record.rework_gaps or [],
            "return_domains":  ea_record.return_domains or [],
            "final_decision":  ea_record.final_decision,
        }

    # -- Blockers list --------------------------------------------------------
    blockers_list = [
        {
            "id":                 str(b.id),
            "blocker_id":         b.blocker_id,
            "domain":             b.domain,
            "title":              b.title,
            "description":        b.description,
            "violated_standard":  b.violated_standard,
            "impact":             b.impact,
            "resolution_required":b.resolution_required,
            "links_to_finding_id":b.links_to_finding_id,
            "is_security_or_dr":  b.is_security_or_dr,
            "status":             b.status,
            "kb_evidence_ref":    b.kb_evidence_ref or [],
        }
        for b in blockers_db
    ]
    if not blockers_list:
        blockers_list = ai_review.get("blockers", [])

    return {
        "id":                    str(review.id),
        "created_at":            review.created_at.isoformat()         if review.created_at else None,
        "submitted_at":          review.submitted_at.isoformat()        if review.submitted_at else None,
        "reviewed_at":           review.reviewed_at.isoformat()         if review.reviewed_at else None,
        "agent_run_at":          review.agent_run_at.isoformat()        if review.agent_run_at else None,
        "sa_user_id":            str(review.sa_user_id)                 if review.sa_user_id else None,
        "solution_name":         review.solution_name,
        "scope_tags":            review.scope_tags,
        "arb_ref":               review.arb_ref,
        "review_version":        review.review_version,
        "classification":        review.classification,
        "status":                review.status,
        "decision":              review.decision,
        # AI agent recommendation fields
        "recommended_decision":  review.recommended_decision or ai_review.get("decision"),
        "aggregate_rag_score":   review.aggregate_rag_score  or ai_review.get("aggregate_score"),
        "aggregate_rag_label":   review.aggregate_rag_label  or ai_review.get("aggregate_rag_label"),
        "decision_rationale":    review.decision_rationale   or ai_review.get("decision_rationale"),
        "kb_sources_cited":      review.kb_sources_cited     or ai_review.get("kb_sources_cited", []),
        # Metadata
        "llm_model":             review.llm_model,
        "tokens_used":           review.tokens_used,
        "processing_time_ms":    review.processing_time_ms,
        "ea_user_id":            str(review.ea_user_id)                 if review.ea_user_id else None,
        "ea_override_notes":     review.ea_override_notes,
        "ea_overridden_at":      review.ea_overridden_at.isoformat()    if review.ea_overridden_at else None,
        "report_json":           review.report_json,
        # Structured dossier data
        "domain_summaries":      domain_summaries,
        "domain_scores":         [{"domain": ds.domain, "score": ds.score} for ds in domain_scores],
        "blockers":              blockers_list,
        "nfr_scorecard":         nfr_scorecard_list,
        "nfr_analysis":          nfr_analysis,
        "ea_review":             ea_review_data,
        # Full lists
        "adrs": [
            {
                "id":                   str(a.id),
                "adr_id":               a.adr_id,
                "domain":               a.domain,
                "adr_type":             a.adr_type,
                "title":                a.title or a.decision,
                "decision":             a.decision,
                "rationale":            a.rationale,
                "context":              a.context,
                "consequences":         a.consequences,
                "mitigations":          a.mitigations,
                "options_considered":   a.options_considered,
                "owner":                a.owner,
                "status":               a.status,
                "waiver_expiry_date":   a.waiver_expiry_date.isoformat() if a.waiver_expiry_date else None,
                "target_date":          a.target_date.isoformat()        if a.target_date else None,
                "links_to_finding_ids": a.links_to_finding_ids,
                "links_to_action_ids":  a.links_to_action_ids,
                "kb_references":        a.kb_references,
                "created_at":           a.created_at.isoformat()         if a.created_at else None,
            }
            for a in adrs_db
        ],
        "actions": [
            {
                "id":                          str(ac.id),
                "action_id":                   ac.action_id,
                "domain":                      ac.domain,
                "action_type":                 ac.action_type,
                "title":                       ac.title,
                "action_text":                 ac.action_text,
                "owner_role":                  ac.owner_role,
                "proposed_owner":              ac.proposed_owner,
                "priority":                    ac.priority,
                "proposed_due_date":           ac.proposed_due_date,
                "due_days":                    ac.due_days,
                "due_date":                    ac.due_date.isoformat()     if ac.due_date else None,
                "verification_method":         ac.verification_method,
                "is_conditional_approval_gate":ac.is_conditional_approval_gate,
                "links_to_finding_id":         ac.links_to_finding_id,
                "links_to_blocker_id":         ac.links_to_blocker_id,
                "links_to_adr_id":             ac.links_to_adr_id,
                "status":                      ac.status,
                "closure_evidence":            ac.closure_evidence,
                "created_at":                  ac.created_at.isoformat()   if ac.created_at else None,
            }
            for ac in actions_db
        ],
    }

@router.post("")
async def create_review(review_data: dict, current_user: tuple = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a new ARB review with enhanced validation"""
    user_id_token, _ = current_user
    if not user_id_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Enhanced validation - use draft mode for initial creation
    is_draft = review_data.get('status') in ('drafting', 'draft')
    
    # Check form_data in report_json (where frontend sends it) or at root level
    form_data = None
    if 'report_json' in review_data and isinstance(review_data['report_json'], dict):
        form_data = review_data['report_json'].get('form_data')
    elif 'form_data' in review_data:
        form_data = review_data['form_data']
    
    # If form_data exists, ensure it includes all project fields that might be sent at top level
    if form_data:
        project_fields = ['problem_statement', 'stakeholders', 'business_drivers', 'target_business_outcomes', 'ptx_gate', 'architecture_disposition']
        for field in project_fields:
            if field not in form_data and field in review_data:
                form_data[field] = review_data[field]
    
    if form_data:
        form_validation = validate_submission_completeness(form_data, is_draft=is_draft)
        if not form_validation.is_valid:
            raise HTTPException(
                status_code=400, 
                detail={
                    "error": "Form data validation failed",
                    "validation_errors": form_validation.errors,
                    "validation_warnings": form_validation.warnings,
                    "summary": get_validation_summary(form_validation)
                }
            )
        
        # Log warnings for monitoring
        if form_validation.warnings:
            logger.warning(f"Review creation form validation warnings: {form_validation.warnings}")
    
    # Basic review structure validation
    validation = validate_review_data_structure(review_data)
    if not validation.is_valid:
        raise HTTPException(
            status_code=400, 
            detail={
                "error": "Review structure validation failed",
                "validation_errors": validation.errors,
                "validation_warnings": validation.warnings,
                "summary": get_validation_summary(validation)
            }
        )
    
    # Log warnings for monitoring
    if validation.warnings:
        logger.warning(f"Review creation warnings: {validation.warnings}")
    
    service = ReviewService(db)
    review = service.create_review(review_data)
    
    return {
        "id": str(review.id),
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "submitted_at": review.submitted_at.isoformat() if review.submitted_at else None,
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
        "sa_user_id": str(review.sa_user_id) if review.sa_user_id else None,
        "solution_name": review.solution_name,
        "scope_tags": review.scope_tags,
        "status": review.status,
        "decision": review.decision,
        "llm_model": review.llm_model,
        "tokens_used": review.tokens_used,
        "processing_time_ms": review.processing_time_ms,
        "llm_raw_response": review.llm_raw_response,
        "ea_user_id": str(review.ea_user_id) if review.ea_user_id else None,
        "ea_override_notes": review.ea_override_notes,
        "ea_overridden_at": review.ea_overridden_at.isoformat() if review.ea_overridden_at else None,
        "report_json": review.report_json,
        "validation_warnings": validation.warnings  # Return warnings for frontend awareness
    }

@router.put("/{review_id}")
async def update_review(review_id: str, review_data: dict, current_user: tuple = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update an existing ARB review with enhanced validation - EA, ARB Admin, and Solution Architect (for their own drafts)"""
    user_id_token, user_role = current_user
    if not user_id_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Instantiate service early — needed for status lookup below
    service = ReviewService(db)

    # Extract form_data from report_json wrapper or root level
    form_data = None
    if 'report_json' in review_data and isinstance(review_data['report_json'], dict):
        form_data = review_data['report_json'].get('form_data')
    elif 'form_data' in review_data:
        form_data = review_data['form_data']

    form_validation = None
    if form_data:
        is_draft = True
        if 'status' in review_data:
            is_draft = review_data['status'] in ('drafting', 'draft')
        else:
            existing_review = service.get_review(review_id)
            if existing_review:
                is_draft = existing_review.status in ('drafting', 'draft')

        # Fetch artefacts for this review and group by domain
        from app.services.artefact_service import ArtefactService
        artefact_service = ArtefactService(db)
        artefacts_list = await artefact_service.get_artefacts_by_review(review_id)
        
        # Group artefacts by domain slug for validation
        artefacts_by_domain: Dict[str, List[Any]] = {}
        for artefact in artefacts_list:
            domain = artefact.get('domain_slug', 'solution')
            if domain not in artefacts_by_domain:
                artefacts_by_domain[domain] = []
            artefacts_by_domain[domain].append(artefact)

        # Augment form_data with top-level fields that the frontend sends separately
        if 'scope_tags' not in form_data and 'scope_tags' in review_data:
            form_data['scope_tags'] = review_data['scope_tags']
        if 'solution_name' not in form_data:
            if 'solution_name' in review_data:
                form_data['solution_name'] = review_data['solution_name']
            elif form_data.get('project_name'):
                form_data['solution_name'] = form_data['project_name']
        
        # Copy project information fields that might be sent at top level
        project_fields = ['problem_statement', 'stakeholders', 'business_drivers', 'target_business_outcomes', 'ptx_gate', 'architecture_disposition']
        for field in project_fields:
            if field not in form_data and field in review_data:
                form_data[field] = review_data[field]

        form_validation = validate_submission_completeness(form_data, artefacts=artefacts_by_domain, is_draft=is_draft)
        if not form_validation.is_valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Form data validation failed",
                    "validation_errors": form_validation.errors,
                    "validation_warnings": form_validation.warnings,
                    "summary": get_validation_summary(form_validation)
                }
            )
        if form_validation.warnings:
            logger.warning(f"Review update form validation warnings: {form_validation.warnings}")

    # Role-based update authorisation
    if user_role in ['enterprise_architect', 'arb_admin', 'super_admin']:
        review = service.update_review(review_id, review_data)
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")
    elif user_role == 'solution_architect':
        review = service.get_review(review_id)
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")
        if str(review.sa_user_id) != user_id_token:
            raise HTTPException(status_code=403, detail="You can only update your own reviews")
        if review.status not in ['drafting', 'queued', 'draft', 'pending', 'submitted', 'review_ready', 'returned']:
            raise HTTPException(status_code=403, detail="You can only update draft, queued, or reviewed reviews")
        review = service.update_review(review_id, review_data)
    else:
        raise HTTPException(status_code=403, detail="Only EA, ARB Admin, and Solution Architect can update reviews")

    return {
        "id": str(review.id),
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "submitted_at": review.submitted_at.isoformat() if review.submitted_at else None,
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
        "sa_user_id": str(review.sa_user_id) if review.sa_user_id else None,
        "solution_name": review.solution_name,
        "scope_tags": review.scope_tags,
        "status": review.status,
        "decision": review.decision,
        "llm_model": review.llm_model,
        "tokens_used": review.tokens_used,
        "processing_time_ms": review.processing_time_ms,
        "llm_raw_response": review.llm_raw_response,
        "ea_user_id": str(review.ea_user_id) if review.ea_user_id else None,
        "ea_override_notes": review.ea_override_notes,
        "ea_overridden_at": review.ea_overridden_at.isoformat() if review.ea_overridden_at else None,
        "report_json": review.report_json,
        "validation_warnings": form_validation.warnings if form_validation else []
    }

@router.post("/{review_id}/approve")
async def approve_review(review_id: str, override_rationale: str = None, current_user: tuple = Depends(get_current_user), db: Session = Depends(get_db)):
    """Approve a review (EA approval) - EA and ARB Admin only"""
    user_id_token, user_role = current_user
    if not user_id_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user_role not in ['enterprise_architect', 'arb_admin', 'super_admin']:
        raise HTTPException(status_code=403, detail="Only EA and ARB Admin can approve reviews")
    service = ReviewService(db)
    review = service.approve_review(review_id, override_rationale)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return {"message": "Review approved successfully", "review_id": review_id}


@router.post("/{review_id}/override")
async def override_review(review_id: str, decision: str, rationale: str, current_user: tuple = Depends(get_current_user), db: Session = Depends(get_db)):
    """Override agent recommendation (EA override) - EA and ARB Admin only"""
    user_id_token, user_role = current_user
    if not user_id_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user_role not in ['enterprise_architect', 'arb_admin', 'super_admin']:
        raise HTTPException(status_code=403, detail="Only EA and ARB Admin can override reviews")
    service = ReviewService(db)
    review = service.override_review(review_id, decision, rationale)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return {"message": "Review overridden successfully", "review_id": review_id}


@router.post("/{review_id}/open")
async def open_review_for_ea(
    review_id: str,
    current_user: tuple = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Gate 2 open: transition review_ready → ea_reviewing when EA opens the dossier."""
    from datetime import datetime, timezone
    from app.db.review_models import Review

    user_id_token, user_role = current_user
    if not user_id_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user_role not in ['enterprise_architect', 'arb_admin', 'super_admin']:
        raise HTTPException(status_code=403, detail="Only EA and ARB Admin can open reviews")

    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.status != 'review_ready':
        raise HTTPException(status_code=409, detail=f"Review must be in review_ready state, current: {review.status}")

    review.status    = 'ea_reviewing'
    review.ea_user_id= user_id_token if hasattr(review, 'ea_user_id') else None

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to open review: {exc}")

    return {"message": "Review opened for EA review", "review_id": review_id, "status": "ea_reviewing"}


@router.post("/{review_id}/ea-decision")
async def submit_ea_decision(
    review_id: str,
    body: dict,
    current_user: tuple = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit Gate 2 EA decision: APPROVE | CONDITIONALLY_APPROVE | RETURN | DEFER."""
    from datetime import datetime, timezone
    from app.db.review_models import Review, EAReviewRecord, DomainReview

    user_id_token, user_role = current_user
    if not user_id_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user_role not in ['enterprise_architect', 'arb_admin', 'super_admin']:
        raise HTTPException(status_code=403, detail="Only EA and ARB Admin can submit EA decisions")

    ea_decision    = body.get("ea_decision")
    ea_annotations = body.get("ea_annotations", "")
    rework_gaps    = body.get("rework_gaps", [])
    overrides      = body.get("overrides", [])
    ea_name        = body.get("ea_name", "")
    decision_rationale = body.get("decision_rationale", "")
    return_domains = body.get("return_domains", [])  # domains to reset on RETURN

    valid_ea_decisions = {"APPROVE", "CONDITIONALLY_APPROVE", "RETURN", "DEFER"}
    if ea_decision not in valid_ea_decisions:
        raise HTTPException(status_code=400, detail=f"ea_decision must be one of {valid_ea_decisions}")

    if ea_decision == "DEFER" and len(decision_rationale.strip()) < 50:
        raise HTTPException(status_code=400, detail="DEFER requires a rationale of at least 50 characters")

    if ea_decision == "RETURN" and not return_domains:
        raise HTTPException(status_code=400, detail="RETURN requires at least one domain to be flagged")
    if ea_decision == "RETURN" and not rework_gaps:
        raise HTTPException(status_code=400, detail="RETURN requires at least one rework gap")

    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.status not in ('ea_reviewing', 'ea_review'):
        raise HTTPException(status_code=409, detail=f"Review must be in ea_reviewing state, current: {review.status}")

    now = datetime.now(timezone.utc)

    # Upsert ea_review record
    ea_record = db.query(EAReviewRecord).filter(EAReviewRecord.review_id == review_id).first()
    if ea_record:
        ea_record.ea_name       = ea_name
        ea_record.reviewed_at   = now
        ea_record.ea_decision   = ea_decision
        ea_record.overrides     = overrides
        ea_record.ea_annotations= ea_annotations
        ea_record.rework_gaps   = rework_gaps
        ea_record.return_domains= return_domains if ea_decision == "RETURN" else []
        ea_record.final_decision= ea_decision
        ea_record.updated_at    = now
    else:
        ea_record = EAReviewRecord(
            review_id      = review_id,
            ea_name        = ea_name,
            reviewed_at    = now,
            ea_decision    = ea_decision,
            overrides      = overrides,
            ea_annotations = ea_annotations,
            rework_gaps    = rework_gaps,
            return_domains = return_domains if ea_decision == "RETURN" else [],
            final_decision = ea_decision,
        )
        db.add(ea_record)

    # Update review status based on decision
    if ea_decision == "APPROVE":
        review.status   = "approved"
        review.decision = "approve"
    elif ea_decision == "CONDITIONALLY_APPROVE":
        review.status   = "conditionally_approved"
        review.decision = "approve_with_conditions"
    elif ea_decision == "RETURN":
        review.status       = "returned"
        review.return_count = (review.return_count or 0) + 1
        review.rework_gaps  = rework_gaps
        # Reset domain_reviews rows for affected domains so agent can re-run them
        affected_domains = return_domains or (review.scope_tags or [])
        if affected_domains:
            db.query(DomainReview).filter(
                DomainReview.review_id == review_id,
                DomainReview.domain.in_(affected_domains)
            ).update(
                {"agent_status": "waiting", "started_at": None, "completed_at": None, "error_message": None},
                synchronize_session=False
            )
    elif ea_decision == "DEFER":
        review.status            = "deferred"
        review.decision          = "defer"
        review.decision_rationale= decision_rationale

    review.ea_user_id        = user_id_token if hasattr(review, 'ea_user_id') else None
    review.ea_override_notes = ea_annotations
    review.ea_overridden_at  = now
    if decision_rationale:
        review.decision_rationale = decision_rationale

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save EA decision: {exc}")

    return {"message": "EA decision recorded", "review_id": review_id, "ea_decision": ea_decision, "status": review.status}


# ── EA Override Endpoints (Tier 3) ────────────────────────────────────────────

VALID_OVERRIDE_TYPES = {"finding_severity", "action_modification", "adr_content", "overall_decision"}


@router.post("/{review_id}/overrides")
async def create_ea_override(
    review_id: str,
    body: Dict[str, Any],
    current_user: tuple = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a governed EA override with mandatory rationale and full audit trail."""
    from app.db.review_models import Review, EAOverride, AuditLog
    from datetime import datetime, timezone
    import uuid as uuid_mod

    user_id_token, user_role = current_user
    if not user_id_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user_role not in ('enterprise_architect', 'arb_admin', 'super_admin'):
        raise HTTPException(status_code=403, detail="Only EA or ARB Admin can create overrides")

    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    override_type  = body.get("override_type")
    target_id      = body.get("target_id")
    original_value = body.get("original_value")
    override_value = body.get("override_value")
    rationale      = body.get("rationale", "")

    if override_type not in VALID_OVERRIDE_TYPES:
        raise HTTPException(status_code=422, detail=f"override_type must be one of {sorted(VALID_OVERRIDE_TYPES)}")
    if not target_id:
        raise HTTPException(status_code=422, detail="target_id is required")
    if original_value is None or override_value is None:
        raise HTTPException(status_code=422, detail="original_value and override_value are required")
    if not rationale or len(rationale.strip()) < 10:
        raise HTTPException(status_code=422, detail="rationale must be at least 10 characters")

    # overall_decision overrides are immutable once the review status advances to ea_approved
    if override_type == "overall_decision" and review.status == "ea_approved":
        raise HTTPException(status_code=409, detail="Review is already EA-approved; overall_decision override is locked")

    now = datetime.now(timezone.utc)
    override = EAOverride(
        review_id      = uuid_mod.UUID(review_id),
        ea_user_id     = uuid_mod.UUID(user_id_token),
        override_type  = override_type,
        target_id      = target_id,
        original_value = original_value,
        override_value = override_value,
        rationale      = rationale.strip(),
        is_immutable   = False,
        created_at     = now,
        updated_at     = now,
    )
    db.add(override)

    # Write audit log
    audit = AuditLog(
        review_id      = uuid_mod.UUID(review_id),
        user_id        = uuid_mod.UUID(user_id_token),
        user_role      = user_role,
        action         = "ea_override_created",
        audit_metadata = {
            "override_type":  override_type,
            "target_id":      target_id,
            "original_value": original_value,
            "override_value": override_value,
            "rationale":      rationale.strip(),
        },
        created_at     = now,
    )
    db.add(audit)

    try:
        db.commit()
        db.refresh(override)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save override: {exc}")

    return {
        "id":             str(override.id),
        "review_id":      review_id,
        "override_type":  override.override_type,
        "target_id":      override.target_id,
        "original_value": override.original_value,
        "override_value": override.override_value,
        "rationale":      override.rationale,
        "is_immutable":   override.is_immutable,
        "created_at":     override.created_at.isoformat(),
        "ea_user_id":     str(override.ea_user_id),
    }


@router.get("/{review_id}/overrides")
async def get_ea_overrides(
    review_id: str,
    override_type: Optional[str] = None,
    current_user: tuple = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return EA overrides for a review, optionally filtered by override_type."""
    from app.db.review_models import Review, EAOverride

    user_id_token, _ = current_user
    if not user_id_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    q = db.query(EAOverride).filter(EAOverride.review_id == review_id)
    if override_type:
        if override_type not in VALID_OVERRIDE_TYPES:
            raise HTTPException(status_code=422, detail=f"override_type must be one of {sorted(VALID_OVERRIDE_TYPES)}")
        q = q.filter(EAOverride.override_type == override_type)

    overrides = q.order_by(EAOverride.created_at.asc()).all()

    grouped: Dict[str, list] = {t: [] for t in VALID_OVERRIDE_TYPES}
    for o in overrides:
        grouped[o.override_type].append({
            "id":             str(o.id),
            "target_id":      o.target_id,
            "original_value": o.original_value,
            "override_value": o.override_value,
            "rationale":      o.rationale,
            "is_immutable":   o.is_immutable,
            "ea_user_id":     str(o.ea_user_id),
            "created_at":     o.created_at.isoformat() if o.created_at else None,
            "confirmed_by":   str(o.confirmed_by) if o.confirmed_by else None,
            "confirmed_at":   o.confirmed_at.isoformat() if o.confirmed_at else None,
        })

    return {"review_id": review_id, "overrides": grouped}


