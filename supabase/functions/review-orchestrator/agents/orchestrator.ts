import { DomainResult, Finding } from './domain-agent.ts'
import { callLLM, parseJsonFromLLM } from '../utils/llm.ts'
import { runSynthesis } from './synthesis.ts'
import {
  buildDomainContext,
  buildSolutionContextBlock,
  buildArtefactBlock,
  buildNfrCriteriaBlock,
  getKnowledgeBaseContent,
  getKbCategoriesForAgent,
  getRegistryForAgent,
  extractCheckCategories,
} from './context-builder.ts'
import type { SupabaseClient } from 'https://esm.sh/@supabase/supabase-js@2'

// ── Domain metadata ───────────────────────────────────────────────────────────

const DOMAIN_LABEL: Record<string, string> = {
  solution:     'Solution',
  business:     'Business Domain',
  application:  'Application Domain',
  software:     'Software Architecture',
  integration:  'Integration Domain',
  api:          'API Design & Standards',
  security:     'Security Domain',
  data:         'Data Domain',
  infra:        'Infrastructure & Platform',
  devsecops:    'DevSecOps Domain',
  engg_quality: 'Engineering Excellence',
  nfr:          'Non-Functional Requirements',
}

const DOMAIN_CODE: Record<string, string> = {
  solution:     'SOL',
  business:     'BUS',
  application:  'APP',
  software:     'SFT',
  integration:  'INT',
  api:          'API',
  security:     'SEC',
  data:         'DAT',
  infra:        'INF',
  devsecops:    'DSO',
  engg_quality: 'ENG',
  nfr:          'NFR',
}

// ── Interfaces ────────────────────────────────────────────────────────────────

export interface ReviewInput {
  review: any
  reportJson: any
  artifactText: string
  supabase: SupabaseClient
  scopeTags: string[]
}

export interface DomainAdr {
  id: string
  adr_type: 'NEW_DECISION' | 'WAIVER' | 'DEVIATION' | 'RATIFICATION' | 'DEPRECATION'
  decision: string
  rationale: string
  context?: string
  owner: string
  target_date: string | null
  waiver_expiry_date?: string | null
  status?: string
}

export interface DomainAction {
  id: string
  finding_ref: string
  action: string
  owner_role: string
  due_days: number
  priority: 'HIGH' | 'MEDIUM' | 'LOW'
}

