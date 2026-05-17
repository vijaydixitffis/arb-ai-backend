-- ============================================================
-- Migration: question_registry — ARB design-philosophy reframing
-- Date: 2026-05-06
--
-- Philosophy applied:
--   ARB reviews DESIGN, ARCHITECTURE, and PLANNING — not
--   operational readiness, test results, or deployed state.
--   Evidence = plans, designs, and architectural documents.
--   Not expected: test results, scan output, runbook completeness,
--   or deployed-environment evidence.
--
-- Changes made:
--   1. Rephrase question_text from "implemented/completed/
--      configured/conducted/in place" → "designed/documented/
--      planned/specified/defined".
--   2. Update hint_text to clarify what IS required (the plan or
--      design) and explicitly state what is NOT required (results).
--   3. Promote nfr-ha-4 (DR strategy + DR test plan) to
--      mandatory_green / blocker — absence of a DR strategy and
--      test plan is a design blocker equivalent to missing VAPT plan.
--   4. All security-design questions remain mandatory_green/blocker
--      because absence of the DESIGN (not the implementation) is
--      still a genuine architectural blocker.
-- ============================================================

BEGIN;

-- ── BLOCK 1: Infrastructure Security Design (infra-sec-1 to infra-sec-8) ──────
-- These questions remain mandatory_green/blocker.
-- Rephrased: "implemented/configured/in place" → "designed/documented/specified".

UPDATE public.question_registry SET
  question_text = 'Authentication and AuthZ architecture designed at infra level?',
  hint_text     = 'Requires network-level AuthZ design, service mesh mTLS approach, and ingress authentication specification — configuration output or deployed evidence not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'infra-sec-1';

UPDATE public.question_registry SET
  question_text = 'RBAC design documented for infra / platform level?',
  hint_text     = 'RBAC design must specify roles, permission scope, and service account boundaries — IAM console output or configuration screenshots not required',
  updated_at    = now()
WHERE question_code = 'infra-sec-2';

UPDATE public.question_registry SET
  question_text = 'Key Vault usage designed and specified for secret management at infra level?',
  hint_text     = 'Architecture must show Key Vault (or equivalent) integration approach for all secret classes — vault contents or configuration dumps not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'infra-sec-3';

UPDATE public.question_registry SET
  question_text = 'PKI / Encryption approach designed (TLS, data at rest and in transit)?',
  hint_text     = 'Encryption design must cover data at rest and in transit for all data tiers; certificate issuance approach must be specified — implementation or certificate installation evidence not required',
  updated_at    = now()
WHERE question_code = 'infra-sec-4';

UPDATE public.question_registry SET
  question_text = 'Certificate lifecycle management approach documented?',
  hint_text     = 'Must specify issuing CA, renewal process, rotation strategy, and automation approach — certificate installation proof or expiry screenshots not required',
  updated_at    = now()
WHERE question_code = 'infra-sec-5';

UPDATE public.question_registry SET
  question_text = 'VAPT plan documented with scope, methodology, and timeline for infra level?',
  hint_text     = 'Infra-level VAPT plan is mandatory — must include testing scope, methodology, tooling approach, and a firm planned completion date. VAPT test results are NOT required at ARB stage.',
  updated_at    = now()
WHERE question_code = 'infra-sec-6';

UPDATE public.question_registry SET
  question_text = 'Standards and legal compliance requirements identified and documented for infra level?',
  hint_text     = 'Compliance register must identify applicable standards (e.g. ISO 27001, PCI-DSS) and document how the infra design addresses each — audit evidence or certificates not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'infra-sec-7';

UPDATE public.question_registry SET
  question_text = 'Integration security architecture designed at infra level?',
  hint_text     = 'Security design must cover authentication, authorisation, and encryption for each integration point (mTLS, API gateway auth, network policy) — implementation evidence not required',
  updated_at    = now()
WHERE question_code = 'infra-sec-8';


