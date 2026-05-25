-- ============================================================================
-- Fix adr_register RLS — consistent with project identity resolution pattern.
-- 2026-05-25
--
-- Issues fixed:
--  1. INSERT broken — createAdr never sets owner_user_id, so NULL = auth.uid()
--     always fails. Add trigger to auto-set owner_user_id + allow EA/Admin
--     to create on behalf of others.
--  2. All policies used auth.uid() only — apply the established project pattern:
--     COALESCE(NULLIF(current_setting('app.current_user_id',true),'')::uuid, auth.uid())
--     so Python backend sessions (app.current_user_id) and Supabase JWT sessions
--     (auth.uid()) both resolve correctly.
--  3. EA UPDATE policy missing explicit WITH CHECK — added.
-- ============================================================================

BEGIN;

-- ── Helper macro (inline function to keep policies readable) ──────────────────
CREATE OR REPLACE FUNCTION public.current_actor_id() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER AS $$
  SELECT COALESCE(
    NULLIF(current_setting('app.current_user_id', true), '')::uuid,
    auth.uid()
  )
$$;

-- ── Trigger: auto-set owner_user_id on INSERT if caller does not supply it ────
CREATE OR REPLACE FUNCTION public.adr_register_set_owner_id()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  IF NEW.owner_user_id IS NULL THEN
    NEW.owner_user_id := public.current_actor_id();
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_adr_register_set_owner ON public.adr_register;
CREATE TRIGGER trg_adr_register_set_owner
  BEFORE INSERT ON public.adr_register
  FOR EACH ROW EXECUTE FUNCTION public.adr_register_set_owner_id();

-- ── Drop all existing policies ────────────────────────────────────────────────
DROP POLICY IF EXISTS adr_register_select       ON public.adr_register;
DROP POLICY IF EXISTS adr_register_insert       ON public.adr_register;
DROP POLICY IF EXISTS adr_register_update_owner ON public.adr_register;
DROP POLICY IF EXISTS adr_register_update_ea    ON public.adr_register;
DROP POLICY IF EXISTS adr_register_delete       ON public.adr_register;

-- ── SELECT — any authenticated user can read all ADRs ────────────────────────
CREATE POLICY adr_register_select ON public.adr_register
  FOR SELECT TO authenticated
  USING (true);

-- ── INSERT — SA creates their own; EA/Admin may create for anyone ─────────────
-- Trigger auto-fills owner_user_id, so the WITH CHECK below validates it.
CREATE POLICY adr_register_insert ON public.adr_register
  FOR INSERT TO authenticated
  WITH CHECK (
    -- actor is the owner (SA self-authors)
    owner_user_id = public.current_actor_id()
    OR
    -- EA or Admin may create ADRs on behalf of anyone
    EXISTS (
      SELECT 1 FROM public.users
      WHERE id = public.current_actor_id()
        AND role IN ('enterprise_architect', 'arb_admin', 'super_admin')
    )
  );

-- ── UPDATE (owner) — SA edits own ADRs while still in draft or proposed ───────
CREATE POLICY adr_register_update_owner ON public.adr_register
  FOR UPDATE TO authenticated
  USING (
    owner_user_id = public.current_actor_id()
    AND status IN ('draft', 'proposed')
  )
  WITH CHECK (
    -- SA cannot re-assign ownership when editing
    owner_user_id = public.current_actor_id()
  );

-- ── UPDATE (EA / Admin) — governance decisions on any ADR ────────────────────
CREATE POLICY adr_register_update_ea ON public.adr_register
  FOR UPDATE TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.users
      WHERE id = public.current_actor_id()
        AND role IN ('enterprise_architect', 'arb_admin', 'super_admin')
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.users
      WHERE id = public.current_actor_id()
        AND role IN ('enterprise_architect', 'arb_admin', 'super_admin')
    )
  );

-- ── DELETE — admin only ───────────────────────────────────────────────────────
CREATE POLICY adr_register_delete ON public.adr_register
  FOR DELETE TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.users
      WHERE id = public.current_actor_id()
        AND role IN ('arb_admin', 'super_admin')
    )
  );

COMMIT;
