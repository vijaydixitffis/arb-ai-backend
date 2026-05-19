import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"
import { OrchestratorAgent } from "./agents/orchestrator.ts"
import { extractTextFromArtifact, mimeTypeToExt } from "./utils/text-extraction.ts"

// Map legacy/uppercase severity values to the normalised lowercase spec values
function normaliseSeverity(s: string | undefined): string {
  if (!s) return 'low'
  const map: Record<string, string> = {
    BLOCKER: 'blocker', HIGH: 'high', MEDIUM: 'medium', LOW: 'low', INFO: 'info',
    critical: 'blocker', major: 'high', minor: 'low',
  }
  return map[s] ?? s.toLowerCase()
}

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders })
  }

  // Declare outside try so the catch block can reference them for audit logging.
  let reviewId: string | undefined

  // Supabase auto-injects SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in edge functions.
  // PROJECT_URL / SERVICE_ROLE_KEY are kept as fallbacks for local dev overrides.
  const supabaseUrl      = Deno.env.get('SUPABASE_URL')              ?? Deno.env.get('PROJECT_URL')      ?? ''
  const serviceRoleKey   = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? Deno.env.get('SERVICE_ROLE_KEY') ?? ''

  // User-scoped client — respects RLS via caller's JWT (used only for the initial read
  // so the gateway enforces "can this user trigger this review").
  const supabase = createClient(
    supabaseUrl,
    serviceRoleKey,
    { global: { headers: { Authorization: req.headers.get('Authorization') ?? '' } } }
  )

  // Admin client — authenticates as service_role, bypasses RLS entirely.
  // No Authorization header override and no session persistence — ensures PostgREST
  // sets role=service_role (BYPASSRLS) for all write operations.
  const adminSupabase = createClient(
    supabaseUrl,
    serviceRoleKey,
    { auth: { persistSession: false, autoRefreshToken: false } }
  )

  try {
    const body = await req.json()
    reviewId = body.reviewId
    // Optional: restrict processing to a subset of domains (e.g. retry only the ones that failed).
    const retryDomains: string[] | undefined =
      Array.isArray(body.retryDomains) && body.retryDomains.length > 0 ? body.retryDomains : undefined
    const isPartialRetry = retryDomains !== undefined

    if (!reviewId) throw new Error('reviewId is required')

    console.log(`Starting review processing for reviewId: ${reviewId}${isPartialRetry ? ` (partial retry: ${retryDomains!.join(', ')})` : ''}`)

    // ── STEP 1: Fetch review and validate ─────────────────────────────────────
    const { data: review, error: reviewError } = await supabase
      .from('reviews')
      .select('*')
      .eq('id', reviewId)
      .single()

    if (reviewError || !review) {
      throw new Error(`Review not found: ${reviewError?.message}`)
    }

    // Accept intake-complete states plus stuck/failed states for re-triggers.
    // review_ready is allowed for partial domain retries (e.g. one domain failed with 503).
    if (!['queued', 'pending', 'submitted', 'returned', 'analysing', 'agent_failed', 'review_pending', 'review_ready'].includes(review.status)) {
      throw new Error(`Review not ready for processing: ${review.status}`)
    }

    await adminSupabase
      .from('reviews')
      .update({ status: 'analysing', submitted_at: new Date().toISOString() })
      .eq('id', reviewId)

    // Pre-insert domain_reviews rows for progress tracking.
    // scope_tags use agent-level keys (e.g. 'infrastructure'); expand to canonical domain slugs.
    const agentDomainMap: Record<string, string[]> = {
      solution:       ['solution'],
      business:       ['business'],
      application:    ['application'],
      integration:    ['integration'],
      data:           ['data'],
      infrastructure: ['infrastructure'],
      devsecops:      ['devsecops'],
      nfr:            ['nfr'],
    }
    // For a partial retry only track the domains being re-run.
    const scopeDomains: string[] = isPartialRetry ? retryDomains! : (review.scope_tags ?? [])
    const expandedDomains = [...new Set(
      scopeDomains.flatMap((tag: string) => agentDomainMap[tag] ?? [tag])
    )]
    if (expandedDomains.length > 0) {
      const domainRows = expandedDomains.map((domain: string) => ({
        review_id:    reviewId,
        domain,
        agent_status: 'waiting',
        retry_count:  0,
      }))
      const { error: drErr } = await adminSupabase
        .from('domain_reviews')
        .upsert(domainRows, { onConflict: 'review_id,domain' })
      if (drErr) console.warn(`domain_reviews pre-insert (non-fatal): ${drErr.message}`)
    }

    console.log(`Review ${reviewId} status updated to analysing`)

    // ── STEP 2: Extract artifact text ────────────────────────────────────────────
    // 2a. Legacy single-file path (artifact_path column)
    let artifactText = ''
    if (review.artifact_path) {
      console.log(`Downloading artifact from: ${review.artifact_path}`)
      const { data: artifactData, error: downloadError } = await supabase
        .storage
        .from('review-artifacts')
        .download(review.artifact_path)

      if (downloadError || !artifactData) {
        console.warn(`Artifact download failed (non-fatal): ${downloadError?.message}`)
      } else {
        artifactText = await extractTextFromArtifact(
          artifactData,
          review.artifact_file_type || 'pdf'
        )
        console.log(`Extracted ${artifactText.length} characters from artifact`)
      }
    }

    // 2b. Multi-artefact schema — query artefacts table (authoritative source of storage_path),
    //     download each file from Storage, extract text, then inject parsed_text into
    //     report_json.artefact_uploads so buildArtefactBlock can serve it to domain agents.
    const { data: artefactRows, error: artefactFetchErr } = await adminSupabase
      .from('artefacts')
      .select('id, storage_path, file_type, filename, domain_slug')
      .eq('review_id', reviewId)
      .eq('is_active', true)

    if (artefactFetchErr) {
      console.warn(`[STEP 2b] artefacts fetch failed (non-fatal): ${artefactFetchErr.message}`)
    } else if (artefactRows && artefactRows.length > 0) {
      console.log(`[STEP 2b] Extracting text from ${artefactRows.length} artefact(s) via Storage...`)

      // Work on a mutable copy of artefact_uploads so buildArtefactBlock finds completed entries
      const updatedUploads: any[] = (review.report_json?.artefact_uploads ?? []).map((u: any) => ({ ...u }))
      let anyUpdated = false

      for (const row of artefactRows) {
        // Skip artefacts already extracted in a previous run — avoids redundant
        // storage downloads on partial retries and failed re-triggers.
        const existingEntry = updatedUploads.find((u: any) => u.artefact_id === row.id)
        if (existingEntry?.parse_status === 'complete') {
          console.log(`[STEP 2b] Skipping ${row.filename} — already extracted`)
          continue
        }

        const { data: fileData, error: dlErr } = await adminSupabase
          .storage
          .from('review-artifacts')
          .download(row.storage_path)

        if (dlErr || !fileData) {
          console.warn(`[STEP 2b] Download failed for ${row.filename}: ${dlErr?.message}`)
          continue
        }

        try {
          const ext = mimeTypeToExt(row.file_type) ?? row.filename.split('.').pop()?.toLowerCase() ?? 'unknown'
          const parsedText = await extractTextFromArtifact(fileData, ext)
          console.log(`[STEP 2b] Extracted ${parsedText.length} chars from ${row.filename}`)

          // Update existing artefact_uploads entry if present, otherwise add one
          const idx = updatedUploads.findIndex((u: any) => u.artefact_id === row.id)
          if (idx >= 0) {
            updatedUploads[idx].parsed_text  = parsedText
            updatedUploads[idx].parse_status = 'complete'
          } else {
            updatedUploads.push({
              artefact_id:  row.id,
              file_name:    row.filename,
              domain_tags:  row.domain_slug ? [row.domain_slug] : [],
              storage_path: row.storage_path,
              file_type:    row.file_type,
              parsed_text:  parsedText,
              parse_status: 'complete',
              is_active:    true,
            })
          }
          anyUpdated = true
        } catch (extractErr: any) {
          console.error(`[STEP 2b] Extraction failed for ${row.filename}:`, extractErr.message)
        }
      }

      if (anyUpdated) {
        const { error: persistErr } = await adminSupabase
          .from('reviews')
          .update({ report_json: { ...review.report_json, artefact_uploads: updatedUploads } })
          .eq('id', reviewId)
        if (persistErr) console.error('[STEP 2b] Failed to persist parse results (non-fatal):', persistErr.message)
        review.report_json = { ...review.report_json, artefact_uploads: updatedUploads }
      }
    }

    // ── STEP 3: Run orchestrator ───────────────────────────────────────────────
    const orchestrator = new OrchestratorAgent()
    const startTime    = Date.now()

    // For a partial retry only run the specified domains; otherwise run all scope_tags.
    const scopeTagsToRun = isPartialRetry ? retryDomains! : (review.scope_tags ?? [])

    const reviewResult = await orchestrator.validateReview({
      review,
      reportJson:   review.report_json,
      artifactText,
      supabase:     adminSupabase,  // admin client for KB/checklist reads — no RLS interference
      scopeTags:    scopeTagsToRun,
    })

    const processingTime = Date.now() - startTime
    console.log(`Review processing completed in ${processingTime}ms`)

    // ── STEP 4: Persist results ────────────────────────────────────────────────

    const now = new Date().toISOString()

    // Detect domains whose agent produced a stub AGENT_FAILURE finding (503 / timeout).
    const newlyFailedDomains: string[] = reviewResult.findings
      .filter((f: any) => f.check_category === 'AGENT_FAILURE')
      .map((f: any) => f.domain as string)

    // For partial retry: compute the true aggregate across ALL domains (not just the retried subset).
    let aggregateScoreToSave    = reviewResult.aggregateScore
    let aggregateRagLabelToSave = reviewResult.aggregateRagLabel
    if (isPartialRetry) {
      const { data: existingScores } = await adminSupabase
        .from('domain_scores')
        .select('domain, score')
        .eq('review_id', reviewId)
        .not('domain', 'in', `(${retryDomains!.map(d => `"${d}"`).join(',')})`)
      const allScores = [
        ...(existingScores || []).map((s: any) => Number(s.score)),
        ...Object.values(reviewResult.domainScores).map(Number),
      ]
      if (allScores.length > 0) {
        aggregateScoreToSave = Math.min(...allScores)
        aggregateRagLabelToSave = aggregateScoreToSave >= 4 ? 'green' : aggregateScoreToSave === 3 ? 'amber' : 'red'
      }
    }

    // 4a. Update reviews table
    // Always carry form_data forward so SA can edit the submission after LLM processing.
    // For partial retry: merge new domain_summaries into the existing report_json so other
    // domains' data is preserved.
    let reportToSave: any = {
      ...reviewResult.fullReport,
      form_data: review.report_json?.form_data ?? reviewResult.fullReport.form_data,
      failed_domains: (() => {
        if (!isPartialRetry) return newlyFailedDomains.length > 0 ? newlyFailedDomains : undefined
        // Remove the retried domains from the previous failed list; add any newly failed ones.
        const prevFailed: string[] = review.report_json?.failed_domains ?? []
        const stillFailed = prevFailed.filter((d: string) => !retryDomains!.includes(d))
        const merged = [...new Set([...stillFailed, ...newlyFailedDomains])]
        return merged.length > 0 ? merged : undefined
      })(),
    }
    if (isPartialRetry) {
      const existingReport    = review.report_json || {}
      const existingAiReview  = existingReport.ai_review || {}
      reportToSave = {
        ...existingReport,
        ...reportToSave,
        ai_review: {
          ...existingAiReview,
          ...reportToSave.ai_review,
          domain_summaries: { ...existingAiReview.domain_summaries, ...reportToSave.ai_review?.domain_summaries },
          domain_scores:    { ...(existingAiReview.domain_scores || {}), ...reportToSave.ai_review?.domain_scores },
        },
        domain_summaries: { ...(existingReport.domain_summaries || {}), ...(reportToSave.domain_summaries || {}) },
        domain_scores:    { ...(existingReport.domain_scores    || {}), ...(reportToSave.domain_scores    || {}) },
      }
    }
    // Strip per-domain partial cache — it's only needed during a run; the final persisted
    // report_json should be clean so stale partials don't interfere with future re-triggers.
    delete reportToSave.domain_partial_results

    const { error: updateError } = await adminSupabase
      .from('reviews')
      .update({
        status:                 'review_ready',
        decision:               reviewResult.decision,
        report_json:            reportToSave,
        tokens_used:            reviewResult.tokensUsed,
        processing_time_ms:     processingTime,
        llm_raw_response:       reviewResult.rawResponse,
        reviewed_at:            now,
        agent_run_at:           now,
        aggregate_rag_score:    aggregateScoreToSave,
        aggregate_rag_label:    aggregateRagLabelToSave,
        recommended_decision:   reviewResult.decision,
        decision_rationale:     reviewResult.executiveRationale || null,
        kb_sources_cited:       reviewResult.kbSourcesCited,
        consolidated_blockers:  reviewResult.blockers,
        consolidated_actions:   reviewResult.actions,
      })
      .eq('id', reviewId)

    if (updateError) console.error(`reviews update (4a) failed (continuing): ${updateError.message}`)

    // 4b. Domain scores — upsert with full DomainSummary fields
    for (const [domain, summary] of Object.entries(reviewResult.domainSummaries)) {
      const s = summary as any
      const { error: dsErr } = await adminSupabase
        .from('domain_scores')
        .upsert(
          {
            review_id:              reviewId,
            domain,
            score:                  s.score,
            rag_label:              s.rag_label,
            overall_readiness:      s.overall_readiness    ?? null,
            executive_summary:      s.executive_summary    ?? null,
            compliant_areas:        s.compliant_areas      ?? [],
            gap_areas:              s.gap_areas            ?? [],
            blocker_count:          s.blocker_count        ?? 0,
            action_count:           s.action_count         ?? 0,
            adr_count:              s.adr_count            ?? 0,
            domain_specific_scores: s.domain_specific_scores ?? null,
            evidence_quality:       s.evidence_quality     ?? null,
            kb_references:          s.kb_references        ?? [],
            model_used:             s.model_used           ?? null,
            generated_at:           now,
          },
          { onConflict: 'review_id,domain' }
        )
      if (dsErr) console.error(`domain_scores upsert failed for ${domain}:`, dsErr.message)
    }

    // 4c. Blockers — delete all domains that produced results this run.
    // For partial retry we scope to ran domains (not just retryDomains) because
    // domain_partial_results may have been externally cleared, causing more domains
    // to re-run than retryDomains implies — scoping to retryDomains would leave
    // stale records from the extra domains and double the blocker count.
    const domainsRan = Object.keys(reviewResult.domainScores)
    if (isPartialRetry) {
      for (const d of domainsRan) {
        await adminSupabase.from('blockers').delete().eq('review_id', reviewId).eq('domain', d)
      }
    } else {
      await adminSupabase.from('blockers').delete().eq('review_id', reviewId)
    }
    if (reviewResult.blockers.length > 0) {
      const { error: blkErr } = await adminSupabase
        .from('blockers')
        .insert(reviewResult.blockers.map(b => ({
          review_id:          reviewId,
          blocker_id:         b.blocker_id,
          domain:             b.domain,
          title:              b.title,
          description:        b.description,
          violated_standard:  b.violated_standard  ?? null,
          impact:             b.impact             ?? null,
          resolution_required: b.resolution_required,
          links_to_finding_id: b.links_to_finding_id ?? null,
          is_security_or_dr:  b.is_security_or_dr  ?? false,
          status:             (b.status ?? 'OPEN').toLowerCase(),
          kb_evidence_ref:    b.kb_evidence_ref    ?? [],
        })))
      if (blkErr) console.error('blockers insert failed:', blkErr.message)
    }

    // 4d. Recommendations — same domainsRan scope as blockers
    if (isPartialRetry) {
      for (const d of domainsRan) {
        await adminSupabase.from('recommendations').delete().eq('review_id', reviewId).eq('domain', d)
      }
    } else {
      await adminSupabase.from('recommendations').delete().eq('review_id', reviewId)
    }
    if (reviewResult.recommendations.length > 0) {
      const { error: recErr } = await adminSupabase
        .from('recommendations')
        .insert(reviewResult.recommendations.map(r => ({
          review_id:            reviewId,
          recommendation_id:    r.recommendation_id,
          domain:               r.domain               ?? 'general',
          priority:             (r.priority ?? 'medium').toLowerCase(),
          title:                r.title                ?? null,
          rationale:            r.rationale            ?? null,
          approved_pattern_ref: r.approved_pattern_ref ?? null,
          benefit:              r.benefit              ?? null,
          implementation_hint:  r.implementation_hint  ?? null,
          applies_to_finding_id: r.applies_to_finding_id ?? null,
          applies_to_adr_id:    r.applies_to_adr_id    ?? null,
          is_agent_generated:   true,
          kb_source_ref:        r.kb_source_ref        ?? [],
        })))
      if (recErr) console.error('recommendations insert failed:', recErr.message)
    }

    // 4e. Findings — same domainsRan scope as blockers
    if (isPartialRetry) {
      for (const d of domainsRan) {
        await adminSupabase.from('findings').delete().eq('review_id', reviewId).eq('domain', d)
      }
    } else {
      await adminSupabase.from('findings').delete().eq('review_id', reviewId)
    }
    if (reviewResult.findings.length > 0) {
      const { error: findErr } = await adminSupabase
        .from('findings')
        .insert(reviewResult.findings.map((f: any) => ({
          review_id:           reviewId,
          domain:              f.domain,
          principle_id:        f.principle_id        || null,
          finding_id:          f.finding_id          || null,
          severity:            normaliseSeverity(f.severity),
          finding:             f.finding,
          recommendation:      f.recommendation      || null,
          check_category:      f.check_category      || null,
          is_resolved:         false,
          title:               f.title               ?? null,
          rag_score:           f.rag_score            ?? null,
          evidence_source:     f.evidence_source      ?? null,
          standard_violated:   f.standard_violated    ?? null,
          impact:              f.impact               ?? null,
          is_blocker:          f.is_blocker           ?? false,
          links_to_action_ids: f.links_to_action_ids  ?? [],
          links_to_adr_id:     f.links_to_adr_id      ?? null,
          waiver_eligible:     f.waiver_eligible       ?? false,
          kb_reference:        f.kb_reference          ?? [],
          artifact_ref:        f.artifact_ref          ?? null,
          kb_ref:              f.kb_ref                ?? null,
        })))
      if (findErr) console.error('findings insert failed:', findErr.message)
    }

    // 4f. ADRs — delete then insert fresh
    // ADRs are stored with domain=null (chk_adrs_domain constraint prevents storing a
    // domain slug), so we cannot scope the delete by domain as we do for other tables.
    // On a partial retry: read existing ADRs first, preserve those not superseded by
    // this run (matched by adr_id), then re-insert the merged set — matching Python's
    // behaviour of always persisting the full cross-domain ADR set.
    const newAdrRows = reviewResult.adrs.map((adr: any, i: number) => ({
      review_id:            reviewId,
      adr_id:               adr.id || `ADR-${reviewId.slice(0, 8)}-${String(i + 1).padStart(3, '0')}`,
      decision:             adr.decision,
      rationale:            adr.rationale,
      context:              adr.context              ?? null,
      consequences:         adr.consequences         ?? null,
      owner:                adr.owner                ?? null,
      target_date:          adr.target_date          ?? null,
      status:               'proposed',
      domain:               null, // chk_adrs_domain constraint — must remain null
      adr_type:             null, // chk_adrs_type constraint — must remain null
      title:                adr.title                ?? null,
      options_considered:   adr.options_considered   ?? null,
      mitigations:          adr.mitigations          ?? [],
      proposed_target_date: null, // chk constraint — skip this field
      waiver_expiry_date:   adr.waiver_expiry_date   ?? null,
      links_to_finding_ids: adr.links_to_finding_ids ?? [],
      links_to_action_ids:  adr.links_to_action_ids  ?? [],
      kb_references:        adr.kb_references        ?? [],
    }))

    let adrsToInsert: any[] = newAdrRows
    if (isPartialRetry) {
      // Fetch only the insertable columns to avoid re-inserting the auto-generated PK.
      const { data: existingAdrs } = await adminSupabase
        .from('adrs')
        .select('adr_id, decision, rationale, context, consequences, owner, target_date, status, domain, adr_type, title, options_considered, mitigations, proposed_target_date, waiver_expiry_date, links_to_finding_ids, links_to_action_ids, kb_references')
        .eq('review_id', reviewId!)
      const newAdrIds = new Set(newAdrRows.map((a: any) => a.adr_id))
      const preserved = (existingAdrs || [])
        .filter((a: any) => !newAdrIds.has(a.adr_id))
        .map((a: any) => ({ ...a, review_id: reviewId }))
      adrsToInsert = [...preserved, ...newAdrRows]
    }

    await adminSupabase.from('adrs').delete().eq('review_id', reviewId)
    if (adrsToInsert.length > 0) {
      const { error: adrErr } = await adminSupabase.from('adrs').insert(adrsToInsert)
      if (adrErr) console.error('adrs insert failed:', adrErr.message)
    }

    // 4g. Actions — same domainsRan scope as blockers
    if (isPartialRetry) {
      for (const d of domainsRan) {
        await adminSupabase.from('actions').delete().eq('review_id', reviewId).eq('domain', d)
      }
    } else {
      await adminSupabase.from('actions').delete().eq('review_id', reviewId)
    }
    if (reviewResult.actions.length > 0) {
      const { error: actErr } = await adminSupabase
        .from('actions')
        .insert(reviewResult.actions.map((action: any) => {
          const dueDays = action.due_days != null ? parseInt(String(action.due_days), 10) || null : null
          const dueDate = dueDays
            ? new Date(Date.now() + dueDays * 86_400_000).toISOString().split('T')[0]
            : action.proposed_due_date ?? null
          
          // Set proposed_due_date to null to avoid constraint violations
          // The constraint is too restrictive, so we'll skip this field
          const formattedProposedDueDate = null
          
          return {
            review_id:                   reviewId,
            action_text:                 action.action,
            owner_role:                  action.owner_role    ?? null,
            due_days:                    dueDays,
            due_date:                    dueDate,
            status:                      'open',
            action_id:                   action.action_id     ?? action.id ?? null,
            domain:                      action.domain        ?? null,
            action_type:                 action.action_type?.toLowerCase() ?? null,
            title:                       action.title         ?? null,
            proposed_owner:              action.proposed_owner ?? action.owner_role ?? null,
            proposed_due_date:           formattedProposedDueDate,
            verification_method:         action.verification_method ?? null,
            is_conditional_approval_gate: action.is_conditional_approval_gate ?? false,
            links_to_finding_id:         action.links_to_finding_id ?? action.finding_ref ?? null,
            links_to_blocker_id:         action.links_to_blocker_id ?? null,
            links_to_adr_id:             action.links_to_adr_id     ?? null,
            priority:                    action.priority            ?? null,
          }
        }))
      if (actErr) console.error('actions insert failed:', actErr.message)
    }

    // 4h. NFR Scorecard — upsert per category
    for (const nfr of reviewResult.nfrScorecard) {
      const { error: nfrErr } = await adminSupabase
        .from('nfr_scorecard')
        .upsert(
          {
            review_id:           reviewId,
            nfr_category:        nfr.nfr_category,
            rag_score:           nfr.rag_score,
            rag_label:           nfr.rag_label           ?? null,
            evidence_provided:   nfr.evidence_provided   ?? [],
            gaps:                nfr.gaps                ?? [],
            mitigating_condition: nfr.mitigating_condition ?? null,
            slo_target:          nfr.slo_target           ?? null,
            actual_evidenced:    nfr.actual_evidenced      ?? null,
            is_mandatory_green:  nfr.is_mandatory_green   ?? false,
          },
          { onConflict: 'review_id,nfr_category' }
        )
      if (nfrErr) console.error(`nfr_scorecard upsert failed for ${nfr.nfr_category}:`, nfrErr.message)
    }

    // 4i. Audit log
    const synthesisFellBack = reviewResult.executiveRationale?.startsWith('Synthesis step unavailable') ?? false
    const { error: auditErr } = await adminSupabase.from('audit_log').insert({
      review_id: reviewId,
      user_id:   null,
      user_role: 'system',
      action:    'llm_processed',
      metadata: {
        tokens_used:                reviewResult.tokensUsed,
        processing_time_ms:         processingTime,
        model:                      review.llm_model || Deno.env.get('GEMINI_MODEL') || 'gemini-2.5-flash-lite',
        domains_reviewed:           review.scope_tags,
        findings_count:             reviewResult.findings.length,
        blockers_count:             reviewResult.blockers.length,
        adrs_count:                 reviewResult.adrs.length,
        actions_count:              reviewResult.actions.length,
        recommendations_count:      reviewResult.recommendations.length,
        nfr_scorecard_count:        reviewResult.nfrScorecard.length,
        aggregate_rag_label:        reviewResult.aggregateRagLabel,
        synthesis_ran:              !synthesisFellBack,
        synthesis_score_corrections: reviewResult.scoreCorrections?.length ?? 0,
        synthesis_removed_adrs:     reviewResult.fullReport?.ai_review?.removed_adr_ids?.length ?? 0,
        synthesis_dedup_findings:   reviewResult.fullReport?.ai_review?.duplicate_finding_ids?.length ?? 0,
      },
    })
    if (auditErr) console.error(`audit_log insert failed (non-fatal): ${auditErr.message}`)
    if (synthesisFellBack) console.warn('[ORCHESTRATOR] Synthesis fell back — executive rationale not generated. Check [SYNTHESIS] logs above.')

    console.log(`Review ${reviewId} processing completed successfully`)

    return new Response(
      JSON.stringify({
        success:  true,
        reviewId,
        decision: reviewResult.decision,
        report:   reviewResult.fullReport,
      }),
      { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    )

  } catch (error) {
    console.error('Error in review-orchestrator:', error)

    if (reviewId) {
      try {
        // Reset review to agent_failed so the UI retry banner becomes visible
        await adminSupabase
          .from('reviews')
          .update({ status: 'agent_failed' })
          .eq('id', reviewId)
        await adminSupabase.from('audit_log').insert({
          review_id: reviewId,
          user_id:   null,
          user_role: 'system',
          action:    'processing_error',
          metadata:  { error: error.message },
        })
      } catch (logError) {
        console.error('Failed to log error:', logError)
      }
    }

    return new Response(
      JSON.stringify({ error: error.message }),
      { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    )
  }
})
