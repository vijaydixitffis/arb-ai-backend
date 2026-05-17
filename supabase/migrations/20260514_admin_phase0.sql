-- ============================================================================
-- Phase 0: Admin Tables Migration (Supabase)
-- 2026-05-14
-- ============================================================================

-- ── 1. Extend users table ────────────────────────────────────────────────────
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_active      BOOLEAN     NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS last_login_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS created_by     UUID        REFERENCES users(id) ON DELETE SET NULL;

-- ── 2. system_config ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_config (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key           VARCHAR     NOT NULL UNIQUE,
    config_value         JSONB       NOT NULL DEFAULT '{}',
    data_type            VARCHAR     NOT NULL DEFAULT 'string',
    category             VARCHAR     NOT NULL DEFAULT 'general',
    label                VARCHAR     NOT NULL,
    description          TEXT,
    is_editable_by_admin BOOLEAN     NOT NULL DEFAULT true,
    updated_by           UUID        REFERENCES users(id) ON DELETE SET NULL,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE system_config ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Admin can manage system_config" ON system_config
    USING (EXISTS (
        SELECT 1 FROM users WHERE id::text = auth.uid()::text
        AND role IN ('arb_admin', 'super_admin') AND is_active = true
    ));

-- ── 3. prompt_templates ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prompt_templates (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_key  VARCHAR     NOT NULL,
    prompt_type VARCHAR     NOT NULL DEFAULT 'system',
    domain_code VARCHAR,
    version     INTEGER     NOT NULL DEFAULT 1,
    content     TEXT        NOT NULL,
    is_active   BOOLEAN     NOT NULL DEFAULT true,
    notes       TEXT,
    created_by  UUID        REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_key_version ON prompt_templates(prompt_key, version);
CREATE INDEX IF NOT EXISTS idx_prompt_key_active         ON prompt_templates(prompt_key, is_active);

ALTER TABLE prompt_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Super admin can manage prompts" ON prompt_templates
    USING (EXISTS (
        SELECT 1 FROM users WHERE id::text = auth.uid()::text
        AND role = 'super_admin' AND is_active = true
    ));

-- ── 4. config_audit_log ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS config_audit_log (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name    VARCHAR     NOT NULL,
    record_id     VARCHAR     NOT NULL,
    field_name    VARCHAR,
    old_value     JSONB,
    new_value     JSONB,
    changed_by    UUID        REFERENCES users(id) ON DELETE SET NULL,
    changed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    change_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_table_record ON config_audit_log(table_name, record_id);
CREATE INDEX IF NOT EXISTS idx_audit_changed_at   ON config_audit_log(changed_at DESC);

ALTER TABLE config_audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Admin can read audit log" ON config_audit_log
    FOR SELECT USING (EXISTS (
        SELECT 1 FROM users WHERE id::text = auth.uid()::text
        AND role IN ('arb_admin', 'super_admin') AND is_active = true
    ));
CREATE POLICY "System inserts audit log" ON config_audit_log
    FOR INSERT WITH CHECK (true);

-- ── 6. Seed: system_config defaults ─────────────────────────────────────────
INSERT INTO system_config (config_key, config_value, data_type, category, label, description, is_editable_by_admin) VALUES
('llm.provider',          '"gemini"',                    'select',  'llm',      'LLM Provider',           'AI provider to use (gemini | openai | openrouter)',                 true),
('llm.gemini_model',      '"gemini-2.5-flash-lite"',     'string',  'llm',      'Gemini Model',           'Gemini model ID',                                                   true),
('llm.openai_model',      '"gpt-4o"',                    'string',  'llm',      'OpenAI Model',           'OpenAI model ID',                                                   true),
('llm.openrouter_model',  '"openai/gpt-oss-120b:free"',  'string',  'llm',      'OpenRouter Model',       'OpenRouter model identifier',                                       true),
('llm.temperature',       '0.3',                         'number',  'llm',      'Temperature',            'Sampling temperature 0.0–2.0',                                     true),
('llm.max_tokens',        '8192',                        'number',  'llm',      'Max Tokens',             'Maximum tokens per LLM response',                                  true),
('llm.use_mock',          'false',                       'boolean', 'llm',      'Use Mock LLM',           'Bypass real LLM and use Bank EDMS fixture data',                   true),
('agent.max_retries',              '2',     'number', 'agent', 'Max Retries',              'Total LLM call attempts per domain (1 initial + retries)',           true),
('agent.retry_delay_seconds',      '10.0',  'number', 'agent', 'Retry Delay (s)',           'Seconds between retry attempts',                                     true),
('agent.domain_delay_seconds',     '0.5',   'number', 'agent', 'Domain Call Delay (s)',     'Delay between sequential domain calls for rate limiting',            true),
('agent.domain_temperature',       '0.5',   'number', 'agent', 'Domain LLM Temperature',    'Sampling temperature for domain validation agents (0.0–2.0)',         true),
('agent.domain_max_tokens',        '16384', 'number', 'agent', 'Domain LLM Max Tokens',     'Max tokens per domain agent LLM response',                           true),
('agent.kb_content_scale',         '1.0',   'number', 'agent', 'KB Content Scale',          'Default content scale passed to domain agents (0.1–2.0)',            true),
('agent.kb_chunk_limit',           '15',    'number', 'agent', 'KB Chunk Limit',            'Max artefact chunks retrieved per domain call (before scaling)',      true),
('agent.kb_max_results',           '8',     'number', 'agent', 'KB Domain Results',         'Max KB documents retrieved for the specific domain per call',         true),
('agent.kb_max_results_general',   '4',     'number', 'agent', 'KB General Results',        'Max general (cross-domain) KB documents retrieved per call',          true),
('agent.content_scale_on_retry',   '0.75',  'number', 'agent', 'Content Scale on Retry',    'KB+artefact content reduction factor applied on retry attempts',      true),
('workflow.session_timeout_minutes', '5',   'number',  'workflow', 'Session Timeout (min)', 'Inactivity timeout for user sessions',      true),
('workflow.max_upload_size_mb',      '50',  'number',  'workflow', 'Max Upload Size (MB)',  'Maximum file upload size in megabytes',     true),
('workflow.auto_run_agent',          'true','boolean', 'workflow', 'Auto-run Agent',        'Automatically run AI agent after submission', true)
ON CONFLICT (config_key) DO NOTHING;

-- ── 7. Seed: super_admin user ─────────────────────────────────────────────────
INSERT INTO users (email, user_password, role, is_active)
VALUES (
    'super_admin@mail.com',
    '$5$rounds=535000$KnxScXu6Mq3IIQ1D$nM0DaPi7bdQKdIDCm.DPFpKzu4eQ1IrGxgNFH6SKYc4',
    'super_admin',
    true
)
ON CONFLICT (email) DO UPDATE SET role = 'super_admin', is_active = true;

UPDATE users SET is_active = true WHERE role IN ('arb_admin', 'enterprise_architect', 'solution_architect');
