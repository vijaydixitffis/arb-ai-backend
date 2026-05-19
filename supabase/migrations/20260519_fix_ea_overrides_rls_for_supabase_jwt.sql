-- Fix ea_overrides RLS to allow EA/arb_admin users authenticated via Supabase JWT.
--
-- Root cause: only policy is ea_overrides_service_role (roles: {service_role}).
-- Frontend EA users authenticate via JWT → Postgres role = 'authenticated', not
-- 'service_role' → all INSERT/UPDATE/DELETE blocked by RLS.
--
-- Fix: add a permissive policy for enterprise_architect and arb_admin roles using
-- the same COALESCE pattern as the reviews fix, so both Python backend sessions
-- (app.current_user_id) and frontend JWT sessions (auth.uid()) are covered.

CREATE POLICY "EA can manage ea_overrides" ON public.ea_overrides
FOR ALL USING (
  EXISTS (
    SELECT 1 FROM public.users
    WHERE users.id = COALESCE(
        NULLIF(current_setting('app.current_user_id', true), '')::uuid,
        auth.uid()
      )
      AND users.role = ANY (ARRAY['enterprise_architect', 'arb_admin'])
  )
) WITH CHECK (
  EXISTS (
    SELECT 1 FROM public.users
    WHERE users.id = COALESCE(
        NULLIF(current_setting('app.current_user_id', true), '')::uuid,
        auth.uid()
      )
      AND users.role = ANY (ARRAY['enterprise_architect', 'arb_admin'])
  )
);
