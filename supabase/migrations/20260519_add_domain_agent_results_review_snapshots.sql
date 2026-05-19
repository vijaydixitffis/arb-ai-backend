-- Migration: 20260519_add_domain_agent_results_review_snapshots
-- Purpose: Add domain_agent_results and review_snapshots tables that were
--          referenced in the security review but had no confirmed migration.
--          domain_agent_results stores the raw per-domain LLM output for
--          auditability and replay. review_snapshots captures point-in-time
--          review state on key lifecycle events for governance traceability.

BEGIN;

-- ── 1. domain_agent_results ──────────────────────────────────────────────────
-- Stores the raw LLM payload returned by each domain agent run.
-- One row per (review_id, domain_slug, run_at) so reruns are appended, not
-- overwritten, giving a full history of agent iterations.

CREATE TABLE IF NOT EXISTS public.domain_agent_results (
    id                 uuid                     DEFAULT gen_random_uuid() NOT NULL,
    review_id          uuid                     NOT NULL,
    domain_slug        text                     NOT NULL,
    agent_model        text,
    raw_response       jsonb,
    parsed_ok          boolean                  NOT NULL DEFAULT false,
    parse_error        text,
    tokens_used        integer,
    processing_time_ms integer,
    run_at             timestamp with time zone DEFAULT now(),
    created_at         timestamp with time zone DEFAULT now(),
    CONSTRAINT domain_agent_results_pkey PRIMARY KEY (id),
    CONSTRAINT domain_agent_results_review_id_fkey
        FOREIGN KEY (review_id) REFERENCES public.reviews (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_domain_agent_results_review_id
    ON public.domain_agent_results (review_id);

CREATE INDEX IF NOT EXISTS idx_domain_agent_results_review_domain
    ON public.domain_agent_results (review_id, domain_slug);

-- ── 2. review_snapshots ──────────────────────────────────────────────────────
-- Captures an immutable snapshot of the full review payload at key lifecycle
-- events (agent_complete, ea_decision, returned, approved, etc.).
-- snapshot_version increments per review so history can be replayed in order.

CREATE TABLE IF NOT EXISTS public.review_snapshots (
    id               uuid                     DEFAULT gen_random_uuid() NOT NULL,
    review_id        uuid                     NOT NULL,
    snapshot_version integer                  NOT NULL DEFAULT 1,
    trigger_event    text                     NOT NULL,
    review_status    text,
    review_decision  text,
    snapshot_data    jsonb,
    created_by       uuid,
    created_at       timestamp with time zone DEFAULT now(),
    CONSTRAINT review_snapshots_pkey PRIMARY KEY (id),
    CONSTRAINT review_snapshots_review_id_fkey
        FOREIGN KEY (review_id) REFERENCES public.reviews (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_review_snapshots_review_id
    ON public.review_snapshots (review_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_review_snapshots_review_version
    ON public.review_snapshots (review_id, snapshot_version);

-- ── 3. RLS policies ──────────────────────────────────────────────────────────
-- Use the same coarse policy as audit_log: service_role bypasses RLS;
-- authenticated users can only read rows belonging to their own reviews.

ALTER TABLE public.domain_agent_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.review_snapshots     ENABLE ROW LEVEL SECURITY;

-- Service role has unrestricted access (used by backend API)
CREATE POLICY "service_role_domain_agent_results"
    ON public.domain_agent_results
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_review_snapshots"
    ON public.review_snapshots
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Authenticated users may read snapshots for reviews they own (sa_user_id match)
CREATE POLICY "authenticated_read_review_snapshots"
    ON public.review_snapshots
    FOR SELECT
    TO authenticated
    USING (
        review_id IN (
            SELECT id FROM public.reviews
            WHERE sa_user_id = auth.uid()
        )
    );

COMMIT;