-- ── BLOCK 2: NFR Security Design (nfr-sec-1 to nfr-sec-8) ────────────────────
-- These questions remain mandatory_green/blocker.
-- Rephrased: "implemented/configured/in place/submitted" → "designed/documented/specified".

UPDATE public.question_registry SET
  question_text = 'Authentication and authorisation scheme designed and documented?',
  hint_text     = 'AuthN/AuthZ design must specify mechanism (OAuth2, OIDC, mTLS, etc.), token handling, and flow — implementation or configuration evidence not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'nfr-sec-1';

UPDATE public.question_registry SET
  question_text = 'RBAC / IAM model designed and documented?',
  hint_text     = 'RBAC model must specify roles, permission boundaries, and service account scope — IAM console screenshots or policy exports not required',
  updated_at    = now()
WHERE question_code = 'nfr-sec-2';

UPDATE public.question_registry SET
  question_text = 'Key Vault usage designed for all application secrets?',
  hint_text     = 'Design must show all secret classes and Key Vault integration approach for the application layer — vault contents or configuration output not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'nfr-sec-3';

UPDATE public.question_registry SET
  question_text = 'PKI / Encryption approach designed (at rest and in transit)?',
  hint_text     = 'Encryption design must cover at-rest and in-transit for all application data tiers — implementation evidence or deployed configuration not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'nfr-sec-4';

UPDATE public.question_registry SET
  question_text = 'Certificate management approach documented?',
  hint_text     = 'Must specify issuing authority, renewal approach, and automated rotation design — certificate installation proof not required',
  updated_at    = now()
WHERE question_code = 'nfr-sec-5';

UPDATE public.question_registry SET
  question_text = 'VAPT plan documented with scope, methodology, and timeline?',
  hint_text     = 'Application-level VAPT plan is mandatory — must include testing scope, methodology, tooling, and a firm planned completion date. VAPT test results are NOT required at ARB stage.',
  updated_at    = now()
WHERE question_code = 'nfr-sec-6';

UPDATE public.question_registry SET
  question_text = 'Standards and legal compliance requirements identified and documented?',
  hint_text     = 'Compliance design register must document applicable standards and how the solution architecture addresses each requirement — audit evidence or certification not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'nfr-sec-7';

UPDATE public.question_registry SET
  question_text = 'Integration security controls designed and specified?',
  hint_text     = 'Security design must cover authentication, authorisation, and encryption per integration — implementation evidence not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'nfr-sec-8';


-- ── BLOCK 3: HA / DR Design (nfr-ha-*) ───────────────────────────────────────

-- nfr-ha-1: Remove "mitigated" (implementation) — replace with "mitigation approach documented"
UPDATE public.question_registry SET
  question_text = 'Single points of failure (SPOF) identified and mitigation approach documented?',
  hint_text     = 'SPOF analysis must identify each SPOF and document the architectural mitigation (redundancy, failover, graceful degradation) — not evidence of remediation completion',
  updated_at    = now()
WHERE question_code = 'nfr-ha-1';

-- nfr-ha-3: Remove "and tested" — failover test results are out of scope at ARB
UPDATE public.question_registry SET
  question_text = 'Failover mechanism designed and documented?',
  hint_text     = 'Failover design must specify mechanism (active-active, active-passive, geo-failover), trigger conditions, and expected recovery behaviour — failover test results are NOT required at ARB stage',
  updated_at    = now()
WHERE question_code = 'nfr-ha-3';

-- nfr-ha-4: Promote to mandatory_green/blocker.
-- DR strategy + test PLAN (not results) are now a mandatory design artefact.
UPDATE public.question_registry SET
  question_text      = 'DR strategy, RPO / RTO targets, and DR test plan documented?',
  hint_text          = 'DR strategy and RTO/RPO targets are mandatory design artefacts. A DR test plan (scope, recovery procedure design, schedule) is also required. DR test results (executed drills, proven RTOs) are NOT required at ARB stage.',
  weight             = 'mandatory_green',
  is_mandatory_green = true,
  blank_nc_severity  = 'blocker',
  updated_at         = now()
