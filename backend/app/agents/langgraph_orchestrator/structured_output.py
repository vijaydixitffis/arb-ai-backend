"""
Pydantic v2 structured output models for the LangGraph orchestrator path.

DomainReviewPayload  — mirrors the dict emitted by EnhancedDomainValidationAgent.validate_domain().
                       Used to validate/coerce raw agent output at the domain node boundary.

SynthesisOutput      — mirrors the JSON schema expected by _run_synthesis() in the custom path.
                       Used with ChatModel.with_structured_output() in the synthesis node,
                       replacing the regex-stripped parse_json_from_llm() fallback approach.

build_langchain_llm  — factory that returns the correct LangChain BaseChatModel based on
                       settings.LLM_PROVIDER, reading the same env vars as LLMService.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings


# ── Coercion helpers ──────────────────────────────────────────────────────────

def _coerce_str(v: Any) -> Optional[str]:
    """LLM sometimes returns a list where a string is expected — join it."""
    if v is None:
        return None
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) if v else None
    return str(v) if not isinstance(v, str) else v


# ── Domain-level models ───────────────────────────────────────────────────────

class DomainFinding(BaseModel):
    id: str
    check_category: Optional[str] = None
    rag_score: int = Field(ge=1, le=5)
    rag_label: Optional[str] = None
    title: str
    finding: str
    description: Optional[str] = None
    recommendation: Optional[str] = None
    severity: Optional[str] = None
    is_blocker: bool = False
    waiver_eligible: bool = False
    evidence_source: Optional[str] = None
    standard_violated: Optional[str] = None
    impact: Optional[str] = None
    principle_id: Optional[str] = None
    links_to_action_ids: Optional[List[str]] = None
    links_to_adr_id: Optional[str] = None
    kb_reference: Optional[str] = None
    artifact_ref: Optional[str] = None
    kb_ref: Optional[str] = None
    is_resolved: bool = False

    @field_validator("kb_reference", "kb_ref", "artifact_ref", "evidence_source",
                     "standard_violated", "impact", "recommendation",
                     mode="before")
    @classmethod
    def coerce_str_field(cls, v: Any) -> Optional[str]:
        return _coerce_str(v)


class DomainBlocker(BaseModel):
    id: Optional[str] = None
    blocker_id: Optional[str] = None
    domain: Optional[str] = None
    title: str
    description: Optional[str] = None
    violated_standard: Optional[str] = None
    impact: Optional[str] = None
    resolution_required: Optional[str] = None
    is_security_or_dr: bool = False
    check_category: Optional[str] = None
    links_to_finding_id: Optional[str] = None
    status: str = "open"
    kb_evidence_ref: Optional[List[str]] = None


class DomainAction(BaseModel):
    id: Optional[str] = None
    action_id: Optional[str] = None
    domain: Optional[str] = None
    action_type: Optional[str] = None
    title: Optional[str] = None
    action_text: Optional[str] = None
    owner_role: Optional[str] = None
    proposed_owner: Optional[str] = None
    priority: Optional[str] = None
    proposed_due_date: Optional[str] = None
    due_days: Optional[int] = None
    verification_method: Optional[str] = None
    is_conditional_approval_gate: bool = False
    links_to_finding_id: Optional[str] = None
    links_to_blocker_id: Optional[str] = None
    links_to_adr_id: Optional[str] = None
    status: str = "open"


class DomainADR(BaseModel):
    id: Optional[str] = None
    adr_id: Optional[str] = None
    domain: Optional[str] = None
    adr_type: Optional[str] = None
    title: Optional[str] = None
    decision: Optional[str] = None
    rationale: Optional[str] = None
    context: Optional[str] = None
    consequences: Optional[str] = None
    mitigations: Optional[str] = None
    # LLM returns List[Dict] here — keep as Any so the DB layer handles serialisation
    options_considered: Optional[List[Any]] = None
    owner: Optional[str] = None
    status: str = "proposed"
    target_date: Optional[str] = None
    waiver_expiry_date: Optional[str] = None
    links_to_finding_ids: Optional[List[str]] = None
    links_to_action_ids: Optional[List[str]] = None
    kb_references: Optional[List[str]] = None

    @field_validator("mitigations", "consequences", "context", "rationale", "decision",
                     mode="before")
    @classmethod
    def coerce_str_field(cls, v: Any) -> Optional[str]:
        return _coerce_str(v)

    @field_validator("kb_references", mode="before")
    @classmethod
    def coerce_kb_refs(cls, v: Any) -> Optional[List[str]]:
        if v is None:
            return None
        if isinstance(v, str):
            return [v] if v else None
        return [str(x) for x in v] if isinstance(v, list) else None


class DomainRecommendation(BaseModel):
    id: Optional[str] = None
    recommendation_id: Optional[str] = None
    domain: Optional[str] = None
    priority: Optional[str] = None
    title: Optional[str] = None
    rationale: Optional[str] = None
    approved_pattern_ref: Optional[str] = None
    benefit: Optional[str] = None
    implementation_hint: Optional[str] = None
    applies_to_finding_id: Optional[str] = None
    applies_to_adr_id: Optional[str] = None
    is_agent_generated: bool = True
    kb_source_ref: Optional[str] = None

    @field_validator("kb_source_ref", "rationale", "benefit", "implementation_hint",
                     mode="before")
    @classmethod
    def coerce_str_field(cls, v: Any) -> Optional[str]:
        return _coerce_str(v)


class NFRScorecardRow(BaseModel):
    nfr_category: str
    rag_score: int = Field(ge=1, le=5)
    rag_label: Optional[str] = None
    evidence_provided: Optional[List[str]] = None
    gaps: Optional[List[str]] = None
    mitigating_condition: Optional[str] = None
    slo_target: Optional[str] = None
    actual_evidenced: Optional[str] = None
    is_mandatory_green: bool = False


class DomainSummary(BaseModel):
    rag_score: int = Field(ge=1, le=5)
    rag_label: Optional[str] = None
    overall_readiness: Optional[str] = None
    executive_summary: Optional[str] = None
    compliant_areas: Optional[List[str]] = None
    gap_areas: Optional[List[str]] = None
    evidence_quality: Optional[str] = None
    blocker_count: int = 0
    action_count: int = 0
    adr_count: int = 0
    domain_specific_scores: Optional[Dict[str, Any]] = None
    kb_references: Optional[List[str]] = None


class DomainReviewPayload(BaseModel):
    """Top-level model for one domain agent's output.

    Coerce raw validate_domain() dict through this to normalise and validate
    at the domain node boundary before feeding into graph state.
    """
    domain: str
    session_id: Optional[str] = None
    summary: DomainSummary
    findings: List[DomainFinding] = Field(default_factory=list)
    blockers: List[DomainBlocker] = Field(default_factory=list)
    recommendations: List[DomainRecommendation] = Field(default_factory=list)
    actions: List[DomainAction] = Field(default_factory=list)
    adrs: List[DomainADR] = Field(default_factory=list)
    nfr_scorecard: Optional[List[NFRScorecardRow]] = None
    tokens_used: int = 0
    artefact_chunks_used: int = 0
    kb_articles_used: int = 0
    error: Optional[str] = None  # set when the domain agent failed


# ── Synthesis model ───────────────────────────────────────────────────────────

class ScoreCorrection(BaseModel):
    domain: str
    original_score: int
    corrected_score: int
    reason: str


class SynthesisOutput(BaseModel):
    """Structured output for the Tier-2 synthesis LLM call.

    Used with: llm.with_structured_output(SynthesisOutput)
    Mirrors the JSON schema in EnhancedARBOrchestrator._SYNTHESIS_SYSTEM_PROMPT.
    """
    scoreCorrections: List[ScoreCorrection] = Field(default_factory=list)
    retainBlockerIds: Optional[List[str]] = None
    filteredAdrIds: List[str] = Field(default_factory=list)
    removedAdrIds: List[str] = Field(default_factory=list)
    duplicateFindingIds: List[str] = Field(default_factory=list)
    executiveRationale: str
    finalDecision: str  # approve | approve_with_conditions | defer | reject


# ── LangChain LLM factory ─────────────────────────────────────────────────────

def build_langchain_llm(db=None):
    """Return a LangChain BaseChatModel for the active provider.

    Reads the same settings as LLMService so both paths stay in sync.
    The returned model supports .with_structured_output(SynthesisOutput).

    db is accepted but unused — kept for signature symmetry with db_config callers.
    """
    provider = settings.LLM_PROVIDER.strip().lower()

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
            max_output_tokens=settings.LLM_MAX_TOKENS,
        )

    if provider == "openrouter" and settings.OPENROUTER_API_KEY:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.OPENROUTER_MODEL,
            api_key=settings.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )

    # Default: OpenAI
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
    )
