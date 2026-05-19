-- Migration: 20260519_business_nfrs_arch_test_plans
-- Purpose: Reframe BUSINESS_NFRS and BUSINESS_OPERATIONS check_categories and question
--          texts so the LLM assesses whether architecture targets and test plans are
--          defined — not whether test results or evidence exist.
--
-- Root cause: question texts like "Performance and scalability business metrics defined?"
-- and category code BUSINESS_NFRS were being interpreted by the LLM as requiring
-- evidence of completed testing (BUS-F01..F04). Renaming the category and rewording
-- the questions to say "architecture and test plans" steers the LLM to check for
-- planned coverage, not executed test results.

BEGIN;

-- ── 1. Rename check_category codes ──────────────────────────────────────────

UPDATE public.question_registry
SET    check_category = 'BUSINESS_NFRS_ARCH_AND_TEST_PLANS',
       updated_at     = now()
WHERE  frontend_tab   = 'business'
AND    check_category = 'BUSINESS_NFRS';

UPDATE public.question_registry
SET    check_category = 'BUSINESS_OPERATIONS_ARCH_AND_TEST_PLANS',
       updated_at     = now()
WHERE  frontend_tab   = 'business'
AND    check_category = 'BUSINESS_OPERATIONS';

-- ── 2. Reword question texts to "architecture and test plans" framing ────────

-- Performance & scalability: was "business metrics defined?" — now asks for targets
-- and test plan, not test evidence.
UPDATE public.question_registry
SET    question_text = 'Performance and scalability architecture targets and test plans defined?',
       hint_text     = 'Define measurable targets (TPS, concurrent users, response times) and confirm a performance test plan exists — not test results.',
       updated_at    = now()
WHERE  frontend_tab   = 'business'
AND    question_code  = 'bus-nfr-2';

-- Business continuity: clarify architecture + test plan scope, not test execution.
UPDATE public.question_registry
SET    question_text = 'Business continuity architecture and test plan documented?',
       hint_text     = 'Confirm RTO/RPO targets are defined in the architecture and a DR/BC test plan exists — not that tests have been executed.',
       updated_at    = now()
WHERE  frontend_tab   = 'business'
AND    question_code  = 'bus-nfr-3';

-- Operations continuity: same reframe.
UPDATE public.question_registry
SET    question_text = 'Operational continuity architecture and test plan documented?',
       hint_text     = 'Confirm operational continuity design and test plan are present — not that continuity tests have been executed.',
       updated_at    = now()
WHERE  frontend_tab   = 'business'
AND    question_code  = 'bus-ops-4';

-- Accessibility: add explicit question anchored to WCAG plan (not audit results).
INSERT INTO public.question_registry
    (question_code, question_text, frontend_tab, agent_domain, check_category,
     display_group, sort_order, weight, is_mandatory_green, blank_nc_severity,
     na_permitted, hint_text, is_active, schema_version, created_at, updated_at)
SELECT
    'bus-nfr-acc-1',
    'Accessibility architecture and test plan defined (WCAG 2.1 AA)?',
    'business',
    'business',
    'BUSINESS_NFRS_ARCH_AND_TEST_PLANS',
    'NFRs',
    sort_order + 1,
    'advisory',
    false,
    'medium',
    true,
    'Confirm WCAG 2.1 AA targets are included in the architecture and a test plan exists — not that accessibility audits have been completed.',
    true,
    '1.0',
    now(),
    now()
FROM public.question_registry
WHERE question_code = 'bus-nfr-3'
AND   NOT EXISTS (
    SELECT 1 FROM public.question_registry WHERE question_code = 'bus-nfr-acc-1'
);

COMMIT;
