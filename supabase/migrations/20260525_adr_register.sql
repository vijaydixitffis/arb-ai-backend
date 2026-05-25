-- ============================================================================
-- ADR Register — system of record table (Supabase / direct REST API)
-- 2026-05-25
-- ============================================================================

BEGIN;

-- ── Sequence for human-readable ADR-NNN identifiers ─────────────────────────
CREATE SEQUENCE IF NOT EXISTS adr_register_seq START 1;

-- ── Core table ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.adr_register (
    id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    adr_id         text        NOT NULL UNIQUE
                               DEFAULT 'ADR-' || LPAD(nextval('adr_register_seq')::text, 3, '0'),
    title          text        NOT NULL,
    status         varchar(20) NOT NULL DEFAULT 'draft'
                               CHECK (status IN (
                                   'draft','proposed','accepted','conditional',
                                   'deferred','rejected','published','evolving')),
    stage          varchar(20) NOT NULL DEFAULT 'authored'
                               CHECK (stage IN ('authored','in_review','published','evolving')),
    owner_name     text        NOT NULL,
    owner_role     varchar(30) NOT NULL DEFAULT 'solution_architect',
    owner_user_id  uuid        REFERENCES public.users(id) ON DELETE SET NULL,
    context        text,
    decision       text,
    rationale      text,
    tags           text[]      NOT NULL DEFAULT '{}',
    domain         text,
    review_date    date,
    decided_at     timestamptz,
    superseded_by  text        REFERENCES public.adr_register(adr_id) ON DELETE SET NULL,
    linked_arb_ref text,
    options        jsonb       NOT NULL DEFAULT '[]',
    consequences   jsonb       NOT NULL DEFAULT '{"pos":[],"neg":[]}',
    links          jsonb       NOT NULL DEFAULT '[]',
    activity       jsonb       NOT NULL DEFAULT '[]',
    comment_count  integer     NOT NULL DEFAULT 0,
    created_by     uuid        REFERENCES public.users(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_adr_register_status     ON public.adr_register(status);
CREATE INDEX IF NOT EXISTS idx_adr_register_stage      ON public.adr_register(stage);
CREATE INDEX IF NOT EXISTS idx_adr_register_owner_user ON public.adr_register(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_adr_register_tags       ON public.adr_register USING gin(tags);
CREATE INDEX IF NOT EXISTS idx_adr_register_created_at ON public.adr_register(created_at DESC);

-- ── Auto-update updated_at ───────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.adr_register_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$;

DROP TRIGGER IF EXISTS trg_adr_register_updated_at ON public.adr_register;
CREATE TRIGGER trg_adr_register_updated_at
    BEFORE UPDATE ON public.adr_register
    FOR EACH ROW EXECUTE FUNCTION public.adr_register_set_updated_at();

-- ── Row Level Security ───────────────────────────────────────────────────────
ALTER TABLE public.adr_register ENABLE ROW LEVEL SECURITY;

-- Any authenticated user can read all ADRs
CREATE POLICY adr_register_select ON public.adr_register
    FOR SELECT TO authenticated
    USING (true);

-- Authors can insert their own ADRs (owner_user_id = calling user)
CREATE POLICY adr_register_insert ON public.adr_register
    FOR INSERT TO authenticated
    WITH CHECK (owner_user_id = auth.uid());

-- Owner can update their own ADRs if still draft/proposed
CREATE POLICY adr_register_update_owner ON public.adr_register
    FOR UPDATE TO authenticated
    USING (
        owner_user_id = auth.uid()
        AND status IN ('draft', 'proposed')
    )
    WITH CHECK (owner_user_id = auth.uid());

-- EA and Admin roles can update status of any ADR (governance decisions)
-- Role is read from public.users.role to avoid JWT claim spoofing
CREATE POLICY adr_register_update_ea ON public.adr_register
    FOR UPDATE TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = auth.uid()
              AND u.role IN ('enterprise_architect','arb_admin','super_admin')
        )
    );

-- Only admins can delete (soft-delete via status change is preferred)
CREATE POLICY adr_register_delete ON public.adr_register
    FOR DELETE TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = auth.uid()
              AND u.role IN ('arb_admin','super_admin')
        )
    );

COMMIT;