WHERE question_code = 'nfr-ha-4';

-- nfr-ha-5: Remove "implemented" — replace with "designed and documented"
UPDATE public.question_registry SET
  question_text = 'Error handling strategy designed and documented?',
  hint_text     = 'Must specify error classification, retry behaviour, dead-letter queue design, and user-facing error approach — implementation evidence not required',
  updated_at    = now()
WHERE question_code = 'nfr-ha-5';

-- nfr-ha-6: Remove "implemented" — replace with "designed and specified"
UPDATE public.question_registry SET
  question_text = 'Self-healing capabilities designed and specified?',
  hint_text     = 'Must describe liveness/readiness probe design, auto-restart policy, and health-check approach — not evidence of a live cluster',
  updated_at    = now()
WHERE question_code = 'nfr-ha-6';

-- nfr-ha-7: Remove "configured" — replace with "designed and documented"
UPDATE public.question_registry SET
  question_text = 'Cache synchronisation strategy designed and documented?',
  hint_text     = 'Must specify cache invalidation approach, consistency model, and failover behaviour — not cache configuration output',
  updated_at    = now()
WHERE question_code = 'nfr-ha-7';


-- ── BLOCK 4: Scalability / Performance (nfr-scalar-*) ────────────────────────

-- nfr-scalar-4: Remove "evidenced" (implies measured/tested) → "capacity approach documented"
UPDATE public.question_registry SET
  question_text = 'Response time target defined and capacity approach to achieve it documented?',
  hint_text     = 'Must define target (e.g. < 3 seconds p95) and document the architectural / capacity approach to achieve it — load test or benchmark results are NOT required at ARB stage',
  updated_at    = now()
WHERE question_code = 'nfr-scalar-4';


-- ── BLOCK 5: DevSecOps Pipeline Design (devops-*) ────────────────────────────

-- devops-1: "compliance verified" → "approach documented"
UPDATE public.question_registry SET
  question_text = '12-Factor App compliance approach documented?',
  hint_text     = 'Must document how each applicable factor is addressed in the design — not a compliance audit report',
  updated_at    = now()
WHERE question_code = 'devops-1';

-- devops-3: "established" implies live — replace with "design and toolset defined"
UPDATE public.question_registry SET
  question_text = 'CI/CD pipeline design and toolset defined?',
  hint_text     = 'Pipeline design must specify stages, tooling, quality gates, and environment promotion strategy — not evidence of a running pipeline',
  updated_at    = now()
WHERE question_code = 'devops-3';

-- devops-4: "configured" → "approach designed"
UPDATE public.question_registry SET
  question_text = 'Identity access management approach designed for the CI/CD pipeline?',
  hint_text     = 'Must specify how pipeline identity (service principals, workload identity) is managed and scoped — not IAM configuration output',
  updated_at    = now()
WHERE question_code = 'devops-4';

-- devops-5: "implemented" → "approach designed and documented"
UPDATE public.question_registry SET
  question_text = 'Secrets and config management approach designed (no-secrets-in-code policy documented)?',
  hint_text     = 'Design must show Key Vault / external secrets operator integration in the pipeline and document the no-secrets-in-code policy — pipeline configuration output not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'devops-5';

-- devops-8: "implemented" → "approach designed"
UPDATE public.question_registry SET
  question_text = 'Templatisation and IaC approach designed?',
  hint_text     = 'Must specify IaC tooling (Terraform, Helm, Bicep, etc.) and template structure — deployed infrastructure evidence not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'devops-8';


-- ── BLOCK 6: SecOps Design (secops-*) ────────────────────────────────────────

-- secops-2: "conducted" → "process designed"
UPDATE public.question_registry SET
  question_text = 'Secure code review process designed and integrated in development workflow?',
  hint_text     = 'Must specify security review gates, security-focused review criteria, and reviewer qualification approach — individual review records not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'secops-2';

