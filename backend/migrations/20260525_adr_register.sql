-- ============================================================================
-- ADR Register — system of record table (PostgreSQL / Python backend)
-- 2026-05-25
-- ============================================================================

-- ── Sequence for human-readable ADR-NNN identifiers ─────────────────────────
CREATE SEQUENCE IF NOT EXISTS adr_register_seq START 1;

-- ── Core table ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS adr_register (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    adr_id         TEXT        NOT NULL UNIQUE
                               DEFAULT 'ADR-' || LPAD(nextval('adr_register_seq')::text, 3, '0'),
    title          TEXT        NOT NULL,
    status         VARCHAR(20) NOT NULL DEFAULT 'draft'
                               CHECK (status IN (
                                   'draft','proposed','accepted','conditional',
                                   'deferred','rejected','published','evolving')),
    stage          VARCHAR(20) NOT NULL DEFAULT 'authored'
                               CHECK (stage IN ('authored','in_review','published','evolving')),
    owner_name     TEXT        NOT NULL,
    owner_role     VARCHAR(30) NOT NULL DEFAULT 'solution_architect',
    owner_user_id  UUID        REFERENCES users(id) ON DELETE SET NULL,
    context        TEXT,
    decision       TEXT,
    rationale      TEXT,
    tags           TEXT[]      NOT NULL DEFAULT '{}',
    domain         TEXT,
    review_date    DATE,
    decided_at     TIMESTAMPTZ,
    superseded_by  TEXT        REFERENCES adr_register(adr_id) ON DELETE SET NULL,
    linked_arb_ref TEXT,
    options        JSONB       NOT NULL DEFAULT '[]',
    consequences   JSONB       NOT NULL DEFAULT '{"pos":[],"neg":[]}',
    links          JSONB       NOT NULL DEFAULT '[]',
    activity       JSONB       NOT NULL DEFAULT '[]',
    comment_count  INTEGER     NOT NULL DEFAULT 0,
    created_by     UUID        REFERENCES users(id) ON DELETE SET NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_adr_register_status     ON adr_register(status);
CREATE INDEX IF NOT EXISTS idx_adr_register_stage      ON adr_register(stage);
CREATE INDEX IF NOT EXISTS idx_adr_register_owner_user ON adr_register(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_adr_register_tags       ON adr_register USING gin(tags);
CREATE INDEX IF NOT EXISTS idx_adr_register_created_at ON adr_register(created_at DESC);

-- ── Auto-update updated_at ───────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION adr_register_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$;

DROP TRIGGER IF EXISTS trg_adr_register_updated_at ON adr_register;
CREATE TRIGGER trg_adr_register_updated_at
    BEFORE UPDATE ON adr_register
    FOR EACH ROW EXECUTE FUNCTION adr_register_set_updated_at();
