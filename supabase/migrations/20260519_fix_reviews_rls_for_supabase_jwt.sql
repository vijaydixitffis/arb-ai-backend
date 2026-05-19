-- Fix reviews UPDATE policy to work with Supabase JWT auth (auth.uid()) as well
-- as the Python backend's custom session variable (app.current_user_id).
--
-- Root cause: all prior migrations used current_setting('app.current_user_id', true)
-- exclusively. The frontend Supabase client authenticates via JWT, making auth.uid()
-- the correct identity — current_setting returns NULL, silently blocking all frontend
-- updates (openForEA, SA retry, etc.).
--
-- Fix: COALESCE(NULLIF(current_setting('app.current_user_id', true), '')::uuid, auth.uid())
-- resolves to app.current_user_id when the Python backend sets it, otherwise falls back
-- to auth.uid() for frontend Supabase JWT sessions.

DROP POLICY IF EXISTS "Users can update reviews based on role and status" ON public.reviews;
DROP POLICY IF EXISTS "Users can update reviews based on role and status (check)" ON public.reviews;

CREATE POLICY "Users can update reviews based on role and status" ON public.reviews
FOR UPDATE USING (
  (EXISTS (
    SELECT 1 FROM public.users
    WHERE users.id = COALESCE(
        NULLIF(current_setting('app.current_user_id', true), '')::uuid,
        auth.uid()
      )
      AND users.role = ANY (ARRAY['enterprise_architect', 'arb_admin'])
  ))
  OR (
    sa_user_id = COALESCE(
      NULLIF(current_setting('app.current_user_id', true), '')::uuid,
      auth.uid()
    )
    AND status = ANY (ARRAY[
      'draft', 'drafting', 'queued', 'pending', 'submitted',
      'review_ready', 'returned', 'review_pending', 'agent_failed'
    ])
    AND EXISTS (
      SELECT 1 FROM public.users
      WHERE users.id = COALESCE(
          NULLIF(current_setting('app.current_user_id', true), '')::uuid,
          auth.uid()
        )
        AND users.role = 'solution_architect'
    )
  )
);

CREATE POLICY "Users can update reviews based on role and status (check)" ON public.reviews
FOR UPDATE WITH CHECK (
  (EXISTS (
    SELECT 1 FROM public.users
    WHERE users.id = COALESCE(
        NULLIF(current_setting('app.current_user_id', true), '')::uuid,
        auth.uid()
      )
      AND users.role = ANY (ARRAY['enterprise_architect', 'arb_admin'])
  ))
  OR (
    sa_user_id = COALESCE(
      NULLIF(current_setting('app.current_user_id', true), '')::uuid,
      auth.uid()
    )
    AND status = ANY (ARRAY[
      'draft', 'drafting', 'queued', 'pending', 'submitted',
      'review_ready', 'returned', 'review_pending', 'agent_failed'
    ])
    AND EXISTS (
      SELECT 1 FROM public.users
      WHERE users.id = COALESCE(
          NULLIF(current_setting('app.current_user_id', true), '')::uuid,
          auth.uid()
        )
        AND users.role = 'solution_architect'
    )
  )
);
