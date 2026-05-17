from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ARRAY, Date
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base
import uuid
from datetime import datetime


class Review(Base):
    __tablename__ = "reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    sa_user_id = Column(UUID(as_uuid=True), nullable=True)
    solution_name = Column(String, nullable=False)
    scope_tags = Column(ARRAY(String), nullable=False)

    # Envelope fields (migration 022)
    arb_ref = Column(String, nullable=True)
    review_version = Column(String, default='v1.0-draft')
    presenting_team = Column(ARRAY(String), nullable=True)
    intake_completed_at = Column(DateTime(timezone=True), nullable=True)
    agent_run_at = Column(DateTime(timezone=True), nullable=True)
    classification = Column(String, default='INTERNAL')

    status = Column(String, nullable=False, default='drafting')
    decision = Column(String, nullable=True)

    # Workflow tracking (migration 023)
    return_count = Column(Integer, nullable=False, default=0)
    rework_gaps  = Column(ARRAY(String), nullable=True)

    # AI agent output columns
    aggregate_rag_score = Column(Integer, nullable=True)
    aggregate_rag_label = Column(String, nullable=True)
    recommended_decision = Column(String, nullable=True)
    decision_rationale = Column(Text, nullable=True)
    kb_sources_cited = Column(ARRAY(String), nullable=True)
    arb_meeting_scheduled_at = Column(DateTime(timezone=True), nullable=True)
    consolidated_blockers = Column(JSONB, nullable=True)
    consolidated_actions = Column(JSONB, nullable=True)

    llm_model = Column(String, default='gpt-4o')
    tokens_used = Column(Integer, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)
    llm_raw_response = Column(Text, nullable=True)

    ea_user_id = Column(UUID(as_uuid=True), nullable=True)
    ea_override_notes = Column(Text, nullable=True)
    ea_overridden_at = Column(DateTime(timezone=True), nullable=True)

    report_json = Column(JSONB, nullable=True)


class DomainScore(Base):
    __tablename__ = "domain_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), nullable=False)
    domain = Column(String, nullable=False)
    score = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Full DomainSummary fields (migration 022)
    rag_label = Column(String, nullable=True)
    overall_readiness = Column(String, nullable=True)
    executive_summary = Column(Text, nullable=True)
    compliant_areas = Column(ARRAY(String), nullable=True)
    gap_areas = Column(ARRAY(String), nullable=True)
    blocker_count = Column(Integer, default=0)
    action_count = Column(Integer, default=0)
    adr_count = Column(Integer, default=0)
    domain_specific_scores = Column(JSONB, nullable=True)
    evidence_quality = Column(String, nullable=True)
    kb_references = Column(ARRAY(String), nullable=True)
    generated_at = Column(DateTime(timezone=True), nullable=True)
    model_used = Column(String, nullable=True)


class Blocker(Base):
    __tablename__ = "blockers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), nullable=False)
    blocker_id = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    violated_standard = Column(Text, nullable=True)
    impact = Column(Text, nullable=True)
    resolution_required = Column(Text, nullable=True)
    links_to_finding_id = Column(String, nullable=True)
    links_to_action_id = Column(String, nullable=True)
    is_security_or_dr = Column(Boolean, default=False)
    status = Column(String, default='OPEN')
    kb_evidence_ref = Column(ARRAY(String), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), nullable=False)
    recommendation_id = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    priority = Column(String, nullable=False, default='MEDIUM')
    title = Column(String, nullable=False)
    rationale = Column(Text, nullable=True)
    approved_pattern_ref = Column(Text, nullable=True)
    benefit = Column(Text, nullable=True)
    implementation_hint = Column(Text, nullable=True)
    applies_to_adr_id = Column(String, nullable=True)
    applies_to_finding_id = Column(String, nullable=True)
    is_agent_generated = Column(Boolean, default=True)
    kb_source_ref = Column(ARRAY(String), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class NFRScorecard(Base):
    __tablename__ = "nfr_scorecard"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), nullable=False)
    nfr_category = Column(String, nullable=False)
    rag_score = Column(Integer, nullable=False)
    rag_label = Column(String, nullable=True)
    evidence_provided = Column(ARRAY(String), nullable=True)
    gaps = Column(ARRAY(String), nullable=True)
    mitigating_condition = Column(Text, nullable=True)
    slo_target = Column(Text, nullable=True)
    actual_evidenced = Column(Text, nullable=True)
    is_mandatory_green = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class EAReviewRecord(Base):
    __tablename__ = "ea_review"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    ea_name = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    ea_decision = Column(String, nullable=True)
    overrides = Column(JSONB, default=list)
    ea_annotations = Column(Text, nullable=True)
    rework_gaps    = Column(ARRAY(String), nullable=True)
    return_domains = Column(ARRAY(String), nullable=True)
    final_decision = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class DomainReview(Base):
    """Per-domain agent progress tracking (migration 023)."""
    __tablename__ = "domain_reviews"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id    = Column(UUID(as_uuid=True), nullable=False)
    domain       = Column(String, nullable=False)
    agent_status = Column(String, nullable=False, default='waiting')
    started_at   = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message= Column(Text, nullable=True)
    retry_count  = Column(Integer, nullable=False, default=0)
    created_at   = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at   = Column(DateTime(timezone=True), default=datetime.utcnow)


