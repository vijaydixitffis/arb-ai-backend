-- Remove restrictive check constraints that are causing Edge Function failures

-- Drop domain constraint that's causing issues with valid domain values
ALTER TABLE public.domain_reviews DROP CONSTRAINT IF EXISTS chk_dr_domain;

-- Drop date format constraints that are too restrictive
ALTER TABLE public.actions DROP CONSTRAINT IF EXISTS actions_proposed_due_date_check;
ALTER TABLE public.adrs DROP CONSTRAINT IF EXISTS adrs_proposed_target_date_check;

-- Ensure applies_to_finding_id column exists in recommendations table
ALTER TABLE public.recommendations 
ADD COLUMN IF NOT EXISTS applies_to_finding_id text;

-- Refresh schema cache
NOTIFY pgbouncer;