export interface ReviewResult {
  decision: 'approve' | 'approve_with_conditions' | 'defer' | 'reject'
  aggregateScore: number
  aggregateRagLabel: string
  domainScores: Record<string, number>
  domainSummaries: Record<string, any>
  findings: Finding[]
  blockers: any[]
  adrs: DomainAdr[]
  actions: DomainAction[]
  recommendations: any[]
  nfrScorecard: any[]
  kbSourcesCited: string[]
  fullReport: any
  tokensUsed: number
  rawResponse: string
  executiveRationale: string
  scoreCorrections: any[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function ragScoreToSeverity(ragScore: number): 'BLOCKER' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO' {
  if (ragScore <= 1) return 'BLOCKER'
  if (ragScore <= 2) return 'HIGH'
  if (ragScore === 3) return 'MEDIUM'
  if (ragScore === 4) return 'LOW'
  return 'INFO'
}

function scoreToRagLabel(score: number): string {
  if (score >= 4) return 'green'
  if (score === 3) return 'amber'
  return 'red'
}

// ── Orchestrator ──────────────────────────────────────────────────────────────

// Delay between sequential domain LLM calls — stays within 15 RPM free-tier limit.
const INTER_DOMAIN_DELAY_S = 0.5

// One retry on transient LLM errors (503, timeout, etc.), 10 s delay.
// Retry (attempt 2) reduces KB + artefact content by 25% to stay under token limits.
const LLM_CONTENT_SCALE_ON_SECOND_RETRY = 0.75

export class OrchestratorAgent {
  async validateReview(input: ReviewInput): Promise<ReviewResult> {
    const { review, reportJson, artifactText, supabase, scopeTags } = input

    console.log(`Orchestrator: Starting validation for review ${review.id}`)
    console.log(`Scope tags: ${scopeTags.join(', ')}`)

    const agentDomainMap: Record<string, string[]> = {
      solution:       ['solution'],
      business:       ['business'],
      application:    ['application'],
      integration:    ['integration'],
      data:           ['data'],
      infrastructure: ['infra', 'security'],
      devsecops:      ['devsecops', 'engg_quality'],
      nfr:            ['nfr'],
    }

    const uniqueDomains = [...new Set(
      scopeTags.flatMap(tag => agentDomainMap[tag] ?? [tag])
    )]
    console.log(`Processing domains: ${uniqueDomains.join(', ')}`)

    const domainResults:      DomainResult[] = []
    const allFindings:        Finding[]      = []
    const allBlockers:        any[]          = []
    const allAdrs:            DomainAdr[]    = []
    const allActions:         DomainAction[] = []
    const allRecommendations: any[]          = []
    const allNfrScorecard:    any[]          = []
    const domainSummaries:    Record<string, any> = {}
    const kbSourcesCited:     string[]       = []
    let totalTokensUsed = 0

    for (const agentDomain of uniqueDomains) {
      console.log(`\n=== Processing domain: ${agentDomain} ===`)

      const domainResult = await this._processDomainWithRetry(
        review, reportJson, artifactText, supabase, agentDomain
      )

      totalTokensUsed += domainResult.tokensUsed
      allFindings.push(...domainResult.findings)
      allBlockers.push(...domainResult.blockers)
      allAdrs.push(...domainResult.adrs)
      allActions.push(...domainResult.actions)
      allRecommendations.push(...domainResult.recommendations)
      if (domainResult.nfrScorecard.length > 0) allNfrScorecard.push(...domainResult.nfrScorecard)
      if (domainResult.kbRefs.length > 0) kbSourcesCited.push(...domainResult.kbRefs)

      domainSummaries[agentDomain] = domainResult.domainSummary
      domainResults.push({
        domain:   agentDomain,
        score:    domainResult.score,
        findings: domainResult.findings,
      })

      if (agentDomain !== uniqueDomains[uniqueDomains.length - 1]) {
        await new Promise(r => setTimeout(r, INTER_DOMAIN_DELAY_S * 1000))
      }
    }

    // ── Aggregate (spec: MIN, not mean; security/DR blocker overrides to 1) ──

    const domainScores: Record<string, number> = {}
    for (const r of domainResults) domainScores[r.domain] = r.score

    const scores = Object.values(domainScores)
    let aggregateScore = scores.length > 0 ? Math.min(...scores) : 3
    const hasSecurityDrBlocker = allBlockers.some(b => b.is_security_or_dr)
    if (hasSecurityDrBlocker) aggregateScore = 1

    // ── Tier 2: Synthesis LLM call ────────────────────────────────────────────
    // Runs after all domain agents. Rationalises cross-domain scores, gates ADRs,
    // writes executive rationale. Honoured only within Tier-1 floors.
    const synthesisModel = review.llm_model || Deno.env.get('GEMINI_MODEL') || 'gemini-2.5-flash-lite'
    const synthesisResult = await runSynthesis({
      reviewId:       review.id,
      solutionName:   review.solution_name ?? '',
      domainScores,
      allFindings,
      allBlockers,
      allAdrs,
      allActions,
      aggregateScore,
      model:          synthesisModel,
      supabase,
    })
    totalTokensUsed += synthesisResult.tokensUsed

    // Apply synthesis score corrections to domainScores (only for domains that actually ran)
    for (const [domain, score] of Object.entries(synthesisResult.finalDomainScores)) {
      if (!(domain in domainScores)) {
        console.warn(`[ORCHESTRATOR] Ignoring score for unknown domain '${domain}' from synthesis`)
        continue
      }
      domainScores[domain] = score
    }

    // Recompute aggregate after synthesis corrections (Tier-1 floors still apply)
    const finalScores = Object.values(domainScores)
    aggregateScore = finalScores.length > 0 ? Math.min(...finalScores) : aggregateScore
    if (hasSecurityDrBlocker) aggregateScore = 1

    // Filter ADRs through synthesis gate
    const filteredAdrs = allAdrs.filter(a => synthesisResult.filteredAdrIds.includes(a.id))

    // Filter blockers through synthesis consolidation (deduplicate cross-domain duplicates)
    const retainSet = synthesisResult.retainBlockerIds
      ? new Set(synthesisResult.retainBlockerIds)
      : null
    const consolidatedBlockers = retainSet
      ? allBlockers.filter(b => retainSet.has(b.id))
      : allBlockers

    // Filter findings through synthesis deduplication (suppress cross-domain duplicates)
    const dupFindingIds = new Set(synthesisResult.duplicateFindingIds ?? [])
    const findingsBeforeDedup = allFindings.length
    const deduplicatedFindings = dupFindingIds.size > 0
      ? allFindings.filter(f => !dupFindingIds.has(f.finding_id ?? f.id))
      : allFindings
    if (dupFindingIds.size > 0) {
      console.log(`[ORCHESTRATOR] Suppressed ${findingsBeforeDedup - deduplicatedFindings.length} duplicate finding(s): ${[...dupFindingIds].join(', ')}`)
    }

    const aggregateRagLabel = scoreToRagLabel(aggregateScore)
    const decision = this.determineDecision(aggregateScore, consolidatedBlockers)

    console.log(`\n=== Aggregate Results (post-synthesis) ===`)
    console.log(`Decision: ${decision}, Agg score: ${aggregateScore} (${aggregateRagLabel}), Blockers: ${consolidatedBlockers.length} (raw: ${allBlockers.length})`)
    console.log(`Findings: ${deduplicatedFindings.length} (raw: ${findingsBeforeDedup}), Actions: ${allActions.length}, ADRs: ${filteredAdrs.length}/${allAdrs.length} (synthesis-gated), Tokens: ${totalTokensUsed}`)
    console.log(`Score corrections: ${synthesisResult.scoreCorrections.length}, Removed ADRs: ${synthesisResult.removedAdrIds.length}, Dropped duplicate blockers: ${allBlockers.length - consolidatedBlockers.length}, Suppressed duplicate findings: ${dupFindingIds.size}`)

    const fullReport = {
      ...(reportJson ?? {}),
      ai_review: {
        decision,
        recommended_decision:  decision,
        aggregate_score:       aggregateScore,
        aggregate_rag_label:   aggregateRagLabel,
        domain_scores:         domainScores,
        domain_summaries:      domainSummaries,
        findings:              deduplicatedFindings,
        blockers:              consolidatedBlockers,
        recommendations:       allRecommendations,
        actions:               allActions,
        adrs:                  filteredAdrs,
        nfr_scorecard:         allNfrScorecard,
        kb_sources_cited:      [...new Set(kbSourcesCited)],
        executive_rationale:   synthesisResult.executiveRationale,
        score_corrections:     synthesisResult.scoreCorrections,
        removed_adr_ids:       synthesisResult.removedAdrIds,
        duplicate_finding_ids: synthesisResult.duplicateFindingIds,
        processed_at:          new Date().toISOString(),
      },
      // Add domain_payloads to match Python backend structure
      domain_payloads: domainResults.map(dr => ({
        domain: dr.domain,
        session_id: review.id,
        summary: domainSummaries[dr.domain],
        findings: dr.findings,
        blockers: allBlockers.filter(b => b.domain === dr.domain),
        recommendations: allRecommendations.filter(r => r.domain === dr.domain),
        actions: allActions,
        adrs: allAdrs,
        nfr_scorecard: dr.domain === 'nfr' ? allNfrScorecard.filter(n => n.nfr_category && n.nfr_category.includes('_')) : [],
      })),
      decision,
      aggregate_score:        aggregateScore,
      aggregate_rag_label:    aggregateRagLabel,
      recommended_decision:   decision,
      domain_scores:          domainScores,
      domain_summaries:       domainSummaries,
      findings:               deduplicatedFindings,
      blockers:               consolidatedBlockers,
      recommendations:        allRecommendations,
      actions:                allActions,
      adrs:                   filteredAdrs,
      nfr_scorecard:          allNfrScorecard,
      kb_sources_cited:       [...new Set(kbSourcesCited)],
      total_tokens_used:      totalTokensUsed,
      processing_time_seconds: totalTokensUsed > 0 ? 0 : 0,
      domains_evaluated:      uniqueDomains,
    }

    return {
      decision,
      aggregateScore,
      aggregateRagLabel,
      domainScores,
      domainSummaries,
      findings:           deduplicatedFindings,
      blockers:           consolidatedBlockers,
      adrs:               filteredAdrs,
      actions:            allActions,
      recommendations:    allRecommendations,
      nfrScorecard:       allNfrScorecard,
      kbSourcesCited:     [...new Set(kbSourcesCited)],
      fullReport,
      tokensUsed:         totalTokensUsed,
      rawResponse:        JSON.stringify(fullReport.ai_review),
      executiveRationale: synthesisResult.executiveRationale,
      scoreCorrections:   synthesisResult.scoreCorrections,
    }
  }