class Finding(Base):
    __tablename__ = "findings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), nullable=False)
    domain = Column(String, nullable=False)
    principle_id = Column(String, nullable=True)
    severity = Column(String, nullable=False)
    finding = Column(Text, nullable=False)
    recommendation = Column(Text, nullable=True)
    check_category = Column(String, nullable=True)
    is_resolved = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Extended fields (migration 022)
    finding_id = Column(String, nullable=True)
    title = Column(Text, nullable=True)
    rag_score = Column(Integer, nullable=True)
    evidence_source = Column(Text, nullable=True)
    standard_violated = Column(Text, nullable=True)
    impact = Column(Text, nullable=True)
    is_blocker = Column(Boolean, default=False)
    links_to_action_ids = Column(ARRAY(String), nullable=True)
    links_to_adr_id = Column(String, nullable=True)
    waiver_eligible = Column(Boolean, default=False)
    kb_reference = Column(ARRAY(String), nullable=True)
    artifact_ref = Column(Text, nullable=True)
    kb_ref = Column(Text, nullable=True)


class ADR(Base):
    __tablename__ = "adrs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), nullable=False)
    adr_id = Column(String, nullable=False)
    decision = Column(String, nullable=False)
    rationale = Column(Text, nullable=False)
    context = Column(Text, nullable=True)
    consequences = Column(Text, nullable=True)
    owner = Column(String, nullable=True)
    target_date = Column(Date, nullable=True)
    status = Column(String, default='proposed')
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Extended fields (migration 022)
    domain = Column(String, nullable=True)
    adr_type = Column(String, nullable=True)
    title = Column(Text, nullable=True)
    options_considered = Column(JSONB, nullable=True)
    mitigations = Column(ARRAY(String), nullable=True)
    confirmed_owner = Column(String, nullable=True)
    proposed_owner = Column(String, nullable=True)
    proposed_target_date = Column(String, nullable=True)
    confirmed_target_date = Column(Date, nullable=True)
    waiver_expiry_date = Column(Date, nullable=True)
    links_to_finding_ids = Column(ARRAY(String), nullable=True)
    links_to_action_ids = Column(ARRAY(String), nullable=True)
    confluence_page_id = Column(String, nullable=True)
    cmdb_record_id = Column(String, nullable=True)
    kb_references = Column(ARRAY(String), nullable=True)


class Action(Base):
    __tablename__ = "actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), nullable=False)
    action_text = Column(Text, nullable=False)
    status = Column(String, nullable=False, default='open')
    owner_role = Column(String, nullable=True)
    due_days = Column(Integer, nullable=True)
    due_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Extended fields (migration 022)
    action_id = Column(String, nullable=True)
    domain = Column(String, nullable=True)
    action_type = Column(String, nullable=True)
    title = Column(Text, nullable=True)
    proposed_owner = Column(String, nullable=True)
    confirmed_owner = Column(String, nullable=True)
    proposed_due_date = Column(String, nullable=True)
    confirmed_due_date = Column(Date, nullable=True)
    verification_method = Column(Text, nullable=True)
    is_conditional_approval_gate = Column(Boolean, default=False)
    links_to_finding_id = Column(String, nullable=True)
    links_to_blocker_id = Column(String, nullable=True)
    links_to_adr_id = Column(String, nullable=True)
    reminder_schedule = Column(ARRAY(String), nullable=True)
    closure_evidence = Column(Text, nullable=True)
    closed_by_ea_at = Column(DateTime(timezone=True), nullable=True)
    priority = Column(String, nullable=True)


class EAOverride(Base):
    __tablename__ = "ea_overrides"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id      = Column(UUID(as_uuid=True), nullable=False)
    ea_user_id     = Column(UUID(as_uuid=True), nullable=False)
    created_at     = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at     = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    override_type  = Column(String, nullable=False)   # finding_severity | action_modification | adr_content | overall_decision
    target_id      = Column(String, nullable=False)   # finding/action/ADR id, or 'overall'
    original_value = Column(JSONB,  nullable=False)
    override_value = Column(JSONB,  nullable=False)
    rationale      = Column(Text,   nullable=False)

    is_immutable   = Column(Boolean, nullable=False, default=False)
    confirmed_by   = Column(UUID(as_uuid=True), nullable=True)
    confirmed_at   = Column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), nullable=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    user_role = Column(String, nullable=True)
    action = Column(String, nullable=False)
    old_status = Column(String, nullable=True)
    new_status = Column(String, nullable=True)
    old_decision = Column(String, nullable=True)
    new_decision = Column(String, nullable=True)
    audit_metadata = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
