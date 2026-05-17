"""
Enhanced Domain Validation Agent — aligned with the Pre-ARB AI Agent spec.

Prompt structure mirrors the TypeScript edge-function orchestrator:
  SYSTEM  → role + 10 RULES + SCORING RULES
  USER    → REVIEW SESSION / KB CONTEXT / SA ARTIFACTS / CHECKLIST /
            ID SEED / MANDATORY CATEGORIES / OUTPUT SCHEMA

Output: DomainReviewPayload  (summary, blockers, recommendations, findings, actions, adrs)
"""

from __future__ import annotations

import logging
import time
import uuid as uuid_mod
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.llm_service import llm_service, LLMService
from app.services.artefact_service import ArtefactService
from app.db.review_models import AuditLog, Review
from app.core.config import settings
from app.core.db_config import db_config

logger = logging.getLogger(__name__)

# ── Domain metadata ────────────────────────────────────────────────────────────

DOMAIN_CODE: Dict[str, str] = {
    "solution":       "SOL",
    "business":       "BUS",
    "application":    "APP",
    "integration":    "INT",
    "data":           "DAT",
    "security":       "SEC",
    "infrastructure": "INF",
    "devsecops":      "DSO",
    "nfr":            "NFR",
}

DOMAIN_LABEL: Dict[str, str] = {
    "solution":       "Solution",
    "business":       "Business Domain",
    "application":    "Application Domain",
    "integration":    "Integration Domain",
    "data":           "Data Domain",
    "security":       "Security Domain",
    "infrastructure": "Infrastructure & Platform",
    "devsecops":      "DevSecOps Domain",
    "nfr":            "Non-Functional Requirements",
}