-- secops-3: "integrated" → "designed and specified"; hint removes "most recent scan pass"
UPDATE public.question_registry SET
  question_text = 'SAST (static analysis) designed and specified in CI/CD pipeline?',
  hint_text     = 'Must specify SAST tool selected, quality threshold configuration, and pipeline stage — most recent scan results or pass evidence are NOT required at ARB stage',
  updated_at    = now()
WHERE question_code = 'secops-3';

-- secops-4: "implemented" → "approach designed and planned"
UPDATE public.question_registry SET
  question_text = 'DAST (dynamic analysis) approach designed and planned?',
  hint_text     = 'Must specify DAST tooling, scope, target environment, and planned integration stage — DAST execution results are NOT required at ARB stage',
  updated_at    = now()
WHERE question_code = 'secops-4';

-- secops-5: "completed" → "plan documented"; this was asking for VAPT results
UPDATE public.question_registry SET
  question_text = 'Application-level VAPT plan documented (scope, approach, and timeline)?',
  hint_text     = 'Application-level VAPT plan is required — must include scope, methodology, and planned completion date. Distinct from infra-level VAPT (infra-sec-6). VAPT results are NOT required at ARB stage.',
  updated_at    = now()
WHERE question_code = 'secops-5';

-- secops-6: "applied" → "approach designed and documented"
UPDATE public.question_registry SET
  question_text = 'Environment hardening approach designed and documented (OS, container, cluster)?',
  hint_text     = 'Hardening design must specify controls for OS baseline, container image hardening, and cluster configuration — hardening scan output or benchmark results not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'secops-6';

-- secops-7: "implemented" → "approach documented"
UPDATE public.question_registry SET
  question_text = 'Software hardening approach documented (SBOM strategy and dependency pinning design)?',
  hint_text     = 'Must specify SBOM tooling, dependency pinning strategy, and EoS/vulnerability tracking approach — not a live SBOM export',
  updated_at    = now()
WHERE question_code = 'secops-7';

-- secops-8: "reporting in place" → "approach designed"
UPDATE public.question_registry SET
  question_text = 'Security metrics and reporting approach designed?',
  hint_text     = 'Must specify which security metrics will be tracked, reporting cadence, and tooling — not live metric evidence',
  updated_at    = now()
WHERE question_code = 'secops-8';


-- ── BLOCK 7: Engineering Excellence (engex-*) ────────────────────────────────

-- engex-1: "results available and within threshold" → "tooling and thresholds defined"
UPDATE public.question_registry SET
  question_text = 'Static code analysis tooling and quality thresholds defined?',
  hint_text     = 'Must specify tool, coverage or quality gate thresholds, and enforcement point in CI/CD — scan results or current threshold status are NOT required at ARB stage',
  updated_at    = now()
WHERE question_code = 'engex-1';

-- engex-3: "mandatory and enforced" is a policy question — slight rephrase to "policy defined"
UPDATE public.question_registry SET
  question_text = 'Code review process and enforcement policy defined?',
  hint_text     = 'Must specify mandatory review gates, minimum reviewer count, and branch protection rules — not individual review approval records',
  updated_at    = now()
WHERE question_code = 'engex-3';

-- engex-4: "completed" → "defined and reviewed"
UPDATE public.question_registry SET
  question_text = 'Test plan defined and peer-reviewed?',
  hint_text     = 'Must show test plan document covering scope, approach, entry/exit criteria — test execution evidence not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'engex-4';

-- engex-5: "defined and monitored" → "approach defined" (remove "monitored" = operational)
UPDATE public.question_registry SET
  question_text = 'Defect tracking approach and metrics defined?',
  hint_text     = 'Must specify defect classification, tracking tooling, and quality metric definitions — live defect counts or dashboards not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'engex-5';