  // ── System prompt (spec: role + rules + scoring) ──────────────────────────

  private async _getDbSystemPrompt(supabase: any, domainLabel: string, agentDomain: string): Promise<string | null> {
    // Check domain-specific key first, then generic fallback
    const keys = agentDomain ? [`domain.system.${agentDomain}`, 'domain.system'] : ['domain.system']
    for (const key of keys) {
      try {
        const { data } = await supabase
          .from('prompt_templates')
          .select('content')
          .eq('prompt_key', key)
          .eq('is_active', true)
          .order('version', { ascending: false })
          .limit(1)
          .single()
        if (data?.content) {
          return data.content
            .replace(/\{domain_label\}/g, domainLabel)
            .replace(/\{domain_slug\}/g, agentDomain)
        }
      } catch {
        // key not found — try next
      }
    }
    return null
  }

  private buildDomainSystemPrompt(domainLabel: string, agentDomain: string = ''): string {
    const solutionExtra = agentDomain === 'solution' ? `

SOLUTION DOMAIN — SPECIALIST GUIDANCE:
As the Solution reviewer your primary responsibility is to assess whether this submission is
problem-driven, well-defined, and strategically aligned — not just technically complete.

SCOPE BOUNDARY FOR SOLUTION DOMAIN:
This domain covers STRATEGIC ALIGNMENT only — problem quality, solution fit, business outcomes,
stakeholder alignment, and strategic context. Do NOT generate security or DR/HA blockers from
this domain. Any is_security_or_dr field in your blockers[] must always be false. If you find
security or DR risks in RAID logs or artefacts, note them in recommendations[], not blockers[].

KEY ASSESSMENT AREAS (generate a finding for each, even if artefacts are absent):
- PROBLEM_STATEMENT_QUALITY: Search BOTH the form-provided fields AND all submitted artefacts
  for problem statement content before scoring — it may exist in uploaded documents even if the
  form field is empty.
  • Absent from BOTH form AND all submitted artefacts → rag_score 2 (RED, significant gap; NOT a blocker)
  • Present but vague/generic, no measurable impact stated → rag_score 2–3
  • Clear, specific, measurable, customer-grounded → rag_score 4–5
- SOLUTION_FIT: Does the proposed solution directly address the root cause of the stated problem?
  Assess alignment between the problem description and the architectural approach in the artefacts.
- BUSINESS_OUTCOMES: Are target outcomes Specific, Measurable, Achievable, Relevant, Time-bound?
  Generic outcomes ("improve performance") without metrics → rag_score 2–3.
  SMART outcomes with measurable KPIs and timelines → rag_score 4–5.
- STAKEHOLDER_ALIGNMENT: Are key stakeholders identified with clear ownership and accountability?
- STRATEGIC_FIT: Does the solution align with the stated enterprise business drivers?

WEIGHTING — PROBLEM STATEMENT:
The problem statement quality carries significant weight in the overall domain score.
A solution with strong technical artefacts but a vague or absent problem statement should score
no higher than rag_score 3 (AMBER) overall.
A well-framed problem with SMART outcomes and demonstrated solution-fit warrants rag_score 4–5.

OUTPUT ADDITION — include "project_context" as the first key in your JSON response:
{
  "project_context": {
    "problem_statement_assessed": "Brief restatement of the SA's problem as you understood it",
    "problem_statement_quality": "clear | vague | absent",
    "outcomes_measurability": "measurable | partial | not_measurable | absent",
    "solution_fit_assessment": "One sentence: how well the solution addresses the stated problem"
  }
}` : ''

    return `You are a senior ${domainLabel} architect acting as a specialist reviewer in the Pre-ARB AI Agent pipeline.
Your role is to conduct a thorough, proportionate review of the Solution Architect's submission against
enterprise architecture standards — producing a balanced assessment that reflects real-world ARB practice.

ARB SCOPE — DESIGN, ARCHITECTURE, AND PLANNING ONLY:
This review covers the quality and completeness of the architectural design, not operational readiness.
The ARB's purpose is to verify the solution has sufficient architectural inputs for a development team
to build, deploy, and test it — not to confirm that building, deployment, or testing has occurred.
Score based on whether the DESIGN is sound and complete enough to proceed, not whether the solution
has been built, tested, or is live.

RULES:
1. Respond ONLY with a valid JSON object matching DomainReviewPayload schema.
   No preamble, no markdown, no explanation outside the JSON.

2. Every finding MUST reference a specific SA artifact section OR a relevant KB document.
   Focus on material gaps affecting architecture quality, security, or operability.
   When the SA has addressed a requirement with reasonable evidence (even if not in the prescribed format),
   credit it and note the finding as GREEN or AMBER rather than inventing a gap.

3. RAG scoring — calibrate against architectural completeness, not operational readiness:
   • rag_score 1 (BLOCKER): Fundamental architectural flaw, or mandatory design domain entirely absent
     with no documented mitigation — unmitigated security architecture risk, no HA/DR design at all.
     → Add to blockers[]. blockers[] ONLY contains rag_score 1 findings. NEVER add rag_score 2 or higher to blockers[].
   • rag_score 2 (RED): Significant design gap — mandatory architectural artefact absent or approach
     conflicts with EA standards. Design must be revised before development can proceed.
     → Add to findings[] with a HIGH priority action. NEVER add to blockers[].
   • rag_score 3 (AMBER): Architectural approach documented but lacks sufficient detail in specific areas;
     a credible, time-bound plan to complete the design before development begins is present.
     → Add to findings[] with a MEDIUM priority action.
   • rag_score 4 (GREEN+): Architecture well-specified; only minor documentation gaps that do not block
     development, deployment, or testing.
   • rag_score 5 (GREEN): Comprehensive design — all mandatory artefacts present, approach fully aligned
     with EA standards, sufficient detail for a development team to build, deploy, and test without
     further architectural clarification.
   Reserve rag_score 1 ONLY for genuinely unmitigable security/architecture blockers. Prefer RED (2) for
   significant gaps, AMBER (3) for non-critical gaps. Use rag_score 4 liberally when the SA has done
   solid design work with minor loose ends.

4. Every finding with rag_score <= 3 (AMBER or RED) MUST have at least one Action in actions[].

5. Generate ADRs only for genuine architectural choices that require a formal recorded decision:
   MANDATORY — generate an ADR for each of these:
   - Architectural patterns that differ materially from the EA standard approach → adr_type: NEW_DECISION
   - Technology or vendor choices that deviate from EA standards → adr_type: NEW_DECISION
   - An explicit design decision to accept a known architectural risk → adr_type: WAIVER
   APPLY THE ARCHITECTURAL-CHOICE TEST before generating any ADR:
     Ask: "Does this finding involve a deliberate architectural choice — a decision between options that
     needs to be recorded and defended?" If yes → ADR. If no → action item only.
   Examples that ARE ADRs: adopt event-driven messaging over REST for async flows; retain a legacy
     component pending migration; accept non-standard RBAC model with compensating controls.
   Examples that are NOT ADRs: missing VAPT plan (action: produce the plan); absent DR test plan
     (action: produce the plan); incomplete diagram (action: update documentation).
   OPTIONAL (generate only if clearly applicable):
   - Notable AMBER design decisions that set a precedent or need tracking → adr_type: DECISION
   Do NOT generate ADRs for missing documentation, incomplete artefacts, or straightforward remediation.
   adrs[] may be empty when all findings relate to missing design documents rather than architectural choices.

6. ADRs of type WAIVER must include a proposed waiver_expiry_date (ISO date string).

7. summary.rag_score reflects overall domain readiness — calibrate against the finding distribution:
   - Mostly GREEN (4–5) with 1–2 minor AMBERs → summary GREEN (4)
   - Mix of GREEN and AMBER, no blockers → summary AMBER (3)
   - Any rag_score=2 finding OR multiple AMBERs without mitigations → summary RED (2)
   - Any blocker (rag_score=1) → summary RED (1)
   The summary should represent what an ARB panel would conclude about this domain's readiness.

8. ARB SCOPE BOUNDARY — defines what counts as valid architectural evidence:

   IN SCOPE — ARCHITECTURE DESIGN artefacts (rag_score 1–2 eligible; security domain may blocker):
   • Architecture diagrams, design documents, ADRs, threat models, RBAC design
   • Encryption-at-rest and in-transit design  (NOT operational key-management evidence)
   • Network security architecture and zone design
   • HA/failover design — mechanism, RTO/RPO targets defined in architecture  (NOT failover test results)
   • Observability design — what will be monitored, alerting approach  (NOT live metrics or dashboards)
   • Capacity model / sizing approach  (NOT measured throughput, benchmark, or load-test results)
   • CI/CD pipeline design with security tooling integration approach  (NOT SAST/DAST scan results)
   • IaC templates or deployment design  (NOT evidence of a deployed or running environment)

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
   - Evidence addressing the INTENT of a requirement in an alternate format: credit appropriately.

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
4 = Sound design — architecture well-specified; only minor documentation gaps that do not block development
3 = Adequate design — architectural approach documented but lacking sufficient detail in specific areas;
    a credible, time-bound plan to complete the design before development begins is present
2 = Design gap — mandatory architectural artefact absent OR approach conflicts with EA standards;
    design must be revised before development can proceed
1 = Critical design failure — fundamental architectural flaw OR mandatory design domain entirely absent
    with no documented mitigation (BLOCKER)${solutionExtra}`
  }

