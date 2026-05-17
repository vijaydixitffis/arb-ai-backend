// ================================================================
// CONTEXT BUILDER
// Adapted from context-builder.ts implementation guide.
// Replaces pg.Pool with SupabaseClient (Deno/Supabase Functions).
// ================================================================

import type { SupabaseClient } from 'https://esm.sh/@supabase/supabase-js@2'

// ── Types ────────────────────────────────────────────────────────

export type ComplianceAnswer = 'compliant' | 'non_compliant' | 'partial' | 'na'

export interface QuestionRegistryRow {
  question_code:      string
  question_text:      string
  frontend_tab:       string
  agent_domain:       string
  check_category:     string
  display_group:      string
  sort_order:         number
  weight:             'mandatory_green' | 'important' | 'advisory'
  is_mandatory_green: boolean
  blank_nc_severity:  'blocker' | 'high' | 'medium' | 'low' | 'info'
  na_permitted:       boolean
  hint_text:          string | null
}

export interface EnrichedQuestion extends QuestionRegistryRow {
  answer:   ComplianceAnswer | 'not_answered'
  evidence: string
}

// ── Step 1: Registry cache (1-hour TTL per agent_domain) ─────────

const registryCache = new Map<string, { rows: QuestionRegistryRow[]; expiresAt: number }>()
const CACHE_TTL_MS = 60 * 60 * 1000

export async function getRegistryForAgent(
  supabase:      SupabaseClient,
  agentDomain:   string,
  schemaVersion  = '1.0'
): Promise<QuestionRegistryRow[]> {
  const cacheKey = `${agentDomain}:${schemaVersion}`
  const cached = registryCache.get(cacheKey)
  if (cached && cached.expiresAt > Date.now()) return cached.rows

  const { data, error } = await supabase
    .from('question_registry')
    .select('*')
    .eq('agent_domain', agentDomain)
    .eq('schema_version', schemaVersion)
    .eq('is_active', true)
    .order('sort_order')

  if (error) throw new Error(`Registry load failed for ${agentDomain}: ${error.message}`)

  const rows = (data ?? []) as QuestionRegistryRow[]
  registryCache.set(cacheKey, { rows, expiresAt: Date.now() + CACHE_TTL_MS })
  return rows
}

// ── Step 2: agent_domain → frontend tab(s) ───────────────────────

export function getFrontendTabsForAgent(agentDomain: string): string[] {
  const map: Record<string, string[]> = {
    solution:     ['solution'],
    business:     ['business'],
    application:  ['application'],
    integration:  ['integration'],
    api:          ['integration'],   // int-check-* lives in same tab
    security:     ['infrastructure', 'nfr'],  // infra-sec-* + nfr-sec-*
    data:         ['data'],
    infra:        ['infrastructure'],
    devsecops:    ['devsecops'],
    engg_quality: ['devsecops'],     // engex-* lives in same tab
    nfr:          ['nfr'],
  }
  return map[agentDomain] ?? [agentDomain]
}

// ── Step 3: Extract checklist + evidence from report_json ─────────

export function extractAnswers(
  reportJson:   any,
  frontendTabs: string[]
): { checklist: Record<string, ComplianceAnswer>; evidence: Record<string, string> } {
  const checklist: Record<string, ComplianceAnswer> = {}
  const evidence:  Record<string, string> = {}

  for (const tab of frontendTabs) {
    const tabData = reportJson?.form_data?.domain_data?.[tab]
    if (!tabData) continue
    for (const [code, answer] of Object.entries(tabData.checklist ?? {})) {
      checklist[code] = answer as ComplianceAnswer
    }
    for (const [code, text] of Object.entries(tabData.evidence ?? {})) {
      evidence[code] = (text as string).trim()
    }
  }

  return { checklist, evidence }
}

// ── Step 4: Enrich registry rows with SA answers ──────────────────

export function enrichQuestions(
  registry:  QuestionRegistryRow[],
  checklist: Record<string, ComplianceAnswer>,
  evidence:  Record<string, string>
): EnrichedQuestion[] {
  return registry.map(q => ({
    ...q,
    answer:   checklist[q.question_code] ?? 'not_answered',
    evidence: evidence[q.question_code] ?? '',
  }))
}

// ── Step 5: Format enriched questions into LLM-ready text ─────────