# Maps Python domain slug → question_registry.frontend_tab values
# (frontend_tab uses full slug names matching the Python DB)
DOMAIN_TO_QR_TABS: Dict[str, List[str]] = {
    "solution":       ["solution"],
    "business":       ["business"],
    "application":    ["application"],
    "integration":    ["integration"],
    "data":           ["data"],
    "security":       ["infrastructure", "nfr"],  # infra-sec-* + nfr-sec-*
    "infrastructure": ["infrastructure"],
    "devsecops":      ["devsecops"],
    "nfr":            ["nfr"],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rag_score_to_severity(rag_score: int) -> str:
    """Map LLM rag_score (1-5) to DB findings.severity constraint values."""
    if rag_score <= 1:
        return "critical"
    if rag_score <= 2:
        return "major"
    return "minor"


# ── Domain Agent ──────────────────────────────────────────────────────────────

class EnhancedDomainValidationAgent:
    """Per-domain LLM agent producing a spec-compliant DomainReviewPayload."""

    def __init__(self, db: Session):
        self.db = db
        self.llm_service: LLMService = llm_service
        self.artefact_service = ArtefactService(db)

    # ── Main entry point ──────────────────────────────────────────────────────

    async def validate_domain(
        self,
        review_id: str,
        domain_slug: str,
        checklist_data: Dict[str, Any],
        content_scale: float = 1.0,
    ) -> Dict[str, Any]:
        """Validate a single domain and return a DomainReviewPayload dict.

        content_scale (0 < scale ≤ 1.0): multiplier applied to chunk and KB
        fetch limits. Pass < 1.0 on retries to reduce token usage.
        """
        t0 = time.time()
        logger.info(
            f"[DOMAIN-AGENT] validate_domain domain={domain_slug} review={review_id} "
            f"content_scale={content_scale}"
        )

        domain_code  = DOMAIN_CODE.get(domain_slug, domain_slug.upper()[:3])
        domain_label = DOMAIN_LABEL.get(domain_slug, domain_slug.title())

        chunk_limit  = max(1, int(db_config(self.db, "agent.kb_chunk_limit",      settings.KB_CHUNK_LIMIT)      * content_scale))
        kb_dom_limit = max(1, int(db_config(self.db, "agent.kb_max_results",       settings.KB_DOMAIN_RESULTS)   * content_scale))
        kb_gen_limit = max(1, int(db_config(self.db, "agent.kb_max_results_general", settings.KB_GENERAL_RESULTS) * content_scale))

        # 1. Artefact chunks
        chunks = await self.artefact_service.get_relevant_chunks(
            review_id=review_id, domain_slug=domain_slug, limit=chunk_limit
        )
        logger.info(f"[DOMAIN-AGENT] {domain_slug}: {len(chunks)} artefact chunks (limit={chunk_limit})")

        # 2. Knowledge-base context (domain + general)
        kb_domain  = await self.artefact_service.search_knowledge_base(
            query=f"{domain_slug} architecture principles standards",
            category=domain_slug, limit=kb_dom_limit,
        )
        kb_general = await self.artefact_service.search_knowledge_base(
            query="enterprise architecture principles", category="solution", limit=kb_gen_limit,
        )
        kb_results = kb_domain + kb_general
        logger.info(f"[DOMAIN-AGENT] {domain_slug}: {len(kb_results)} KB articles (limits={kb_dom_limit}+{kb_gen_limit})")

        # 3. Check categories from question_registry
        check_categories = self._get_check_categories(domain_slug)

        # 4. NFR quantitative criteria (only for nfr domain)
        nfr_context = ""
        if domain_slug == "nfr":
            review = self.db.query(Review).filter(Review.id == review_id).first()
            nfr_context = self._build_nfr_criteria_block(review)

        # 5. Build prompts (spec structure)
        system_prompt = self._build_system_prompt(domain_label, domain_slug)
        user_prompt   = self._build_user_prompt(
            session_id=review_id,
            domain_slug=domain_slug,
            domain_code=domain_code,
            checklist_data=checklist_data,
            chunks=chunks,
            kb_results=kb_results,
            check_categories=check_categories,
            nfr_context=nfr_context,
        )

        # 6. Call LLM — audit both success and failure paths
        logger.info(f"[DOMAIN-AGENT] calling LLM for {domain_slug}")
        try:
            response = await self.llm_service.generate_completion(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=db_config(self.db, "agent.domain_temperature", settings.DOMAIN_LLM_TEMPERATURE),
                max_tokens=int(db_config(self.db, "agent.domain_max_tokens", settings.DOMAIN_LLM_MAX_TOKENS)),
                timeout=120,
                db=self.db,
            )
        except Exception as llm_exc:
            self._audit_llm(
                review_id, domain_slug,
                response=None, error=llm_exc,
                user_prompt=user_prompt, system_prompt=system_prompt,
            )
            raise

        self._audit_llm(
            review_id, domain_slug,
            response=response, error=None,
            user_prompt=user_prompt, system_prompt=system_prompt,
        )

        # 7. Parse DomainReviewPayload
        raw_content = response.get("content") or ""
        logger.debug(f"[DOMAIN-AGENT] raw LLM response for {domain_slug}: {raw_content[:800]}")
        try:
            payload = LLMService.parse_json_from_llm(raw_content)
        except Exception as exc:
            logger.error(f"[DOMAIN-AGENT] JSON parse failed for {domain_slug}: {exc}")
            logger.error(f"[DOMAIN-AGENT] First 200 chars: {raw_content[:200]}")
            logger.error(f"[DOMAIN-AGENT] Last 200 chars: {raw_content[-200:] if len(raw_content) > 200 else raw_content}")
            payload = {
                "domain": domain_slug,
                "session_id": review_id,
                "summary": {
                    "rag_score": 2,
                    "rag_label": "RED",
                    "overall_readiness": "DEFER",
                    "rationale": "LLM response parse failure — domain result unavailable; manual review required",
                    "evidence_quality": "ABSENT",
                    "total_findings": 1, "blocker_count": 0, "mandatory_gaps": 0,
                },
                "blockers": [],
                "recommendations": [],
                "findings": [{
                    "id": f"{domain_slug.upper()[:3]}-F01",
                    "check_category": "PARSE_FAILURE",
                    "rag_score": 2,
                    "rag_label": "RED",
                    "title": f"LLM response parse failure for {domain_slug} domain — re-trigger review",
                    "finding": "The LLM returned a response that could not be parsed as valid JSON. "
                               "This domain has not been assessed. Re-trigger the review to obtain a valid result.",
                    "description": str(exc),
                    "is_blocker": False,
                    "waiver_eligible": False,
                }],
                "actions": [{
                    "id": f"{domain_slug.upper()[:3]}-ACT-01",
                    "domain": domain_slug.upper()[:3],
                    "action_type": "EVIDENCE_SUBMISSION",
                    "title": f"Re-trigger ARB review for {domain_slug} domain",
                    "action": "The domain agent returned an unparseable response. Re-submit the review to obtain a valid assessment.",
                    "proposed_owner": "solution_architect",
                    "priority": "HIGH",
                }],
                "adrs": [],
            }

        payload["tokens_used"]          = response.get("tokens_used", 0)
        payload["artefact_chunks_used"] = len(chunks)
        payload["kb_articles_used"]     = len(kb_results)

        logger.info(
            f"[DOMAIN-AGENT] {domain_slug} done in {time.time()-t0:.2f}s "
            f"rag_score={payload.get('summary', {}).get('rag_score')} "
            f"findings={len(payload.get('findings', []))} "
            f"blockers={len(payload.get('blockers', []))} "
            f"actions={len(payload.get('actions', []))} "
            f"adrs={len(payload.get('adrs', []))}"
        )
        return payload

    # ── Audit helper ──────────────────────────────────────────────────────────

    def _audit_llm(
        self,
        review_id: str,
        domain_slug: str,
        response: Optional[Dict],
        error: Optional[Exception],
        user_prompt: str = "",
        system_prompt: str = "",
    ) -> None:
        """Write one audit_log row recording the LLM call outcome for this domain.

        Uses a fresh DB session so the write is unaffected by the state of the
        shared session (e.g. an aborted transaction from a prior domain failure).
        """
        from app.core.database import SessionLocal
        try:
            meta: Dict[str, Any] = {
                "domain_slug":   domain_slug,
                "request": {
                    "system_prompt": system_prompt,
                    "user_prompt":   user_prompt,
                },
            }
            if response is not None:
                meta.update({
                    "status":       "success",
                    "model":        response.get("model"),
                    "provider":     response.get("provider"),
                    "tokens_used":  response.get("tokens_used", 0),
                    "raw_response": response.get("content", ""),
                })
            if error is not None:
                meta.update({
                    "status":     "error",
                    "error":      str(error),
                    "error_type": type(error).__name__,
                })
            log_entry = AuditLog(
                review_id=uuid_mod.UUID(review_id),
                action="llm_domain_review",
                audit_metadata=meta,
            )
            audit_db = SessionLocal()
            try:
                audit_db.add(log_entry)
                audit_db.commit()
            finally:
                audit_db.close()
        except Exception as log_exc:
            logger.warning(f"[DOMAIN-AGENT] audit log failed ({log_exc})")

    # ── System prompt (spec §RULES + SCORING RULES) ───────────────────────────

    def _build_system_prompt(self, domain_label: str, domain_slug: str = "") -> str:
        # Domain-specific key first, then generic fallback, then hardcoded constant.
        try:
            from app.db.admin_models import PromptTemplate
            keys = [f"domain.system.{domain_slug}", "domain.system"] if domain_slug else ["domain.system"]
            for key in keys:
                db_prompt = (
                    self.db.query(PromptTemplate)
                    .filter(PromptTemplate.prompt_key == key, PromptTemplate.is_active == True)
                    .order_by(PromptTemplate.version.desc())
                    .first()
                )
                if db_prompt and db_prompt.content:
                    return db_prompt.content.format(domain_label=domain_label, domain_slug=domain_slug)
        except Exception:
            pass

        return f"""You are a senior {domain_label} architect acting as a specialist reviewer in the Pre-ARB AI Agent pipeline.
Your role is to conduct a thorough, proportionate review of the Solution Architect's submission against
enterprise architecture standards — producing a balanced assessment that reflects real-world ARB practice.

ARB SCOPE — DESIGN, ARCHITECTURE, AND PLANNING ONLY:
This review covers the quality and completeness of the architectural design, not operational readiness.
The ARB's purpose is to verify the solution has sufficient architectural inputs for a development team
to build, deploy, and test it — not to confirm that building, deployment, or testing has occurred.
Score based on whether the DESIGN is sound and complete enough to proceed. Do NOT penalise the absence
of test results, runbooks, operational metrics, or deployed-state evidence — those belong post-ARB.

RULES:
1. Respond ONLY with a valid JSON object matching DomainReviewPayload schema.
   No preamble, no markdown, no explanation outside the JSON.

2. Every finding MUST reference a specific SA artifact section OR a relevant KB document.
   Focus on material gaps affecting architecture quality, security, or operability.
   When the SA has addressed a requirement with reasonable evidence (even if not in the prescribed format),
   credit it and note the finding as GREEN or AMBER rather than inventing a gap.

3. RAG scoring — calibrate proportionately:
   • rag_score 1 (BLOCKER): Critical architecture gap preventing approval — unmitigated security design
     risk, absent mandatory compliance approach, critical domain with no architectural design at all.
     → Add to blockers[]. blockers[] ONLY contains rag_score 1 findings. NEVER add rag_score 2 or higher to blockers[].
   • rag_score 2 (RED): Significant design gap — mandatory architectural artefact absent or approach
     conflicts with EA standards. Design must be revised before development can proceed.
     → Add to findings[] with a HIGH priority action. NEVER add to blockers[].
   • rag_score 3 (AMBER): Design gaps present but a clear remediation path exists; trackable post-approval.
     → Add to findings[] with a MEDIUM priority action.
   • rag_score 4 (GREEN+): Design well-addressed; only minor follow-up actions logged.
   • rag_score 5 (GREEN): Comprehensive design — all mandatory architecture artefacts present; sufficient
     detail for a development team to build, deploy, and test the solution without further architectural
     clarification.
   Reserve rag_score 1 ONLY for genuinely unmitigable security/architecture blockers. Prefer RED (2) for
   significant gaps, AMBER (3) for non-critical gaps. Use rag_score 4 liberally when the SA has done
   solid design work with minor loose ends.

4. Every finding with rag_score <= 3 (AMBER or RED) MUST have at least one Action in actions[].

5. Generate ADRs only for genuine architectural decisions — apply the ARCHITECTURAL-CHOICE TEST:
   Ask: "Is there a deliberate design decision between two or more viable architectural options?"
   YES → generate an ADR.  NO (just a missing plan or incomplete documentation) → action only.

   MANDATORY ADR cases:
   - A conscious choice to use a technology or pattern that deviates from EA standards → DECISION
   - A deliberate architectural trade-off (e.g. choosing eventual consistency over strong consistency) → DECISION
   - Any rag_score 1 blocker that represents a genuine design exception (not just a missing artefact) → WAIVER

   NOT an ADR (action only — do not generate an ADR for these):
   - Missing VAPT plan, DR test plan, runbook, or other planning artefact → action to produce the plan
   - Incomplete or vague documentation → action to complete it
   - Absent evidence of a standard approach (where no deviation was chosen) → action to provide evidence

   adrs[] may be empty. Only generate ADRs when the architectural-choice test passes.

6. ADRs of type WAIVER must include a proposed waiver_expiry_date (ISO date string).

7. summary.rag_score reflects overall domain readiness — calibrate against the finding distribution:
   - Mostly GREEN (4–5) with 1–2 minor AMBERs → summary GREEN (4)
   - Mix of GREEN and AMBER, no blockers → summary AMBER (3)
   - Any rag_score=2 finding OR multiple AMBERs without mitigations → summary RED (2)
   - Any blocker (rag_score=1) → summary RED (1)
   The summary should represent what an ARB panel would conclude about this domain's design readiness.

8. When a design artefact is absent, apply proportionate judgment within ARB scope:

   IN SCOPE — ARCHITECTURE DESIGN artefacts (rag_score 1–2 eligible; security domain may blocker):
   • Threat model / security risk assessment design
   • RBAC and access control design
   • Encryption-at-rest and in-transit design  (NOT operational key-management evidence)
   • Network security architecture and zone design
   • HA/failover design — mechanism, RTO/RPO targets defined in architecture  (NOT failover test results)
   • Observability design — what will be monitored, alerting approach  (NOT live metrics or dashboards)
   • Capacity model / sizing approach  (NOT measured throughput, benchmark, or load-test results)
   • CI/CD pipeline design with security tooling integration approach  (NOT SAST/DAST scan results)

   ADVISORY SCOPE — testing and operational planning artefacts (cap at rag_score 3, NEVER a Blocker):
   • VAPT plan — scope, methodology, and timeline  (NOT VAPT results or pen-test reports)
     Absent VAPT plan → rag_score 3 (AMBER) + action to produce before go-live. NEVER rag_score 1–2.
   • DR test plan — recovery testing methodology and schedule  (NOT DR test results)
     Absent DR test plan → rag_score 3 (AMBER) + action to produce before go-live. NEVER rag_score 1–2.

   OUT OF SCOPE — do NOT raise any finding for absence of:
   • Test results of any kind — unit, integration, load, performance, VAPT, DR
   • Runbook completeness or operational procedures
   • Live monitoring metrics, alerting proof, or deployed-state evidence
   • SAST/DAST scan results, penetration test reports, or security-tool output
   • Proof-of-concept results or benchmark measurements

   CRITICAL — RAID log "not completed" entries:
   If the RAID log, risk register, or any artefact states "VAPT not completed before ARB",
   "DR drill not completed", "penetration test pending", or any similar statement that a
   test or activity has not yet been executed: this is test EXECUTION — completely OUT OF SCOPE.
   Do NOT create any finding or blocker for this. Ignore it entirely.
   The only valid VAPT/DR check: does a VAPT PLAN or DR TEST PLAN document exist? If absent,
   score AMBER (3) with an action — never a blocker.

   Scoring when design artefacts are absent:
   - Security architecture absent (no threat model, no RBAC, no encryption design) → rag_score 1–2
   - HA/DR architecture absent (no failover design, no RTO/RPO targets in the design) → rag_score 1–2
   - VAPT plan absent → rag_score 3 (AMBER) + action. NEVER rag_score 1–2. NEVER a Blocker.
   - DR test plan absent → rag_score 3 (AMBER) + action. NEVER rag_score 1–2. NEVER a Blocker.
   - VAPT results absent → not a finding.  DR test results absent → not a finding.
   - Non-critical artefact absent, SA has a documented plan with owner and timeline → rag_score 3
   - Vague "will be addressed post-launch" does not satisfy a mandatory check → rag_score 2

9. Do not invent evidence. Flag genuine absences explicitly — note WHAT is missing and WHY it matters.
   When the SA has documented their rationale for a deviation, assess whether the rationale is adequate
   rather than automatically flagging as non-compliant.

10. Security domain Blockers — ARCHITECTURE DESIGN gaps only:
    A finding becomes a Blocker (is_security_or_dr: true) ONLY when it represents an absent or
    fundamentally inadequate security ARCHITECTURE design element:
    • No threat model or security risk assessment design
    • No RBAC / access control design
    • No encryption-at-rest or in-transit design
    • No network security architecture or zone design
    Any other security finding — including a missing VAPT plan, DR test plan, or any testing/
    operational planning artefact — must NOT be a Blocker. Score these rag_score 3 (AMBER) with
    an action only. Never set is_security_or_dr: true for a missing planning artefact.

PRAGMATISM GUIDELINES:
- Calibrate against the solution's risk profile. A customer-facing, regulated system warrants stricter
  scrutiny than an internal analytics tool. Let the problem statement and stakeholder context inform weight.
- Distinguish mandatory enterprise standards from best-practice guidance. Flag violations of the former
  as RED/AMBER; treat the latter as recommendations with LOW priority.
- The knowledge base may not cover every scenario. Where KB guidance is sparse, apply professional
  judgment informed by the solution's context and general architecture principles.
- Accept evidence addressing the INTENT of a requirement, even if not in the exact prescribed format.
- For intentional design trade-offs (e.g., MVP simplicity over full resilience), assess whether the
  trade-off is proportionate, documented, and time-bounded — not just whether it follows the standard.
- When the SA has made a well-reasoned deviation with documented rationale, acknowledge it explicitly
  and assess the rationale's adequacy rather than treating silence and bad reasoning the same way.

COVERAGE REQUIREMENT:
- Assess every check category listed in the prompt. For fully addressed categories,
  a GREEN finding (rag_score 4–5) that briefly acknowledges compliance IS the correct output.
  Do not manufacture concerns for well-covered areas. Do not skip any category.

ADR GENERATION REQUIREMENT:
- You MUST generate ADRs when you identify any of the following:
  • Technology choices between viable options (e.g., choosing between different databases, frameworks, or cloud services)
  • Deviations from enterprise standards or patterns that require formal documentation
  • Architectural trade-offs where the SA has chosen one approach over others
  • Design decisions that have significant consequences and need formal ratification
  • Security or compliance exceptions that require waiver documentation
- Do NOT generate ADRs for missing documentation or plans - those should be actions, not ADRs.
- Each ADR must include specific options considered with clear pros/cons.

RECOMMENDATION GENERATION REQUIREMENT:
- You MUST generate recommendations for strategic improvements, even when findings are GREEN:
  • Suggest architectural patterns or best practices that would strengthen the solution
  • Recommend additional capabilities that could provide business value
  • Suggest optimizations for performance, security, or maintainability
  • Provide guidance on future-proofing or scalability considerations
- Recommendations should be distinct from actions - they are strategic guidance, not mandatory fixes.
- Generate at least 1-3 recommendations per domain, even for well-designed solutions.

SCORING RULES:
5 = Comprehensive design — all mandatory architecture artefacts present; sufficient detail for a
    development team to build, deploy, and test the solution without further architectural clarification
4 = Compliant — design well-addressed; only minor tracked actions remain (e.g., doc update, detail clarification)
3 = Partially compliant — design gaps present but SA has a credible, time-bound remediation plan
2 = Significant design gap — mandatory architectural artefact absent or conflicts with EA standards
1 = Critical architecture gap — unmitigated design risk or mandatory standard violated with no mitigation (BLOCKER)""" + ("""

SOLUTION DOMAIN — SPECIALIST GUIDANCE:
As the Solution reviewer your primary responsibility is to assess whether this submission is
problem-driven, well-defined, and strategically aligned — not just technically complete.

SCOPE BOUNDARY FOR SOLUTION DOMAIN:
This domain covers STRATEGIC ALIGNMENT only — problem quality, solution fit, business outcomes,
stakeholder alignment, and strategic context. Do NOT generate security or DR/HA blockers from
this domain. Any is_security_or_dr field in your blockers[] must always be false. If you find
security or DR risks in RAID logs or artefacts, note them in recommendations[], not blockers[].

KEY ASSESSMENT AREAS (generate a finding for each, even if all artefacts are absent):
- PROBLEM_STATEMENT_QUALITY: Search BOTH the form-provided fields AND all submitted artefacts
  for problem statement content before scoring — it may exist in uploaded documents even if the
  form field is empty.
  • Absent from BOTH form AND all submitted artefacts → rag_score 2 (RED, significant gap; NOT a blocker)
  • Present but vague/generic, no measurable impact stated → rag_score 2–3
  • Clear, specific, measurable, customer-grounded → rag_score 4–5
- SOLUTION_FIT: Does the proposed solution directly address the root cause of the stated problem?
  Assess alignment between the problem description and the architectural approach in the artefacts.
- BUSINESS_OUTCOMES: Are target outcomes Specific, Measurable, Achievable, Relevant, Time-bound?
  Generic outcomes ("improve performance", "reduce cost") without metrics → rag_score 2–3.
  SMART outcomes with measurable KPIs and timelines → rag_score 4–5.
- STAKEHOLDER_ALIGNMENT: Are key stakeholders identified with clear ownership and accountability?
- STRATEGIC_FIT: Does the solution align with the stated enterprise business drivers?

WEIGHTING — PROBLEM STATEMENT:
The problem statement quality carries significant weight in the overall domain score.
A solution with strong technical artefacts but a vague or absent problem statement should score
no higher than rag_score 3 (AMBER) for this domain overall.
A well-framed problem with SMART outcomes and demonstrated solution-fit warrants rag_score 4–5.

OUTPUT ADDITION — include a "project_context" object at the top level of your JSON response:
{
  "project_context": {
    "problem_statement_assessed": "Brief restatement of the SA's problem as you understood it",
    "problem_statement_quality": "clear | vague | absent",
    "outcomes_measurability": "measurable | partial | not_measurable | absent",
    "solution_fit_assessment": "One sentence on how well the solution addresses the stated problem"
  }
}""" if domain_slug == "solution" else "")

    # ── User prompt (all spec sections) ──────────────────────────────────────

    def _build_user_prompt(
        self,
        session_id:       str,
        domain_slug:      str,
        domain_code:      str,
        checklist_data:   Dict[str, Any],
        chunks:           List[Dict[str, Any]],
        kb_results:       List[Dict[str, Any]],
        check_categories: List[Dict[str, Any]],
        nfr_context:      str,
    ) -> str:
        from datetime import datetime, timezone

        review_date    = datetime.now(timezone.utc).isoformat()
        domain_label   = DOMAIN_LABEL.get(domain_slug, domain_slug.title())
        meta           = checklist_data.get("domain_metadata", {})
        solution_name  = meta.get("solution_name", "(not provided)")

        # --- Project info block (always brief; expanded for solution domain) ---
        problem_statement       = meta.get("problem_statement") or "(not provided)"
        business_drivers        = meta.get("business_drivers") or []
        stakeholders            = meta.get("stakeholders") or []
        target_business_outcomes = meta.get("target_business_outcomes") or "(not provided)"

        # --- KB section ---
        kb_lines: List[str] = []
        for i, kb in enumerate(kb_results[:10], 1):
            kb_lines.append(f"\n[KB-{i:02d} | {kb.get('principle_id', 'N/A')}]\n{kb['title']}\n{kb['content']}")
        kb_block = "\n".join(kb_lines) if kb_lines else "(No KB entries loaded for this domain.)"

        # --- SA Artifacts section ---
        artifact_lines: List[str] = []
        for i, chunk in enumerate(chunks[:15], 1):
            artifact_lines.append(
                f"\n--- Artefact {i}: {chunk.get('filename', 'Unknown')} ---\n{chunk['chunk_text']}"
            )
        artifact_block = "\n".join(artifact_lines) if artifact_lines else "(No artefact content available.)"
        if nfr_context:
            artifact_block += f"\n\n{nfr_context}"

        # --- Checklist section ---
        checklist_lines: List[str] = []
        items = checklist_data.get("checklist_items", [])
        for item in items:
            q    = item.get("question_text", item.get("question", "N/A"))
            code = item.get("question_code", "")
            ans  = item.get("answer", "not_answered")
            ev   = item.get("evidence", "") or "(none provided)"
            checklist_lines.append(
                f"  {code:<15}  {q}\n"
                f"             Answer:   {ans.upper()}\n"
                f"             Evidence: {ev}"
            )
        checklist_block = "\n".join(checklist_lines) if checklist_lines else "(No checklist items provided.)"

        # --- Mandatory check categories ---
        if check_categories:
            cat_lines = []
            for c in check_categories:
                flag = "  [MANDATORY-GREEN] " if c["is_mandatory_green"] else "  "
                suffix = "  ← non_compliant = BLOCKER" if c["is_mandatory_green"] else ""
                cat_lines.append(f"{flag}{c['category']}{suffix}")
            categories_block = "\n".join(cat_lines)
        else:
            categories_block = "  (no categories registered — use check_category from checklist above)"

        # --- Solution context block ---
        if domain_slug == "solution":
            solution_context_block = f"""== PROJECT INFORMATION (PRIMARY ASSESSMENT CONTEXT) ==
Solution Name:            {solution_name}
Problem Statement:        {problem_statement}
Business Drivers:         {'; '.join(business_drivers) if business_drivers else '(not provided)'}
Stakeholders:             {', '.join(stakeholders) if stakeholders else '(not provided)'}
Target Business Outcomes: {target_business_outcomes}

ASSESSMENT INSTRUCTIONS:
1. Assess the QUALITY of the problem statement — not just whether one was provided.
   A strong problem statement identifies the customer/stakeholder, describes the pain or opportunity,
   quantifies the impact, and is specific enough to evaluate solution-fit.
2. Assess whether target outcomes are SMART (Specific, Measurable, Achievable, Relevant, Time-bound).
3. Assess solution-fit: does the architectural approach in the artefacts directly address the problem?
   Document gaps or misalignments explicitly.
4. Generate a PROBLEM_STATEMENT_QUALITY finding and a BUSINESS_OUTCOMES finding regardless of other coverage."""
        else:
            solution_context_block = f"""== SOLUTION CONTEXT ==
Solution Name:    {solution_name}
Problem Summary:  {problem_statement}
Domain:           {domain_label}
Description:      {checklist_data.get("domain_metadata", {}).get("description", "")}"""

        project_context_schema_hint = (
            '\nInclude "project_context" as the first key (Solution domain only):\n'
            '  "project_context": {\n'
            '    "problem_statement_assessed": "Brief restatement of the SA\'s problem as you understood it",\n'
            '    "problem_statement_quality": "clear | vague | absent",\n'
            '    "outcomes_measurability": "measurable | partial | not_measurable | absent",\n'
            '    "solution_fit_assessment": "One sentence: how well the solution addresses the stated problem"\n'
            '  },\n'
            if domain_slug == "solution" else ""
        )

        return f"""== REVIEW SESSION ==
session_id: {session_id}
solution_name: {solution_name}
domain_under_review: {domain_code}
review_date: {review_date}

{solution_context_block}

== KNOWLEDGE BASE CONTEXT (retrieved for this domain) ==
{kb_block}

== SA SUBMITTED ARTIFACTS ==
{artifact_block}

== SA CHECKLIST ANSWERS & EVIDENCE ==
{checklist_block}

== ID SEED ==
finding_id_start:        {domain_code}-F01
blocker_id_start:        {domain_code}-BLK-01
recommendation_id_start: {domain_code}-REC-01
action_id_start:         {domain_code}-ACT-01
adr_id_start:            ADR-{domain_code}-01
Use these as starting IDs, incrementing sequentially (F01, F02, F03 ...).

== MANDATORY CHECK CATEGORIES FOR THIS DOMAIN ==
Assess each category below against ARCHITECTURAL COMPLETENESS — design quality and planning adequacy.
Do NOT penalise absence of test results, runbooks, operational metrics, or deployed-state evidence;
these are outside ARB scope. Penalise absence of the design, plan, or architectural approach itself.
  - Fully compliant design → GREEN finding (rag_score 4–5) briefly acknowledging coverage is the correct output.
  - Partial design or minor gap → AMBER finding (rag_score 3) in findings[] with a time-bound action.
  - Significant design gap → RED finding (rag_score 2) in findings[] with a HIGH priority action. NEVER in blockers[].
  - Unmitigable architecture blocker → rag_score 1 in blockers[] AND findings[]. Only use when approval is truly impossible without resolution.
Do not manufacture concerns for well-addressed areas. Do not skip any listed category.
Categories marked [MANDATORY-GREEN] require rag_score = 1 if the SA answer is non_compliant
(check artifact evidence first — adequate mitigating design evidence can raise this to rag_score 2).

{categories_block}

== ADR AND RECOMMENDATION GENERATION INSTRUCTIONS ==
IMPORTANT: You must generate both ADRs and recommendations for every domain review:

ADR GENERATION:
- Look for technology choices, design trade-offs, or deviations from standards in the SA's submission
- If the SA chose AWS over Azure, Spring Boot over .NET, or made other architectural decisions - create an ADR
- If the SA deviated from enterprise patterns with documented rationale - create a waiver ADR
- Each ADR must show at least 2 options considered with pros/cons

RECOMMENDATION GENERATION:
- Even for GREEN findings, suggest strategic improvements
- Recommend architectural patterns, best practices, or additional capabilities
- Provide guidance on performance, security, scalability, or future-proofing
- Generate 1-3 recommendations per domain minimum

== OUTPUT SCHEMA ==
Return a JSON object with this exact top-level structure. No markdown. No prose outside the JSON.
NOTE on is_security_or_dr: Set to true ONLY when a blocker represents a security ARCHITECTURE gap
or an HA/DR DESIGN gap. Platform/infrastructure operational blockers (missing runbook, capacity config,
operational procedures) must have is_security_or_dr: false.
{project_context_schema_hint}
{{
  "domain": "{domain_code}",
  "session_id": "{session_id}",
  "summary": {{
    "rag_score": 3,
    "rag_label": "GREEN | AMBER | RED",
    "overall_readiness": "APPROVE | APPROVE_WITH_CONDITIONS | DEFER | REJECT",
    "rationale": "One-sentence justification for the domain rag_score",
    "executive_summary": "3-5 sentences covering: current state, key strengths, critical gaps, ARB readiness",
    "compliant_areas": ["Area 1 — references specific standard or pattern", "Area 2"],
    "gap_areas": ["{domain_code}-F01: Short gap description", "{domain_code}-F02: ..."],
    "total_findings": 0,
    "blocker_count": 0,
    "action_count": 0,
    "adr_count": 0,
    "mandatory_gaps": 0,
    "evidence_quality": "COMPLETE | PARTIAL | INSUFFICIENT | ABSENT",
    "domain_specific_scores": {{}},
    "kb_references": ["KB-DOC-ID-1", "KB-DOC-ID-2"]
  }},
  "blockers": [
    {{
      "id": "{domain_code}-BLK-01",
      "domain": "{domain_code}",
      "title": "Specific title ≤120 chars — name the control or standard violated",
      "description": "1-3 sentences: what is missing/failing, which SA artifact, why non-compliant",
      "violated_standard": "Standard name and version e.g. Security Standards v2.4 §3.2",
      "impact": "Specific business or technical consequence if unresolved",
      "resolution_required": "Exact artifact or evidence the SA must produce to close this",
      "links_to_finding_id": "{domain_code}-F01",
      "is_security_or_dr": false,
      "status": "OPEN",
      "kb_evidence_ref": ["KB-DOC-ID"]
    }}
  ],
  "recommendations": [
    {{
      "id": "{domain_code}-REC-01",
      "domain": "{domain_code}",
      "priority": "CRITICAL | HIGH | MEDIUM | LOW",
      "title": "Action-verb lead: Implement X for Y — specific to this solution",
      "rationale": "Why this recommendation applies to this specific solution (1-2 sentences)",
      "approved_pattern_ref": "Pattern or standard name and version from KB",
      "benefit": "Specific measurable or verifiable benefit",
      "implementation_hint": "Optional: concrete first step for the SA",
      "applies_to_finding_id": "{domain_code}-F01 or null",
      "is_agent_generated": true,
      "kb_source_ref": ["KB-DOC-ID"]
    }}
  ],
  "findings": [
    {{
      "id": "{domain_code}-F01",
      "check_category": "CATEGORY_FROM_LIST_ABOVE",
      "rag_score": 4,
      "rag_label": "GREEN | AMBER | RED",
      "title": "[what is wrong or confirmed] in [specific component/artifact] — ≤140 chars",
      "finding": "Balanced assessment: what the SA addressed well and any specific gap (reference artifact or KB)",
      "description": "2-4 sentences: what was found, in which SA artifact, why it is non-compliant or compliant",
      "evidence_source": "File name or section in SA submission where evidence was reviewed",
      "standard_violated": "Exact standard, policy or principle violated with version — null if GREEN",
      "impact": "Specific risk if unresolved — null if GREEN",
      "recommendation": "1-2 sentences: specific remediation action — null if no action required",
      "is_blocker": false,
      "waiver_eligible": false,
      "artifact_ref": "File name or section in SA submission",
      "kb_ref": "KB document ID or title that defines the standard",
      "principle_id": "EA principle code if applicable, else null",
      "kb_reference": ["KB-DOC-ID"]
    }}
  ],
  "actions": [
    {{
      "id": "{domain_code}-ACT-01",
      "domain": "{domain_code}",
      "action_type": "BLOCKER_RESOLUTION | AMBER_CONDITION | DOCUMENTATION | EVIDENCE_SUBMISSION | WAIVER_APPLICATION | POST_GO_LIVE",
      "title": "Action-verb lead — specific enough to act without reading the finding",
      "action": "Specific, measurable remediation step",
      "proposed_owner": "solution_architect | enterprise_architect | dev_team | security_team",
      "owner_role": "solution_architect | enterprise_architect | dev_team | security_team",
      "proposed_due_date": "BEFORE_ARB | WITHIN_2_WEEKS | WITHIN_30_DAYS | WITHIN_60_DAYS | WITHIN_QUARTER | PRE_GO_LIVE",
      "due_days": 30,
      "priority": "CRITICAL | HIGH | MEDIUM | LOW",
      "verification_method": "How completion will be verified — specific artifact or review step",
      "is_conditional_approval_gate": false,
      "links_to_finding_id": "{domain_code}-F01",
      "links_to_blocker_id": "{domain_code}-BLK-01 or null"
    }}
  ],
  "adrs": [
    {{
      "id": "ADR-{domain_code}-01",
      "domain": "{domain_code}",
      "adr_type": "NEW_DECISION | WAIVER | DEVIATION | RATIFICATION | DEPRECATION",
      "title": "Decision: [verb + specific choice] or Waiver: [specific deviation]",
      "decision": "The chosen option and its key parameters — specific, not vague",
      "rationale": "Why this option was chosen, referencing architecture principles or KB patterns",
      "context": "2-4 sentences: why this decision was needed",
      "consequences": "Both positive outcomes and trade-offs accepted",
      "mitigations": ["Specific mitigation for each risk in consequences"],
      "options_considered": [
        {{"option_label": "A", "description": "Option A description", "pros": ["pro1"], "cons": ["con1"]}},
        {{"option_label": "B", "description": "Option B description", "pros": ["pro1"], "cons": ["con1"]}}
      ],
      "proposed_owner": "Role responsible for implementing this ADR",
      "owner": "Role or team responsible",
      "proposed_target_date": "IMMEDIATE | WITHIN_30_DAYS | WITHIN_QUARTER | NEXT_RELEASE | ONGOING",
      "target_date": "YYYY-MM-DD or null",
      "waiver_expiry_date": "YYYY-MM-DD — REQUIRED when adr_type = WAIVER, else null",
      "links_to_finding_ids": ["{domain_code}-F01"],
      "status": "PROPOSED",
      "kb_references": ["KB-DOC-ID"]
    }}
  ],
  "nfr_scorecard": []
}}

NFR_SCORECARD NOTE: Populate nfr_scorecard[] only when domain = "NFR". Each row:
{{
  "nfr_category": "SCALABILITY_PERFORMANCE | HA_RESILIENCE | SECURITY | DEVSECOPS_QUALITY | ENGINEERING_EXCELLENCE | DR",
  "rag_score": 3,
  "rag_label": "GREEN | AMBER | RED",
  "evidence_provided": ["specific evidence item from SA"],
  "gaps": ["specific gap vs SLO baseline"],
  "mitigating_condition": "What must be done to close the gap — empty string if GREEN",
  "slo_target": "Platform SLO target e.g. P95 < 3s, Four-9s HA",
  "actual_evidenced": "What the SA actually evidenced vs the SLO target",
  "is_mandatory_green": false
}}"""

    # ── Check categories from question_registry ───────────────────────────────

    def _get_check_categories(self, domain_slug: str) -> List[Dict[str, Any]]:
        """Return unique check_category rows for the domain from question_registry.
        Falls back to checklist_subsections if question_registry is not populated.
        """
        tabs = DOMAIN_TO_QR_TABS.get(domain_slug, [domain_slug])
        placeholders = ", ".join(f":tab{i}" for i in range(len(tabs)))
        params = {f"tab{i}": t for i, t in enumerate(tabs)}

        try:
            with self.db.begin_nested():
                rows = self.db.execute(text(f"""
                    SELECT check_category,
                           bool_or(is_mandatory_green) AS is_mandatory_green
                    FROM   question_registry
                    WHERE  frontend_tab IN ({placeholders})
                    AND    is_active = true
                    GROUP  BY check_category
                    ORDER  BY check_category
                """), params).fetchall()

            if rows:
                return [{"category": r[0], "is_mandatory_green": bool(r[1])} for r in rows]
        except Exception as exc:
            logger.warning(f"[DOMAIN-AGENT] question_registry query failed ({exc}), using subsections fallback")

        # Fallback: checklist_subsections (existing Python metadata tables)
        try:
            from app.db.metadata_models import Domain, ChecklistSubsection, ChecklistQuestion
            domain_obj = self.db.query(Domain).filter(Domain.slug == domain_slug).first()
            if not domain_obj:
                return []
            subsections = (
                self.db.query(ChecklistSubsection)
                .filter(ChecklistSubsection.domain_id == domain_obj.id, ChecklistSubsection.is_active == True)
                .order_by(ChecklistSubsection.sort_order)
                .all()
            )
            result = []
            for sub in subsections:
                has_required = (
                    self.db.query(ChecklistQuestion)
                    .filter(ChecklistQuestion.subsection_id == sub.id, ChecklistQuestion.is_required == True)
                    .count() > 0
                )
                result.append({"category": sub.name, "is_mandatory_green": has_required})
            return result
        except Exception as exc2:
            logger.warning(f"[DOMAIN-AGENT] subsections fallback also failed ({exc2})")
            return []

    # ── NFR criteria block (nfr domain only) ─────────────────────────────────

    def _build_nfr_criteria_block(self, review: Optional[Review]) -> str:
        if not review or not review.report_json:
            return ""
        rows = (review.report_json.get("form_data") or {}).get("nfr_criteria", [])
        if not rows:
            return "== NFR QUANTITATIVE CRITERIA — none provided by SA =="
        lines = [
            f"== NFR QUANTITATIVE CRITERIA ({len(rows)} rows) ==",
            "Use these to calibrate SCALABILITY_PERFORMANCE and HA_RESILIENCE scores.",
            "",
            "Category           | Criteria              | Target      | Actual       | Score | Evidence",
            "-------------------|----------------------|-------------|--------------|-------|----------",
        ]
        for r in rows:
            lines.append(" | ".join([
                str(r.get("category",     "")).ljust(18),
                str(r.get("criteria",     "")).ljust(21),
                str(r.get("target_value", "")).ljust(11),
                str(r.get("actual_value", "")).ljust(12),
                str(r.get("score",        "?")).ljust(5),
                str(r.get("evidence",     "(none)")),
            ]))
        return "\n".join(lines)