  // ── User prompt (spec: session + KB + artifacts + checklist + ID seed + categories + schema) ──

  private buildDomainUserPrompt(opts: {
    sessionId:        string
    reportJson:       any
    domainCode:       string
    agentDomain:      string
    kbContext:        string
    checklistContext: string
    artefactContext:  string
    nfrContext:       string
    checkCategories:  Array<{ category: string; isMandatoryGreen: boolean }>
  }): string {
    const {
      sessionId, reportJson, domainCode, agentDomain,
      kbContext, checklistContext, artefactContext, nfrContext, checkCategories,
    } = opts

    const fd           = reportJson?.form_data ?? {}
    const solutionName = fd.solution_name ?? fd.project_name ?? '(not provided)'
    const reviewDate   = new Date().toISOString()

    // For Solution domain: dedicated project info block; for others: standard context block
    const solutionContext = agentDomain === 'solution'
      ? (() => {
          const problem   = fd.problem_statement ?? '(not provided)'
          const drivers   = (fd.business_drivers ?? []).join('; ') || '(not provided)'
          const stk       = (fd.stakeholders ?? []).join(', ') || '(not provided)'
          const outcomes  = fd.target_business_outcomes ?? fd.growth_plans ?? '(not provided)'
          return `== PROJECT INFORMATION (PRIMARY ASSESSMENT CONTEXT) ==
Solution Name:            ${solutionName}
Problem Statement:        ${problem}
Business Drivers:         ${drivers}
Stakeholders:             ${stk}
Target Business Outcomes: ${outcomes}

ASSESSMENT INSTRUCTIONS:
1. Assess QUALITY of the problem statement — not just presence. A strong problem statement identifies
   the customer/stakeholder, describes the pain or opportunity, quantifies impact, and is specific
   enough to evaluate solution-fit.
2. Assess whether target outcomes are SMART (Specific, Measurable, Achievable, Relevant, Time-bound).
3. Assess solution-fit: does the architectural approach in the artefacts directly address the problem?
4. Generate PROBLEM_STATEMENT_QUALITY and BUSINESS_OUTCOMES findings regardless of other coverage.`
        })()
      : buildSolutionContextBlock(reportJson)

    // Mandatory check categories block
    const categoriesBlock = checkCategories.length > 0
      ? checkCategories
          .map(c => c.isMandatoryGreen
            ? `  [MANDATORY-GREEN] ${c.category}  ← non_compliant = BLOCKER (check artifact evidence first)`
            : `  ${c.category}`)
          .join('\n')
      : '  (no categories registered for this domain — use check_category from the checklist below)'

    // NFR block appended to artefact section if present
    const artefactSection = nfrContext
      ? `${artefactContext}\n\n${nfrContext}`
      : artefactContext

    return `== REVIEW SESSION ==
session_id: ${sessionId}
solution_name: ${solutionName}
domain_under_review: ${domainCode}
review_date: ${reviewDate}

${solutionContext}

== KNOWLEDGE BASE CONTEXT (retrieved for this domain) ==
${kbContext || '(No knowledge base entries are loaded for this domain. Flag findings based on absence of KB evidence.)'}

== SA SUBMITTED ARTIFACTS ==
${artefactSection}

== SA CHECKLIST ANSWERS & EVIDENCE ==
${checklistContext}

== ID SEED ==
finding_id_start:        ${domainCode}-F01
blocker_id_start:        ${domainCode}-BLK-01
recommendation_id_start: ${domainCode}-REC-01
action_id_start:         ${domainCode}-ACT-01
adr_id_start:            ADR-${domainCode}-01
Use these as starting IDs, incrementing sequentially (F01, F02, F03 …).

== MANDATORY CHECK CATEGORIES FOR THIS DOMAIN ==
Assess each category against ARCHITECTURAL COMPLETENESS — design quality and planning adequacy.
Do NOT penalise absence of test results, runbooks, operational metrics, or deployed-state evidence;
these are outside ARB scope. Penalise absence of the design, plan, or architectural approach itself.
  - Fully compliant area → GREEN finding (rag_score 4–5) briefly acknowledging coverage is correct output.
  - Partial compliance or minor gap → AMBER finding (rag_score 3) in findings[] with a time-bound action.
  - Significant design gap → RED finding (rag_score 2) in findings[] with a HIGH priority action. NEVER in blockers[].
  - Unmitigable architecture blocker → rag_score 1 in blockers[] AND findings[]. Only use when approval is truly impossible without resolution.
Do not manufacture concerns for well-addressed areas. Do not skip any listed category.
Categories marked [MANDATORY-GREEN] require rag_score = 1 if the SA answer is non_compliant
(check artifact evidence first — adequate mitigating design evidence can raise this to rag_score 2).

${categoriesBlock}

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
${agentDomain === 'solution' ? `
Include "project_context" as the first key (Solution domain only):
  "project_context": {
    "problem_statement_assessed": "Brief restatement of the SA's problem as you understood it",
    "problem_statement_quality": "clear | vague | absent",
    "outcomes_measurability": "measurable | partial | not_measurable | absent",
    "solution_fit_assessment": "One sentence: how well the solution addresses the stated problem"
  },
` : ''}
{
  "domain": "${domainCode}",
  "session_id": "${sessionId}",
  "summary": {
    "rag_score": 3,
    "rag_label": "GREEN | AMBER | RED",
    "overall_readiness": "APPROVE | APPROVE_WITH_CONDITIONS | DEFER | REJECT",
    "rationale": "One-sentence justification for the domain rag_score",
    "executive_summary": "3-5 sentences covering: current state, key strengths, critical gaps, ARB readiness",
    "compliant_areas": ["area1 — references specific standard or pattern", "area2"],
    "gap_areas": ["${domainCode}-F01: Short gap description", "${domainCode}-F02: ..."],
    "total_findings": 0,
    "blocker_count": 0,
    "action_count": 0,
    "adr_count": 0,
    "mandatory_gaps": 0,
    "evidence_quality": "COMPLETE | PARTIAL | INSUFFICIENT | ABSENT",
    "domain_specific_scores": { "sub_area_name": 4 },
    "kb_references": ["KB doc title or ID cited"]
  },
  "blockers": [
    {
      "id": "${domainCode}-BLK-01",
      "domain": "${domainCode}",
      "title": "Short blocker title",
      "description": "Precise description of the blocking issue",
      "violated_standard": "Which EA standard or policy is violated",
      "impact": "Business or technical impact if not resolved",
      "resolution_required": "Specific action that must be completed before approval",
      "links_to_finding_id": "${domainCode}-F01",
      "is_security_or_dr": false,
      // Set true ONLY for blockers that are security architecture gaps OR HA/DR design gaps.
      // Platform/infra operational blockers (missing runbook, capacity config) must remain false.
      "status": "OPEN",
      "kb_evidence_ref": ["KB doc title"]
    }
  ],
  "recommendations": [
    {
      "id": "${domainCode}-REC-01",
      "domain": "${domainCode}",
      "priority": "CRITICAL | HIGH | MEDIUM | LOW",
      "title": "Action-verb lead: Implement X for Y — specific to this solution",
      "rationale": "Why this recommendation applies to this specific solution (1-2 sentences)",
      "approved_pattern_ref": "Pattern or standard name and version from KB",
      "benefit": "Specific measurable or verifiable benefit",
      "implementation_hint": "Optional: concrete first step for the SA",
      "applies_to_finding_id": "${domainCode}-F01 or null",
      "is_agent_generated": true,
      "kb_source_ref": ["KB doc title"]
    }
  ],
  "findings": [
    {
      "id": "${domainCode}-F01",
      "check_category": "CATEGORY_FROM_LIST_ABOVE",
      "rag_score": 4,
      "rag_label": "GREEN | AMBER | RED",
      "title": "[what is wrong or confirmed] in [specific component/artifact] — ≤140 chars",
      "finding": "Balanced assessment: what the SA addressed well and any specific gap (reference artifact or KB)",
      "description": "2-4 sentences: what was found, in which SA artifact, why it is non-compliant or compliant",
      "recommendation": "1-2 sentences: specific remediation action — null if no action required",
      "evidence_source": "File name or section in SA submission where evidence was reviewed",
      "standard_violated": "Exact standard, policy or principle violated with version — null if GREEN",
      "impact": "Specific risk if unresolved — null if GREEN",
      "is_blocker": false,
      "waiver_eligible": false,
      "links_to_action_ids": ["${domainCode}-ACT-01"],
      "links_to_adr_id": null,
      "artifact_ref": "File name or section in SA submission",
      "kb_ref": "KB document ID or title that defines the standard",
      "principle_id": "EA principle code if applicable, else null",
      "kb_reference": ["KB doc title"]
    }
  ],
  "actions": [
    {
      "id": "${domainCode}-ACT-01",
      "domain": "${domainCode}",
      "action_type": "BLOCKER_RESOLUTION | AMBER_CONDITION | DOCUMENTATION | EVIDENCE_SUBMISSION | WAIVER_APPLICATION | POST_GO_LIVE",
      "title": "Action-verb lead — specific enough to act without reading the finding",
      "finding_ref": "${domainCode}-F01",
      "action": "Specific, measurable remediation step",
      "owner_role": "solution_architect | enterprise_architect | dev_team | security_team",
      "proposed_owner": "solution_architect",
      "due_days": 30,
      "proposed_due_date": "BEFORE_ARB | WITHIN_2_WEEKS | WITHIN_30_DAYS | WITHIN_60_DAYS | WITHIN_QUARTER | PRE_GO_LIVE",
      "priority": "HIGH | MEDIUM | LOW",
      "verification_method": "How completion will be verified — specific artifact or review step",
      "is_conditional_approval_gate": false,
      "links_to_finding_id": "${domainCode}-F01",
      "links_to_blocker_id": null
    }
  ],
  "adrs": [
    {
      "id": "ADR-${domainCode}-01",
      "domain": "${domainCode}",
      "adr_type": "NEW_DECISION | WAIVER | DEVIATION | RATIFICATION | DEPRECATION",
      "title": "Decision: [verb + specific choice] or Waiver: [specific deviation]",
      "decision": "The chosen option and its key parameters — specific, not vague",
      "rationale": "Why this option was chosen, referencing architecture principles or KB patterns",
      "context": "2-4 sentences: why this decision was needed",
      "consequences": "Both positive outcomes and trade-offs accepted",
      "options_considered": [
        {"option_label": "A", "description": "Option A description", "pros": ["pro1"], "cons": ["con1"]},
        {"option_label": "B", "description": "Option B description", "pros": ["pro1"], "cons": ["con1"]}
      ],
      "mitigations": ["Specific mitigation for each risk in consequences"],
      "owner": "Role or team responsible",
      "proposed_owner": "Role responsible for implementing this ADR",
      "target_date": "YYYY-MM-DD or null",
      "proposed_target_date": "IMMEDIATE | WITHIN_30_DAYS | WITHIN_QUARTER | NEXT_RELEASE | ONGOING",
      "waiver_expiry_date": "YYYY-MM-DD — REQUIRED when adr_type = WAIVER, else null",
      "links_to_finding_ids": ["${domainCode}-F01"],
      "links_to_action_ids": [],
      "status": "PROPOSED",
      "kb_references": ["KB doc title"]
    }
  ]${agentDomain === 'nfr' ? `,
  "nfr_scorecard": [
    {
      "nfr_category": "SCALABILITY_PERFORMANCE | HA_RESILIENCE | SECURITY | DEVSECOPS_QUALITY | ENGINEERING_EXCELLENCE | DR",
      "rag_score": 3,
      "rag_label": "GREEN | AMBER | RED",
      "evidence_provided": ["evidence item"],
      "gaps": ["gap description"],
      "slo_target": "e.g. 99.9% availability",
      "actual_evidenced": "What the SA evidenced",
      "is_mandatory_green": false
    }
  ]` : ''}
}`
  }

