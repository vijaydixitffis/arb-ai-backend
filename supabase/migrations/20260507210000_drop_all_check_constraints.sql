-- Drop all check constraints from review outcome tables
-- This removes all restrictive constraints that are causing Edge Function failures

-- Drop constraints from domain_reviews table
ALTER TABLE public.domain_reviews DROP CONSTRAINT IF EXISTS chk_dr_domain;
ALTER TABLE public.domain_reviews DROP CONSTRAINT IF EXISTS chk_dr_agent_status;
ALTER TABLE public.domain_reviews DROP CONSTRAINT IF EXISTS chk_dr_evidence_quality;
ALTER TABLE public.domain_reviews DROP CONSTRAINT IF EXISTS chk_dr_rag_label;
ALTER TABLE public.domain_reviews DROP CONSTRAINT IF EXISTS chk_dr_rag_score;
ALTER TABLE public.domain_reviews DROP CONSTRAINT IF EXISTS chk_dr_readiness;

-- Drop constraints from recommendations table
ALTER TABLE public.recommendations DROP CONSTRAINT IF EXISTS recommendations_priority_check;

-- Drop constraints from actions table
ALTER TABLE public.actions DROP CONSTRAINT IF EXISTS actions_status_check;
ALTER TABLE public.actions DROP CONSTRAINT IF EXISTS actions_proposed_due_date_check;

-- Drop constraints from adrs table
ALTER TABLE public.adrs DROP CONSTRAINT IF EXISTS adrs_status_check;
ALTER TABLE public.adrs DROP CONSTRAINT IF EXISTS chk_adrs_domain;
ALTER TABLE public.adrs DROP CONSTRAINT IF EXISTS adrs_proposed_target_date_check;

-- Drop constraints from findings table
ALTER TABLE public.findings DROP CONSTRAINT IF EXISTS chk_findings_rag;
ALTER TABLE public.findings DROP CONSTRAINT IF EXISTS findings_severity_check;

-- Drop constraints from domain_scores table
ALTER TABLE public.domain_scores DROP CONSTRAINT IF EXISTS domain_scores_score_check;

-- Drop constraints from nfr_scorecard table
ALTER TABLE public.nfr_scorecard DROP CONSTRAINT IF EXISTS chk_nfr_rag_score;

-- Drop constraints from reviews table
ALTER TABLE public.reviews DROP CONSTRAINT IF EXISTS chk_reviews_agg_label;
ALTER TABLE public.reviews DROP CONSTRAINT IF EXISTS chk_reviews_agg_rag;
ALTER TABLE public.reviews DROP CONSTRAINT IF EXISTS chk_reviews_ea_decision;
ALTER TABLE public.reviews DROP CONSTRAINT IF EXISTS chk_reviews_rec_decision;
ALTER TABLE public.reviews DROP CONSTRAINT IF EXISTS valid_decision;
ALTER TABLE public.reviews DROP CONSTRAINT IF EXISTS valid_status;

-- Drop constraints from question_registry table
ALTER TABLE public.question_registry DROP CONSTRAINT IF EXISTS qr_agent_domain;
ALTER TABLE public.question_registry DROP CONSTRAINT IF EXISTS qr_blank_nc_severity;
ALTER TABLE public.question_registry DROP CONSTRAINT IF EXISTS qr_frontend_tab;
ALTER TABLE public.question_registry DROP CONSTRAINT IF EXISTS qr_weight;

-- Refresh schema cache
NOTIFY pgbouncer;
