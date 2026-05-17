-- =====================================================
-- SYNC SUPABASE CONSTRAINTS TO MATCH LOCAL POSTGRES
-- Generated: 2026-05-08
-- Aligns Supabase check constraints, foreign keys, and columns
-- with the authoritative local postgres schema.
-- =====================================================

-- =========================
-- STEP 1: DROP EXTRA SUPABASE CONSTRAINTS (not in local postgres)
-- =========================

-- actions: drop Supabase-only constraints
ALTER TABLE public.actions DROP CONSTRAINT IF EXISTS actions_priority_check;
ALTER TABLE public.actions DROP CONSTRAINT IF EXISTS chk_actions_type;

-- adrs: drop Supabase-only constraints
ALTER TABLE public.adrs DROP CONSTRAINT IF EXISTS chk_adrs_waiver_expiry;

-- ea_review: drop Supabase-only constraints (decision enums and FK not in local)
ALTER TABLE public.ea_review DROP CONSTRAINT IF EXISTS ea_review_ea_decision_check;
ALTER TABLE public.ea_review DROP CONSTRAINT IF EXISTS ea_review_final_decision_check;
ALTER TABLE public.ea_review DROP CONSTRAINT IF EXISTS ea_review_review_id_fkey;

-- nfr_scorecard: drop Supabase-only constraints
ALTER TABLE public.nfr_scorecard DROP CONSTRAINT IF EXISTS chk_nfr_category;
ALTER TABLE public.nfr_scorecard DROP CONSTRAINT IF EXISTS chk_nfr_rag_label;

-- recommendations: drop Supabase-specific names, will re-add with local postgres names
ALTER TABLE public.recommendations DROP CONSTRAINT IF EXISTS chk_rec_domain;
ALTER TABLE public.recommendations DROP CONSTRAINT IF EXISTS chk_rec_priority;


-- =========================
-- STEP 2: ADD MISSING CONSTRAINTS (matching local postgres exactly)
-- Using NOT VALID to avoid failures on existing data; validates new rows only.
-- =========================

-- actions: status enum check
ALTER TABLE public.actions ADD CONSTRAINT actions_status_check
  CHECK (status = ANY (ARRAY[
    'open'::text, 'in_progress'::text, 'evidence_submitted'::text,
    'closed'::text, 'rejected'::text, 'waived'::text
  ])) NOT VALID;

-- adrs: status enum check
ALTER TABLE public.adrs ADD CONSTRAINT adrs_status_check
  CHECK (status = ANY (ARRAY[
    'proposed'::text, 'accepted'::text, 'conditional'::text,
    'rejected'::text, 'superseded'::text
  ])) NOT VALID;

-- domain_reviews: agent status enum
ALTER TABLE public.domain_reviews ADD CONSTRAINT chk_dr_agent_status
  CHECK (agent_status = ANY (ARRAY[
    'waiting'::text, 'running'::text, 'done'::text, 'failed'::text, 'skipped'::text
  ])) NOT VALID;

-- domain_reviews: evidence quality enum (nullable)
ALTER TABLE public.domain_reviews ADD CONSTRAINT chk_dr_evidence_quality
  CHECK ((evidence_quality IS NULL) OR (evidence_quality = ANY (ARRAY[
    'complete'::text, 'partial'::text, 'insufficient'::text, 'absent'::text
  ]))) NOT VALID;

-- domain_reviews: rag label enum (nullable)
ALTER TABLE public.domain_reviews ADD CONSTRAINT chk_dr_rag_label
  CHECK ((rag_label IS NULL) OR (rag_label = ANY (ARRAY[
    'green'::text, 'amber'::text, 'red'::text, 'waiver'::text
  ]))) NOT VALID;

-- domain_reviews: rag score range (nullable)
ALTER TABLE public.domain_reviews ADD CONSTRAINT chk_dr_rag_score
  CHECK ((rag_score IS NULL) OR ((rag_score >= 1) AND (rag_score <= 5))) NOT VALID;

-- domain_reviews: domain readiness enum (nullable)
ALTER TABLE public.domain_reviews ADD CONSTRAINT chk_dr_readiness
  CHECK ((domain_readiness IS NULL) OR (domain_readiness = ANY (ARRAY[
    'approve'::text, 'approve_with_conditions'::text, 'defer'::text, 'reject'::text
  ]))) NOT VALID;

-- domain_scores: score range 1-5
ALTER TABLE public.domain_scores ADD CONSTRAINT domain_scores_score_check
  CHECK (((score >= 1) AND (score <= 5))) NOT VALID;

-- findings: rag score range (nullable)
ALTER TABLE public.findings ADD CONSTRAINT chk_findings_rag
  CHECK ((rag_score IS NULL) OR ((rag_score >= 1) AND (rag_score <= 5))) NOT VALID;

-- findings: severity enum
ALTER TABLE public.findings ADD CONSTRAINT findings_severity_check
  CHECK (severity = ANY (ARRAY[
    'blocker'::text, 'high'::text, 'medium'::text, 'low'::text,
    'info'::text, 'minor'::text, 'major'::text, 'critical'::text
  ])) NOT VALID;

-- nfr_scorecard: rag score range 1-5
ALTER TABLE public.nfr_scorecard ADD CONSTRAINT chk_nfr_rag_score
  CHECK (((rag_score >= 1) AND (rag_score <= 5))) NOT VALID;

-- recommendations: priority enum (using local postgres constraint name)
ALTER TABLE public.recommendations ADD CONSTRAINT recommendations_priority_check
  CHECK (priority = ANY (ARRAY[
    'critical'::text, 'high'::text, 'medium'::text, 'low'::text
  ])) NOT VALID;


-- =========================
-- STEP 3: ADD MISSING COLUMN
-- =========================

-- recommendations: kb_source_ref array column present in local postgres but missing in Supabase
ALTER TABLE public.recommendations ADD COLUMN IF NOT EXISTS kb_source_ref text[];


-- =========================
-- STEP 4: FIX COLUMN NULLABILITY DIFFERENCES
-- =========================

-- ea_review.created_at: local postgres has this as NOT NULL
ALTER TABLE public.ea_review ALTER COLUMN created_at SET NOT NULL;