export function formatChecklistBlock(
  enriched:    EnrichedQuestion[],
  agentDomain: string
): string {
  // Exclude N/A (SA explicitly out-of-scope) AND not_answered (SA never attempted — optional per UI)
  const naCount         = enriched.filter(q => q.answer === 'na').length
  const notAttempted    = enriched.filter(q => q.answer === 'not_answered').length
  const active          = enriched.filter(q => q.answer !== 'na' && q.answer !== 'not_answered')

  if (active.length === 0) {
    return [
      `== SA CHECKLIST — domain: ${agentDomain} — no checklist items attempted by SA ==`,
      `   (${enriched.length} registered; ${naCount} marked N/A; ${notAttempted} not attempted — all excluded)`,
      `   Assess domain compliance using artefact evidence only.`,
    ].join('\n')
  }

  const groups = new Map<string, EnrichedQuestion[]>()
  for (const q of active) {
    if (!groups.has(q.check_category)) groups.set(q.check_category, [])
    groups.get(q.check_category)!.push(q)
  }

  const lines: string[] = [
    `== SA CHECKLIST — domain: ${agentDomain} (${active.length} answered; ${naCount} N/A; ${notAttempted} not attempted — N/A and unattempted excluded) ==`,
    '',
    'INSTRUCTIONS FOR THIS SECTION:',
    '  • Generate ONE finding per check_category group, not one per question code.',
    '  • mandatory_green: non_compliant = BLOCKER unless artifact evidence provides adequate mitigation.',
    '  • Blank evidence on non_compliant/partial = absent evidence; cite WHAT is missing and WHY it matters.',
    '  • compliant: raise a finding only if evidence reveals a genuine concern.',
    '  • For categories with solid evidence, a GREEN finding (rag_score 4–5) is the correct output.',
    '',
  ]

  for (const [category, questions] of groups) {
    const isMandatory = questions.some(q => q.is_mandatory_green)
    const flag = isMandatory ? '  ⚠ MANDATORY-GREEN — non_compliant = BLOCKER (verify artifacts first)' : ''
    lines.push(`── check_category: ${category}${flag}`)

    for (const q of questions) {
      const hint = q.hint_text ? `\n           Hint:     ${q.hint_text}` : ''
      lines.push(`  ${q.question_code.padEnd(15)} ${q.question_text}`)
      lines.push(`           Answer:   ${formatAnswer(q.answer)}`)
      lines.push(`           Evidence: ${formatEvidence(q.answer, q.evidence)}${hint}`)

      if (['non_compliant', 'partial'].includes(q.answer)) {
        const sev = q.is_mandatory_green
          ? 'BLOCKER (mandatory-green rule — verify artifact evidence before concluding)'
          : q.blank_nc_severity.toUpperCase() + (q.evidence ? '' : '  (blank evidence — treat as absent)')
        lines.push(`           → Consider: ${sev} finding for ${category}`)
      }
    }
    lines.push('')
  }

  return lines.join('\n')
}

function formatAnswer(answer: string): string {
  return ({
    compliant:     'COMPLIANT',
    non_compliant: 'NON-COMPLIANT ✗',
    partial:       'PARTIAL △',
    na:            'N/A',
    not_answered:  'NOT ANSWERED ✗',
  })[answer] ?? answer.toUpperCase()
}

function formatEvidence(answer: string, evidence: string): string {
  if (evidence) return `"${evidence}"`
  if (answer === 'compliant' || answer === 'na') return '(none — acceptable for this answer)'
  return '(none provided — treat as absent evidence)'
}

// ── Step 6: Top-level builder ─────────────────────────────────────

export async function buildDomainContext(
  supabase:      SupabaseClient,
  reportJson:    any,
  agentDomain:   string,
  schemaVersion  = '1.0'
): Promise<string> {
  const registry = await getRegistryForAgent(supabase, agentDomain, schemaVersion)
  if (registry.length === 0) {
    return `== SA CHECKLIST — domain: ${agentDomain} — no active questions in registry ==`
  }
  const tabs = getFrontendTabsForAgent(agentDomain)
  const { checklist, evidence } = extractAnswers(reportJson, tabs)
  const enriched = enrichQuestions(registry, checklist, evidence)
  return formatChecklistBlock(enriched, agentDomain)
}

// ── Step 7: Solution context block ───────────────────────────────

export function buildSolutionContextBlock(reportJson: any): string {
  const fd = reportJson?.form_data ?? {}
  return [
    '== SOLUTION CONTEXT ==',
    `Solution Name:            ${fd.solution_name ?? fd.project_name ?? '(not provided)'}`,
    `Problem Statement:        ${fd.problem_statement ?? '(not provided)'}`,
    `Stakeholders:             ${(fd.stakeholders ?? []).join(', ') || '(not provided)'}`,
    `Business Drivers:         ${(fd.business_drivers ?? []).join('; ') || '(not provided)'}`,
    `Target Business Outcomes: ${fd.target_business_outcomes ?? fd.growth_plans ?? '(not provided)'}`,
  ].join('\n')
}

// ── Step 8: Artefact block (domain-filtered, truncated) ───────────

const MAX_ARTEFACT_CHARS = 4000