-- engex-6: "implemented and results available" → "strategy and coverage targets defined"
UPDATE public.question_registry SET
  question_text = 'Automation testing strategy and coverage targets defined?',
  hint_text     = 'Must specify test types (unit, integration, contract), coverage targets, and tooling choices — test execution results or current coverage metrics are NOT required at ARB stage',
  updated_at    = now()
WHERE question_code = 'engex-6';

-- engex-7: "conducted" → "approach and scope defined"
UPDATE public.question_registry SET
  question_text = 'API testing approach and scope defined?',
  hint_text     = 'Must specify API test tooling, contract testing approach, and coverage expectations — test execution evidence not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'engex-7';

-- engex-8: "completed and baseline documented" → "plan and baseline targets defined"
-- hint removes the "<90 days old" result-age rule — not applicable under design philosophy
UPDATE public.question_registry SET
  question_text = 'Performance testing plan and baseline targets defined?',
  hint_text     = 'Must specify test scenarios, tooling, load targets (TPS, concurrent users), and pass/fail thresholds — test execution results or measured baselines are NOT required at ARB stage',
  updated_at    = now()
WHERE question_code = 'engex-8';

-- engex-9: "reporting in place" → "approach designed"
UPDATE public.question_registry SET
  question_text = 'SW quality metrics and reporting approach designed?',
  hint_text     = 'Must specify which quality metrics will be tracked, reporting cadence, and tooling — not live metric evidence',
  updated_at    = now()
WHERE question_code = 'engex-9';


-- ── BLOCK 8: Application / Infra Observability Design ────────────────────────

-- app-oth-2: "implemented" → "approach designed and documented"
UPDATE public.question_registry SET
  question_text = 'Audit trail and logging approach designed and documented?',
  hint_text     = 'Must specify which application events are logged, log schema, retention design, and correlation approach — live log samples not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'app-oth-2';

-- app-oth-3: "configured" → "approach designed and documented"
UPDATE public.question_registry SET
  question_text = 'Monitoring and alerting approach designed and documented?',
  hint_text     = 'Must specify application-level metrics, SLO thresholds, alerting channels, and on-call routing design — live dashboards or alert history not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'app-oth-3';

-- infra-oth-2: "configured" → "approach designed and documented"
UPDATE public.question_registry SET
  question_text = 'Audit trail and logging design specified for infra level?',
  hint_text     = 'Must specify what infra events are captured, log forwarding design, and retention policy — live log samples not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'infra-oth-2';

-- infra-oth-3: "set up" → "approach designed and documented"
UPDATE public.question_registry SET
  question_text = 'Monitoring and alerting approach designed for infra level?',
  hint_text     = 'Must specify infra-level metrics, alerting thresholds, and notification design — live dashboards or alert screenshots not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'infra-oth-3';


-- ── BLOCK 9: Infrastructure Capacity Design ───────────────────────────────────

-- infra-meta-4: "verified" → "modelled and documented"
UPDATE public.question_registry SET
  question_text = 'Bandwidth and resource adequacy modelled and documented for compute, storage and network?',
  hint_text     = 'Capacity model must document sizing rationale, growth headroom, and burst-handling approach — live utilisation metrics or monitoring screenshots not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'infra-meta-4';


-- ── BLOCK 10: Resilience and API Design ──────────────────────────────────────

-- app-soft-3: "applied" → "designed and documented"
UPDATE public.question_registry SET
  question_text = 'Resilience patterns designed and documented: timeouts, retries, circuit breakers, idempotency?',
  hint_text     = 'Evidence must reference HLD section showing each pattern design — implementation or test evidence not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'app-soft-3';

-- int-check-4: "implemented" → "designed and specified"
UPDATE public.question_registry SET
  question_text = 'Reliability controls designed and specified: idempotency, throttling, and rate limiting?',
  hint_text     = 'Design must show how each control is applied per integration pattern — implementation evidence not required at ARB stage',
  updated_at    = now()
WHERE question_code = 'int-check-4';

COMMIT;
