-- Add review_pending and agent_failed to reviews.status allowed values.
--
-- review_pending: one or more domain LLM calls failed (e.g. 503); partial
--                 results are cached in report_json.domain_partial_results.
--                 SA can re-trigger to complete only the failed domains.
-- agent_failed:   whole orchestration failed (already used in code but not
--                 previously in the DB constraint).

-- 1. Drop the old constraint (name from the original backup schema)
ALTER TABLE public.reviews
  DROP CONSTRAINT IF EXISTS valid_status;

-- 2. Re-add with the full allowed set
ALTER TABLE public.reviews
  ADD CONSTRAINT valid_status CHECK (
    status = ANY (ARRAY[
      'drafting'::text,
      'draft'::text,
      'pending'::text,
      'submitted'::text,
      'queued'::text,
      'analysing'::text,
      'review_pending'::text,
      'review_ready'::text,
      'agent_failed'::text,
      'ea_reviewing'::text,
      'ea_review'::text,
      'returned'::text,
      'approved'::text,
      'conditionally_approved'::text,
      'deferred'::text,
      'rejected'::text,
      'closed'::text
    ])
  );

-- 3. Update SA RLS policies to allow SA to read/update review_pending and agent_failed rows
--    (so the "Retry failed domains" button is not blocked by RLS)

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
    AND status = ANY (ARRAY[
      'draft', 'drafting', 'queued', 'pending', 'submitted',
      'review_ready', 'returned', 'review_pending', 'agent_failed'
    ])
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
    AND status = ANY (ARRAY[
      'draft', 'drafting', 'queued', 'pending', 'submitted',
      'review_ready', 'returned', 'review_pending', 'agent_failed'
    ])
    AND EXISTS (
      SELECT 1 FROM public.users
      WHERE users.id = (current_setting('app.current_user_id', true))::uuid
        AND users.role = 'solution_architect'
    )
  )
);