export function buildArtefactBlock(reportJson: any, agentDomain: string): string {
  const uploads: any[] = reportJson?.artefact_uploads ?? []
  const relevant = uploads.filter(u =>
    u.parse_status === 'complete' &&
    u.parsed_text &&
    (!u.domain_tags || u.domain_tags.length === 0 || u.domain_tags.includes(agentDomain))
  )
  if (relevant.length === 0) {
    return `== PARSED ARTEFACTS — none available for domain: ${agentDomain} ==`
  }
  const lines = [`== PARSED ARTEFACTS — ${relevant.length} file(s) for domain: ${agentDomain} ==`]
  for (const u of relevant) {
    lines.push(`\n--- ${u.file_name} (${u.artefact_category ?? 'other'}) ---`)
    const text = (u.parsed_text as string).slice(0, MAX_ARTEFACT_CHARS)
    lines.push(text)
    if (u.parsed_text.length > MAX_ARTEFACT_CHARS) {
      lines.push(`[... truncated — artefact_id: ${u.artefact_id}]`)
    }
  }
  return lines.join('\n')
}

// ── Step 9: NFR quantitative criteria block ───────────────────────

export function buildNfrCriteriaBlock(reportJson: any): string {
  const rows: any[] = reportJson?.form_data?.nfr_criteria ?? []
  if (rows.length === 0) return '== NFR CRITERIA — none provided by SA =='
  const lines = [
    `== NFR QUANTITATIVE CRITERIA (${rows.length} rows) ==`,
    'Use these to calibrate SCALABILITY_PERFORMANCE and HA_RESILIENCE scores.',
    '',
    'Category           | Criteria              | Target      | Actual       | Score | Evidence',
    '-------------------|----------------------|-------------|--------------|-------|----------',
  ]
  for (const r of rows) {
    lines.push([
      (r.category     ?? '').padEnd(18),
      (r.criteria     ?? '').padEnd(21),
      (r.target_value ?? '').padEnd(11),
      (r.actual_value ?? '').padEnd(12),
      String(r.score ?? '?').padEnd(5),
      r.evidence ?? '(none)',
    ].join(' | '))
  }
  return lines.join('\n')
}

// ── Step 10: Knowledge base content fetcher ───────────────────────

const kbCache = new Map<string, { content: string; expiresAt: number }>()
const KB_CACHE_TTL_MS = 30 * 60 * 1000 // 30 minutes

export async function getKnowledgeBaseContent(
  supabase: SupabaseClient,
  categories: string[],
  principleIds?: string[],
  limit?: number
): Promise<string> {
  const cacheKey = `${categories.join(',')}:${principleIds?.join(',') || 'all'}:${limit || 'unlimited'}`
  const cached = kbCache.get(cacheKey)
  if (cached && cached.expiresAt > Date.now()) return cached.content

  let query = supabase
    .from('knowledge_base')
    .select('title, content')
    .in('category', categories)
    .eq('is_active', true)

  if (principleIds && principleIds.length > 0) {
    query = query.or(principleIds.map(id => `principle_id.eq.${id}`).join(','))
  }

  if (limit && limit > 0) {
    query = query.limit(limit)
  }

  const { data, error } = await query.order('created_at', { ascending: true })

  if (error) {
    console.error(`Knowledge base fetch failed: ${error.message}`)
    return ''
  }

  const content = (data ?? [])
    .map(entry => `## ${entry.title}\n\n${entry.content}`)
    .join('\n\n---\n\n')

  kbCache.set(cacheKey, { content, expiresAt: Date.now() + KB_CACHE_TTL_MS })
  return content
}

// ── Step 11: Extract check categories from a loaded registry ─────────
// Returns each unique check_category together with whether any question
// in that category is mandatory_green (i.e. non_compliant = BLOCKER).

export interface CheckCategoryInfo {
  category:         string
  isMandatoryGreen: boolean
}

export function extractCheckCategories(
  registry: QuestionRegistryRow[]
): CheckCategoryInfo[] {
  const seen = new Map<string, boolean>()
  for (const q of registry) {
    const current = seen.get(q.check_category) ?? false
    seen.set(q.check_category, current || q.is_mandatory_green)
  }
  return Array.from(seen.entries())
    .map(([category, isMandatoryGreen]) => ({ category, isMandatoryGreen }))
}

// ── Step 12: Map agent domain to knowledge base categories ─────────

export function getKbCategoriesForAgent(agentDomain: string): string[] {
  const map: Record<string, string[]> = {
    solution:     ['ea_principles', 'ea_standards'],
    business:     ['ea_principles', 'ea_standards'],
    application:  ['ea_principles', 'ea_standards'],
    integration:  ['integration_principles', 'ea_standards'],
    api:          ['integration_principles', 'ea_standards'],
    security:     ['ea_principles', 'ea_standards'],
    data:         ['ea_principles', 'ea_standards'],
    infra:        ['ea_principles', 'ea_standards'],
    devsecops:    ['ea_principles', 'ea_standards'],
    engg_quality: ['ea_principles', 'ea_standards'],
    nfr:          ['ea_principles', 'ea_standards'],
  }
  return map[agentDomain] ?? ['ea_principles', 'ea_standards']
}