  // ── Retry wrapper (matches Python implementation) ───────────────────────────

  private async _processDomainWithRetry(
    review: any,
    reportJson: any,
    artifactText: string,
    supabase: any,
    agentDomain: string
  ): Promise<{
    score: number
    domainSummary: any
    findings: Finding[]
    blockers: any[]
    adrs: DomainAdr[]
    actions: DomainAction[]
    recommendations: any[]
    nfrScorecard: any[]
    kbRefs: string[]
    tokensUsed: number
  }> {
    const domainCode = DOMAIN_CODE[agentDomain] ?? agentDomain.toUpperCase()
    const domainLabel = DOMAIN_LABEL[agentDomain] ?? agentDomain

    const delays = [0, 10] // 2 total attempts, 10s delay on retry
    let lastErr: Error = new Error('no attempts made')

    for (let attempt = 1; attempt <= delays.length; attempt++) {
      const delay = delays[attempt - 1]
      const contentScale = attempt === 2 ? LLM_CONTENT_SCALE_ON_SECOND_RETRY : 1.0

      if (delay > 0) {
        console.warn(`[ORCHESTRATOR] ${agentDomain} attempt ${attempt} — retrying in ${delay}s after: ${lastErr.message}`)
        await new Promise(r => setTimeout(r, delay * 1000))
      }

      if (contentScale < 1.0) {
        console.log(`[ORCHESTRATOR] ${agentDomain} attempt ${attempt} — reducing KB/artefact content to ${Math.round(contentScale * 100)}%`)
      }

      try {
        // 1. Checklist + evidence enriched by question_registry
        const checklistContext = await buildDomainContext(supabase, reportJson, agentDomain)

        // 2. Check categories for mandatory coverage instruction
        const registry = await getRegistryForAgent(supabase, agentDomain)
        const checkCategories = extractCheckCategories(registry)

        // 3. Artefact block — with content scaling on retry
        const artefactBlock = buildArtefactBlock(reportJson, agentDomain)
        const artefactContext = artefactBlock.includes('none available') && artifactText
          ? `== PARSED ARTEFACT (raw extraction) ==\n${artifactText.slice(0, Math.floor(8000 * contentScale))}`
          : artefactBlock

        // 4. NFR quantitative criteria (nfr domain only)
        const nfrContext = agentDomain === 'nfr' ? buildNfrCriteriaBlock(reportJson) : ''

        // 5. Knowledge-base RAG context — with scaled limits (matches Python: 8 domain + 4 general)
        const kbCategories = getKbCategoriesForAgent(agentDomain)
        const kbDomLimit = Math.max(1, Math.floor(8 * contentScale))
        const kbGenLimit = Math.max(1, Math.floor(4 * contentScale))
        const kbContext = await getKnowledgeBaseContent(supabase, kbCategories, undefined, kbDomLimit + kbGenLimit)

        // 6. Build prompts — DB-managed prompt takes precedence if a super_admin has configured one
        const dbPrompt = await this._getDbSystemPrompt(supabase, domainLabel, agentDomain)
        const systemPrompt = dbPrompt ?? this.buildDomainSystemPrompt(domainLabel, agentDomain)
        const userPrompt = this.buildDomainUserPrompt({
          sessionId: review.id,
          reportJson,
          domainCode,
          agentDomain,
          kbContext,
          checklistContext,
          artefactContext,
          nfrContext,
          checkCategories,
        })

        console.log(`Calling LLM for domain: ${agentDomain} (${domainCode})`)
        const llmResponse = await callLLM({
          systemPrompt,
          userPrompt,
          model: review.llm_model || Deno.env.get('GEMINI_MODEL') || 'gemini-2.5-flash-lite',
        })

        // 7. Parse DomainReviewPayload (handles markdown fences)
        let domainReport: any
        try {
          domainReport = parseJsonFromLLM(llmResponse.content)
        } catch (parseErr: any) {
          console.error(`JSON parse failed for domain ${agentDomain}:`, parseErr)
          console.error('Raw LLM content (first 500 chars):', llmResponse.content.slice(0, 500))
          // Pessimistic fallback: an unreadable response is unknown, not adequate.
          // RED-2 ensures the review surfaces as needing re-run rather than silently passing.
          domainReport = {
            summary: {
              rag_score: 2,
              rag_label: 'red',
              overall_readiness: 'DEFER',
              rationale: `LLM response for ${agentDomain} domain could not be parsed — re-run required.`,
              executive_summary: `Domain review failed to parse. Raw output logged for inspection.`,
              evidence_quality: 'ABSENT',
            },
            findings: [{
              id: `${domainCode}-F01`,
              check_category: 'PARSE_FAILURE',
              rag_score: 2,
              rag_label: 'red',
              title: `${agentDomain} domain review unparseable — re-run required`,
              finding: `The LLM response for this domain could not be parsed as valid JSON. This domain has not been assessed. Re-trigger the review to obtain a valid result.`,
              recommendation: 'Re-trigger the review. If the error persists, check LLM quota and token limits.',
              is_blocker: false,
              links_to_action_ids: [],
            }],
            blockers: [],
            recommendations: [],
            actions: [],
            adrs: [],
          }
        }

        // Domain score — LLM-authoritative via summary.rag_score
        const domainScore: number = (() => {
          const raw = Number(domainReport.summary?.rag_score)
          return raw >= 1 && raw <= 5 ? Math.round(raw) : 3
        })()
        const domainRagLabel = scoreToRagLabel(domainScore)

        // rec lookup for fallback recommendation text on findings
        const recByFindingRef: Record<string, string> = {}
        for (const rec of (domainReport.recommendations ?? [])) {
          const ref  = rec.finding_ref || rec.id
          const text = (rec.recommendation ?? rec.rationale ?? '').trim()
          if (ref && text) recByFindingRef[ref] = text
        }

        // Findings (extended fields)
        const domainFindings: Finding[] = (domainReport.findings ?? []).map((f: any) => {
          const findingId   = (f.id ?? f.finding_id ?? '').trim()
          const principleId = (f.principle_id ?? '').trim() || findingId || ''
          const inlineRec   = (f.recommendation ?? '').trim()
          return {
            domain:              agentDomain,
            principle_id:        principleId,
            finding_id:          findingId,
            severity:            ragScoreToSeverity(Number(f.rag_score) || 3),
            finding:             f.finding ?? f.description ?? '',
            recommendation:      inlineRec || recByFindingRef[findingId] || '',
            check_category:      f.check_category ?? '',
            title:               f.title ?? null,
            rag_score:           Number(f.rag_score) || 3,
            evidence_source:     f.evidence_source ?? null,
            standard_violated:   f.standard_violated ?? null,
            impact:              f.impact ?? null,
            is_blocker:          f.is_blocker ?? false,
            links_to_action_ids: f.links_to_action_ids ?? [],
            links_to_adr_id:     f.links_to_adr_id ?? null,
            waiver_eligible:     f.waiver_eligible ?? false,
            kb_reference:        f.kb_reference ?? [],
            artifact_ref:        f.artifact_ref ?? null,
            kb_ref:              f.kb_ref ?? null,
          }
        })

        // Blockers as separate table rows (not merged into findings)
        const domainBlockers = (domainReport.blockers ?? []).map((b: any) => ({
          blocker_id:         b.id ?? b.blocker_id ?? `${domainCode}-BLK-${Date.now()}`,
          domain:             agentDomain,
          title:              b.title ?? b.description ?? '',
          description:        b.description ?? b.title ?? '',
          violated_standard:  b.violated_standard ?? null,
          impact:             b.impact ?? null,
          resolution_required: b.resolution_required ?? '',
          links_to_finding_id: b.finding_ref ?? b.links_to_finding_id ?? null,
          // Only security blockers auto-flag as security_or_dr.
          // Infra blockers split into DR/HA concerns (LLM must assert true) vs platform/ops (false).
          // Auto-flagging infra caused platform findings to trigger the hard security/DR gate.
          is_security_or_dr:  b.is_security_or_dr ?? (agentDomain === 'security'),
          status:             b.status ?? 'OPEN',
          kb_evidence_ref:    b.kb_evidence_ref ?? [],
        }))

        // Recommendations (extended fields)
        const domainRecommendations = (domainReport.recommendations ?? []).map((r: any) => ({
          recommendation_id:    r.id ?? r.recommendation_id ?? `${domainCode}-REC-${Date.now()}`,
          domain:               agentDomain,
          priority:             r.priority ?? 'MEDIUM',
          title:                r.title ?? null,
          rationale:            r.rationale ?? r.recommendation ?? '',
          approved_pattern_ref: r.approved_pattern_ref ?? null,
          benefit:              r.benefit ?? null,
          implementation_hint:  r.implementation_hint ?? null,
          applies_to_finding_id: r.finding_ref ?? r.applies_to_finding_id ?? null,
          applies_to_adr_id:    r.applies_to_adr_id ?? null,
          is_agent_generated:   true,
          kb_source_ref:        r.kb_source_ref ?? [],
        }))

        // Actions (extended fields)
        const domainActions: DomainAction[] = (domainReport.actions ?? []).map((a: any) => ({
          id:                         a.id ?? `${domainCode}-ACT-${Date.now()}`,
          finding_ref:                a.finding_ref ?? '',
          action:                     a.action ?? '',
          owner_role:                 a.owner_role ?? a.proposed_owner ?? 'solution_architect',
          due_days:                   Number(a.due_days) || 30,
          priority:                   a.priority ?? 'MEDIUM',
          // extended
          action_id:                  a.id ?? a.action_id ?? null,
          domain:                     agentDomain,
          action_type:                a.action_type ?? null,
          title:                      a.title ?? null,
          proposed_owner:             a.proposed_owner ?? a.owner_role ?? null,
          proposed_due_date:          a.proposed_due_date ?? null,
          verification_method:        a.verification_method ?? null,
          is_conditional_approval_gate: a.is_conditional_approval_gate ?? false,
          links_to_finding_id:        a.finding_ref ?? a.links_to_finding_id ?? null,
          links_to_blocker_id:        a.links_to_blocker_id ?? null,
          links_to_adr_id:            a.links_to_adr_id ?? null,
        }))

        // ADRs (extended fields)
        const domainAdrs: DomainAdr[] = (domainReport.adrs ?? []).map((d: any) => ({
          id:                 d.id ?? `ADR-${domainCode}-${Date.now()}`,
          adr_type:           d.adr_type ?? d.type ?? 'NEW_DECISION',
          decision:           d.decision ?? '',
          rationale:          d.rationale ?? '',
          context:            d.context,
          owner:              d.owner ?? 'enterprise_architect',
          target_date:        d.target_date ?? null,
          waiver_expiry_date: d.waiver_expiry_date ?? null,
          status:             d.status ?? 'PROPOSED',
          // extended
          domain:             agentDomain,
          title:              d.title ?? d.decision ?? null,
          options_considered: d.options_considered ?? null,
          mitigations:        d.mitigations ?? [],
          proposed_owner:     d.owner ?? d.proposed_owner ?? null,
          proposed_target_date: d.target_date ?? d.proposed_target_date ?? null,
          links_to_finding_ids: d.links_to_finding_ids ?? [],
          links_to_action_ids:  d.links_to_action_ids ?? [],
          kb_references:        d.kb_references ?? [],
        }))

        // NFR scorecard (only populated by the nfr domain agent)
        const domainNfrScorecard = (domainReport.nfr_scorecard ?? []).map((n: any) => ({
          nfr_category:      n.nfr_category ?? n.category ?? '',
          rag_score:         Number(n.rag_score) || 3,
          rag_label:         n.rag_label ?? scoreToRagLabel(Number(n.rag_score) || 3),
          evidence_provided: n.evidence_provided ?? [],
          gaps:              n.gaps ?? [],
          mitigating_condition: n.mitigating_condition ?? null,
          slo_target:        n.slo_target ?? null,
          actual_evidenced:  n.actual_evidenced ?? null,
          is_mandatory_green: n.is_mandatory_green ?? false,
        }))

        const kbRefs: string[] = domainReport.summary?.kb_references ?? []

        // Full DomainSummary object for domain_scores table
        const domainSummary = {
          score:                domainScore,
          rag_label:            domainRagLabel,
          overall_readiness:    domainReport.summary?.overall_readiness ?? null,
          executive_summary:    domainReport.summary?.executive_summary ?? domainReport.summary?.rationale ?? null,
          compliant_areas:      domainReport.summary?.compliant_areas ?? [],
          gap_areas:            domainReport.summary?.gap_areas ?? [],
          blocker_count:        domainBlockers.length,
          action_count:         domainActions.length,
          adr_count:            domainAdrs.length,
          domain_specific_scores: domainReport.summary?.domain_specific_scores ?? null,
          evidence_quality:     domainReport.summary?.evidence_quality ?? null,
          kb_references:        kbRefs,
          model_used:           review.llm_model || 'gemini-2.5-flash-lite',
          // for frontend display
          total_findings:       domainFindings.length,
          critical_count:       domainFindings.filter((f: any) => (f.rag_score || 3) <= 2).length,
          findings:             domainFindings,
          actions:              domainActions,
          adrs:                 domainAdrs,
          recommendations:      domainRecommendations,
        }

        console.log(`Domain ${agentDomain}: score=${domainScore}(${domainRagLabel}), findings=${domainFindings.length}, blockers=${domainBlockers.length}, actions=${domainActions.length}, adrs=${domainAdrs.length}`)

        return {
          score:           domainScore,
          domainSummary,
          findings:        domainFindings,
          blockers:        domainBlockers,
          adrs:            domainAdrs,
          actions:         domainActions,
          recommendations: domainRecommendations,
          nfrScorecard:    domainNfrScorecard,
          kbRefs,
          tokensUsed:      llmResponse.tokensUsed,
        }
      } catch (err: any) {
        lastErr = err
        console.warn(`[ORCHESTRATOR] ${agentDomain} attempt ${attempt} failed: ${err.message}`)
      }
    }

    throw lastErr
  }

  // ── Decision logic (Tier-1 gates) ────────────────────────────────────────────
  // Security/DR architecture blockers are hard gates (reject/defer).
  // Non-security/DR design blockers are conditions (approve_with_conditions).

  private determineDecision(
    aggregateScore: number,
    blockers: any[],
  ): 'approve' | 'approve_with_conditions' | 'defer' | 'reject' {
    const hasSecurityDrBlocker  = blockers.some(b => b.is_security_or_dr)
    const hasNonSecDrBlocker    = blockers.some(b => !b.is_security_or_dr)
    const hasAnyBlocker         = blockers.length > 0

    if (aggregateScore >= 4 && !hasAnyBlocker)          return 'approve'
    if (aggregateScore <= 1 && hasSecurityDrBlocker)    return 'reject'
    if (hasSecurityDrBlocker)                           return 'defer'
    if (hasNonSecDrBlocker || aggregateScore <= 3)      return 'approve_with_conditions'
    return 'approve'
  }
}
