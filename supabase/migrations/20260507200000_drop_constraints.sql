ALTER TABLE public.domain_reviews DROP CONSTRAINT IF EXISTS chk_dr_domain;
ALTER TABLE public.actions DROP CONSTRAINT IF EXISTS actions_proposed_due_date_check;
ALTER TABLE public.adrs DROP CONSTRAINT IF EXISTS adrs_proposed_target_date_check;
ALTER TABLE public.recommendations ADD COLUMN IF NOT EXISTS applies_to_finding_id text;
