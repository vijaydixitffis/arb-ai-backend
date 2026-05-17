/**
 * Admin API — Supabase Edge Function
 *
 * Provides all admin operations for arb_admin and super_admin roles,
 * consistent with the Python FastAPI admin endpoints at /api/v1/admin/*.
 *
 * Route convention: POST /admin-api  with body { action, payload }
 * Actions map 1-to-1 with Python endpoint operations.
 */
import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

const ADMIN_ROLES    = new Set(['arb_admin', 'super_admin'])
const SUPER_ADMIN    = new Set(['super_admin'])

// ── Helpers ───────────────────────────────────────────────────────────────────

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' },
  })
}

function errResponse(message: string, status = 400) {
  return jsonResponse({ error: message }, status)
}

async function getUserRole(supabase: ReturnType<typeof createClient>, userId: string): Promise<string | null> {
  // Try matching by id first (works for users created via admin createUser API)
  const { data: byId } = await supabase
    .from('users')
    .select('role, is_active')
    .eq('id', userId)
    .maybeSingle()
  if (byId?.is_active) return byId.role

  // Fallback: match by email via auth.admin (handles seeded users whose
  // public.users.id was generated independently from the Supabase auth UUID)
  const { data: authData } = await supabase.auth.admin.getUserById(userId)
  if (!authData?.user?.email) return null
  const { data: byEmail } = await supabase
    .from('users')
    .select('role, is_active')
    .eq('email', authData.user.email)
    .maybeSingle()
  if (!byEmail?.is_active) return null
  return byEmail.role
}

function getAdminClient() {
  const supabaseUrl    = Deno.env.get('SUPABASE_URL')              ?? ''
  const serviceRoleKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
  return createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  })
}

// ── Main handler ──────────────────────────────────────────────────────────────

serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders })

  const adminClient = getAdminClient()

  // Authenticate caller — extract JWT and verify explicitly
  const token = req.headers.get('Authorization')?.replace('Bearer ', '') ?? ''
  if (!token) return errResponse('Authentication required', 401)
  const { data: { user }, error: authErr } = await adminClient.auth.getUser(token)
  if (authErr || !user) return errResponse('Authentication required', 401)

  const callerRole = await getUserRole(adminClient, user.id)
  if (!callerRole || !ADMIN_ROLES.has(callerRole)) {
    return errResponse('Admin access required (arb_admin or super_admin)', 403)
  }

  let body: { action: string; payload?: any }
  try {
    body = await req.json()
  } catch {
    return errResponse('Invalid JSON body')
  }

  const { action, payload = {} } = body

  try {
    // ── CONFIG ─────────────────────────────────────────────────────────────────

    if (action === 'getConfig') {
      if (!SUPER_ADMIN.has(callerRole)) return errResponse('Super admin access required', 403)
      const { data, error } = await adminClient.from('system_config').select('*').order('category').order('config_key')
      if (error) throw error
      const grouped: Record<string, any[]> = {}
      for (const row of data ?? []) {
        grouped[row.category] = grouped[row.category] ?? []
        grouped[row.category].push(row)
      }
      return jsonResponse({ config: grouped })
    }

    if (action === 'updateConfig') {
      if (!SUPER_ADMIN.has(callerRole)) return errResponse('Super admin access required', 403)
      const { config_key, config_value, change_reason } = payload
      const { error } = await adminClient.from('system_config')
        .update({ config_value, updated_by: user.id, updated_at: new Date().toISOString() })
        .eq('config_key', config_key)
      if (error) throw error
      await adminClient.from('config_audit_log').insert({
        table_name: 'system_config', record_id: config_key, field_name: config_key,
        new_value: config_value, changed_by: user.id, change_reason,
      })
      return jsonResponse({ config_key, updated: true })
    }

    // ── USERS ──────────────────────────────────────────────────────────────────

    if (action === 'listUsers') {
      const { data, error } = await adminClient.from('users').select('id, email, role, is_active, last_login_at, created_at, updated_at').order('created_at', { ascending: false })
      if (error) throw error
      return jsonResponse({ users: data ?? [] })
    }

    if (action === 'createUser') {
      const { email, password, role, is_active = true } = payload
      const { data: authData, error: authError } = await adminClient.auth.admin.createUser({
        email, password, user_metadata: { role }, email_confirm: true,
      })
      if (authError) throw authError
      // Also insert into users table for our RLS lookups
      const { error: dbError } = await adminClient.from('users').upsert({
        id: authData.user.id, email, role, is_active, created_by: user.id,
      })
      if (dbError) throw dbError
      await adminClient.from('config_audit_log').insert({
        table_name: 'users', record_id: authData.user.id, field_name: 'created',
        new_value: { email, role }, changed_by: user.id,
      })
      return jsonResponse({ id: authData.user.id, email, role, created: true }, 201)
    }

    if (action === 'updateUser') {
      const { user_id, role, is_active } = payload
      const updates: Record<string, any> = {}
      if (role !== undefined) updates.role = role
      if (is_active !== undefined) updates.is_active = is_active
      const { error } = await adminClient.from('users').update({ ...updates, updated_at: new Date().toISOString() }).eq('id', user_id)
      if (error) throw error
      await adminClient.from('config_audit_log').insert({
        table_name: 'users', record_id: user_id, field_name: Object.keys(updates).join(','),
        new_value: updates, changed_by: user.id,
      })
      return jsonResponse({ user_id, updated: true })
    }

    if (action === 'deactivateUser') {
      const { user_id } = payload
      const { error } = await adminClient.from('users').update({ is_active: false, updated_at: new Date().toISOString() }).eq('id', user_id)
      if (error) throw error
      return jsonResponse({ user_id, deactivated: true })
    }

    if (action === 'resetPassword') {
      const { user_id, new_password } = payload
      const { error } = await adminClient.auth.admin.updateUserById(user_id, { password: new_password })
      if (error) throw error
      return jsonResponse({ user_id, reset: true })
    }

    // ── DOMAINS ────────────────────────────────────────────────────────────────

    if (action === 'listDomains') {
      const includeInactive = payload.include_inactive !== false
      let q = adminClient.from('domains').select('*').order('seq_number')
      if (!includeInactive) q = q.eq('is_active', true)
      const { data, error } = await q
      if (error) throw error
      return jsonResponse({ domains: data ?? [] })
    }

    if (action === 'updateDomain') {
      const { domain_id, change_reason, ...updates } = payload
      const { error } = await adminClient.from('domains').update({ ...updates, updated_at: new Date().toISOString() }).eq('id', domain_id)
      if (error) throw error
      await adminClient.from('config_audit_log').insert({
        table_name: 'domains', record_id: domain_id, new_value: updates, changed_by: user.id, change_reason,
      })
      return jsonResponse({ domain_id, updated: true })
    }

    // ── ARTEFACT TYPES ─────────────────────────────────────────────────────────

    if (action === 'listArtefactTypes') {
      const { data, error } = await adminClient.from('artefact_types').select('*').order('label')
      if (error) throw error
      return jsonResponse({ artefact_types: data ?? [] })
    }

    if (action === 'createArtefactType') {
      const { error, data } = await adminClient.from('artefact_types').insert(payload).select().single()
      if (error) throw error
      return jsonResponse({ id: data.id, created: true }, 201)
    }

    if (action === 'updateArtefactType') {
      const { id, ...updates } = payload
      const { error } = await adminClient.from('artefact_types').update(updates).eq('id', id)
      if (error) throw error
      return jsonResponse({ id, updated: true })
    }

    if (action === 'deleteArtefactType') {
      const { error } = await adminClient.from('artefact_types').update({ is_active: false }).eq('id', payload.id)
      if (error) throw error
      return jsonResponse({ id: payload.id, deleted: true })
    }

    // ── PTX GATES ──────────────────────────────────────────────────────────────

    if (action === 'listPtxGates') {
      const { data, error } = await adminClient.from('ptx_gates').select('*').order('sort_order')
      if (error) throw error
      return jsonResponse({ ptx_gates: data ?? [] })
    }

    if (action === 'createPtxGate') {
      const { error, data } = await adminClient.from('ptx_gates').insert(payload).select().single()
      if (error) throw error
      return jsonResponse({ id: data.id, created: true }, 201)
    }

    if (action === 'updatePtxGate') {
      const { id, ...updates } = payload
      const { error } = await adminClient.from('ptx_gates').update(updates).eq('id', id)
      if (error) throw error
      return jsonResponse({ id, updated: true })
    }

    if (action === 'deletePtxGate') {
      const { error } = await adminClient.from('ptx_gates').update({ is_active: false }).eq('id', payload.id)
      if (error) throw error
      return jsonResponse({ id: payload.id, deleted: true })
    }

    // ── DISPOSITIONS ───────────────────────────────────────────────────────────

    if (action === 'listDispositions') {
      const { data, error } = await adminClient.from('architecture_dispositions').select('*').order('sort_order')
      if (error) throw error
      return jsonResponse({ dispositions: data ?? [] })
    }

    if (action === 'createDisposition') {
      const { error, data } = await adminClient.from('architecture_dispositions').insert(payload).select().single()
      if (error) throw error
      return jsonResponse({ id: data.id, created: true }, 201)
    }

    if (action === 'updateDisposition') {
      const { id, ...updates } = payload
      const { error } = await adminClient.from('architecture_dispositions').update(updates).eq('id', id)
      if (error) throw error
      return jsonResponse({ id, updated: true })
    }

    if (action === 'deleteDisposition') {
      const { error } = await adminClient.from('architecture_dispositions').update({ is_active: false }).eq('id', payload.id)
      if (error) throw error
      return jsonResponse({ id: payload.id, deleted: true })
    }

    // ── EA PRINCIPLES ──────────────────────────────────────────────────────────

    if (action === 'listEAPrinciples') {
      const { data, error } = await adminClient.from('ea_principles').select('*').order('principle_code')
      if (error) throw error
      return jsonResponse({ ea_principles: data ?? [] })
    }

    if (action === 'createEAPrinciple') {
      const { error, data } = await adminClient.from('ea_principles').insert(payload).select().single()
      if (error) throw error
      return jsonResponse({ id: data.id, created: true }, 201)
    }

    if (action === 'updateEAPrinciple') {
      const { id, ...updates } = payload
      const { error } = await adminClient.from('ea_principles').update({ ...updates, updated_at: new Date().toISOString() }).eq('id', id)
      if (error) throw error
      return jsonResponse({ id, updated: true })
    }

    if (action === 'deleteEAPrinciple') {
      const { error } = await adminClient.from('ea_principles').update({ is_active: false }).eq('id', payload.id)
      if (error) throw error
      return jsonResponse({ id: payload.id, deleted: true })
    }

    // ── CHECKLIST ──────────────────────────────────────────────────────────────

    if (action === 'listSubsections') {
      let q = adminClient.from('checklist_subsections').select('*').order('sort_order')
      if (payload.domain_id) q = q.eq('domain_id', payload.domain_id)
      const { data, error } = await q
      if (error) throw error
      return jsonResponse({ subsections: data ?? [] })
    }

    if (action === 'createSubsection') {
      const { error, data } = await adminClient.from('checklist_subsections').insert(payload).select().single()
      if (error) throw error
      return jsonResponse({ id: data.id, created: true }, 201)
    }

    if (action === 'updateSubsection') {
      const { id, ...updates } = payload
      const { error } = await adminClient.from('checklist_subsections').update({ ...updates, updated_at: new Date().toISOString() }).eq('id', id)
      if (error) throw error
      return jsonResponse({ id, updated: true })
    }

    if (action === 'deleteSubsection') {
      const { error } = await adminClient.from('checklist_subsections').update({ is_active: false }).eq('id', payload.id)
      if (error) throw error
      return jsonResponse({ id: payload.id, deleted: true })
    }

    if (action === 'listQuestions') {
      let q = adminClient.from('checklist_questions').select('*').order('sort_order')
      if (payload.subsection_id) q = q.eq('subsection_id', payload.subsection_id)
      const { data, error } = await q
      if (error) throw error
      return jsonResponse({ questions: data ?? [] })
    }

    if (action === 'createQuestion') {
      const { error, data } = await adminClient.from('checklist_questions').insert(payload).select().single()
      if (error) throw error
      return jsonResponse({ id: data.id, created: true }, 201)
    }

    if (action === 'updateQuestion') {
      const { id, ...updates } = payload
      const { error } = await adminClient.from('checklist_questions').update({ ...updates, updated_at: new Date().toISOString() }).eq('id', id)
      if (error) throw error
      return jsonResponse({ id, updated: true })
    }

    if (action === 'deleteQuestion') {
      const { error } = await adminClient.from('checklist_questions').update({ is_active: false }).eq('id', payload.id)
      if (error) throw error
      return jsonResponse({ id: payload.id, deleted: true })
    }

    // ── PROMPTS (super_admin only) ─────────────────────────────────────────────

    if (['listPrompts', 'getPromptHistory', 'savePrompt', 'revertPrompt'].includes(action)) {
      if (!SUPER_ADMIN.has(callerRole)) return errResponse('Super admin access required', 403)

      if (action === 'listPrompts') {
        const { data, error } = await adminClient.from('prompt_templates').select('*').eq('is_active', true).order('prompt_key')
        if (error) throw error
        return jsonResponse({ prompts: data ?? [] })
      }

      if (action === 'getPromptHistory') {
        const { data, error } = await adminClient.from('prompt_templates')
          .select('id, version, is_active, notes, created_at')
          .eq('prompt_key', payload.prompt_key)
          .order('version', { ascending: false })
        if (error) throw error
        return jsonResponse({ history: data ?? [] })
      }

      if (action === 'savePrompt') {
        const { prompt_key, content, notes, prompt_type = 'system' } = payload
        const { data: latest } = await adminClient.from('prompt_templates')
          .select('version').eq('prompt_key', prompt_key).order('version', { ascending: false }).limit(1).single()
        const nextVersion = (latest?.version ?? 0) + 1
        await adminClient.from('prompt_templates').update({ is_active: false }).eq('prompt_key', prompt_key).eq('is_active', true)
        const { error, data } = await adminClient.from('prompt_templates').insert({
          prompt_key, prompt_type, version: nextVersion, content, notes, is_active: true, created_by: user.id,
        }).select().single()
        if (error) throw error
        await adminClient.from('config_audit_log').insert({
          table_name: 'prompt_templates', record_id: data.id, field_name: 'saved',
          new_value: { prompt_key, version: nextVersion }, changed_by: user.id,
        })
        return jsonResponse({ id: data.id, prompt_key, version: nextVersion, saved: true })
      }

      if (action === 'revertPrompt') {
        const { prompt_key, version } = payload
        await adminClient.from('prompt_templates').update({ is_active: false }).eq('prompt_key', prompt_key).eq('is_active', true)
        const { error } = await adminClient.from('prompt_templates').update({ is_active: true }).eq('prompt_key', prompt_key).eq('version', version)
        if (error) throw error
        return jsonResponse({ prompt_key, version, reverted: true })
      }
    }

    // ── KNOWLEDGE BASE (super_admin only) — knowledge_base table ──────────────

    if (['listKbEntries', 'createKbEntry', 'updateKbEntry', 'deleteKbEntry'].includes(action)) {
      if (!SUPER_ADMIN.has(callerRole)) return errResponse('Super admin access required', 403)

      if (action === 'listKbEntries') {
        let q = adminClient.from('knowledge_base')
          .select('id, title, content, category, principle_id, is_active, created_at, updated_at')
          .order('category').order('title')
        if (!payload.include_inactive) q = q.eq('is_active', true)
        const { data, error } = await q
        if (error) throw error
        return jsonResponse({ entries: data ?? [] })
      }

      if (action === 'createKbEntry') {
        const { title, content, category, principle_id } = payload
        const { data, error } = await adminClient.from('knowledge_base')
          .insert({ title, content, category, principle_id, is_active: true })
          .select('id, title, content, category, principle_id, is_active, created_at, updated_at')
          .single()
        if (error) throw error
        return jsonResponse({ entry: data }, 201)
      }

      if (action === 'updateKbEntry') {
        const { id, ...updates } = payload
        updates.updated_at = new Date().toISOString()
        const { error } = await adminClient.from('knowledge_base').update(updates).eq('id', id)
        if (error) throw error
        return jsonResponse({ id, updated: true })
      }

      if (action === 'deleteKbEntry') {
        const { error } = await adminClient.from('knowledge_base').delete().eq('id', payload.id)
        if (error) throw error
        return jsonResponse({ id: payload.id, deleted: true })
      }
    }

    // ── ANALYTICS ──────────────────────────────────────────────────────────────

    if (action === 'getAnalyticsSummary') {
      const [
        { count: total },
        { count: approved },
        { count: rejected },
        { count: deferred },
        { count: thisMonth },
      ] = await Promise.all([
        adminClient.from('reviews').select('*', { count: 'exact', head: true }),
        adminClient.from('reviews').select('*', { count: 'exact', head: true }).eq('decision', 'approved'),
        adminClient.from('reviews').select('*', { count: 'exact', head: true }).eq('decision', 'rejected'),
        adminClient.from('reviews').select('*', { count: 'exact', head: true }).eq('decision', 'deferred'),
        adminClient.from('reviews').select('*', { count: 'exact', head: true }).gte('created_at', new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString()),
      ])
      const totalN = total ?? 0
      const approvedN = approved ?? 0
      return jsonResponse({
        total_reviews: totalN,
        pending_reviews: Math.max(0, totalN - approvedN - (rejected ?? 0) - (deferred ?? 0)),
        approved_reviews: approvedN,
        rejected_reviews: rejected ?? 0,
        deferred_reviews: deferred ?? 0,
        reviews_this_month: thisMonth ?? 0,
        approval_rate: totalN > 0 ? Math.round(approvedN / totalN * 1000) / 10 : null,
      })
    }

    if (action === 'getDomainAnalytics') {
      const { data: domains } = await adminClient.from('domains').select('slug, name').eq('is_active', true).order('seq_number')
      const results = []
      for (const d of domains ?? []) {
        const { data: scores } = await adminClient.from('domain_scores').select('rag_score').eq('domain_slug', d.slug)
        const rags = (scores ?? []).map((s: any) => s.rag_score).filter(Boolean)
        const avg = rags.length > 0 ? rags.reduce((a: number, b: number) => a + b, 0) / rags.length : null
        results.push({ domain_slug: d.slug, domain_name: d.name, avg_score: avg ? Math.round(avg * 100) / 100 : null, total_reviews: rags.length, blocker_count: 0 })
      }
      return jsonResponse({ domains: results })
    }

    if (action === 'getRecentReviews') {
      const limit = payload.limit ?? 20
      const { data, error } = await adminClient.from('reviews')
        .select('id, solution_name, status, decision, aggregate_rag_score, llm_model, created_at, agent_run_at')
        .order('created_at', { ascending: false }).limit(limit)
      if (error) throw error
      return jsonResponse({ reviews: data ?? [] })
    }

    // ── AUDIT LOG ──────────────────────────────────────────────────────────────

    if (action === 'getAuditLog') {
      const { limit = 100, offset = 0 } = payload
      const { data, error } = await adminClient.from('config_audit_log')
        .select('*').order('changed_at', { ascending: false }).range(offset, offset + limit - 1)
      if (error) throw error
      return jsonResponse({ audit_log: data ?? [] })
    }

    return errResponse(`Unknown action: ${action}`, 400)

  } catch (err: any) {
    console.error('[admin-api] error:', err)
    return errResponse(err.message ?? 'Internal server error', 500)
  }
})
