-- Allow SA to update reviews in 'returned' status (when EA returns domains for rework)
DROP POLICY IF EXISTS "Users can update reviews based on role and status" ON public.reviews;
DROP POLICY IF EXISTS "Users can update reviews based on role and status (check)" ON public.reviews;

CREATE POLICY "Users can update reviews based on role and status" ON public.reviews
FOR UPDATE USING (
  (EXISTS (
    SELECT 1 FROM public.users
    WHERE users.id = (current_setting('app.current_user_id', true))::uuid
      AND users.role = ANY (ARRAY['enterprise_architect', 'arb_admin'])
  ))
  OR (
    sa_user_id = (current_setting('app.current_user_id', true))::uuid
    AND status = ANY (ARRAY['draft', 'drafting', 'queued', 'pending', 'submitted', 'review_ready', 'returned'])
    AND EXISTS (
      SELECT 1 FROM public.users
      WHERE users.id = (current_setting('app.current_user_id', true))::uuid
        AND users.role = 'solution_architect'
    )
  )
);

CREATE POLICY "Users can update reviews based on role and status (check)" ON public.reviews
FOR UPDATE WITH CHECK (
  (EXISTS (
    SELECT 1 FROM public.users
    WHERE users.id = (current_setting('app.current_user_id', true))::uuid
      AND users.role = ANY (ARRAY['enterprise_architect', 'arb_admin'])
  ))
  OR (
    sa_user_id = (current_setting('app.current_user_id', true))::uuid
    AND status = ANY (ARRAY['draft', 'drafting', 'queued', 'pending', 'submitted', 'review_ready', 'returned'])
    AND EXISTS (
      SELECT 1 FROM public.users
      WHERE users.id = (current_setting('app.current_user_id', true))::uuid
        AND users.role = 'solution_architect'
    )
  )
);
