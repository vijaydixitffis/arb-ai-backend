-- ============================================================================
-- ADR Register — seed data (12 records mirroring frontend mock data)
-- 2026-05-25
-- Uses inline subqueries (no PL/pgSQL DO block) for portability with
-- Supabase management API and plain psql.
-- ============================================================================

-- ── ADR-042 ──────────────────────────────────────────────────────────────────
INSERT INTO adr_register (
  adr_id, title, status, stage, owner_name, owner_role, owner_user_id,
  context, decision, rationale, tags, domain, review_date, decided_at,
  options, consequences, links, activity, comment_count, created_by
) SELECT
  'ADR-042',
  'Use Event-Driven Architecture for Order Processing',
  'published', 'published', 'Priya Menon', 'solution_architect',
  (SELECT id FROM users WHERE role='solution_architect' LIMIT 1),
  'The order processing domain experiences variable load with peaks during retail events and requires high scalability and resilience. The current synchronous REST chain between Order, Inventory, Payments and Fulfilment creates tight coupling and cascading failures when any one service degrades.',
  'We will use an event-driven architecture with Kafka as the message broker to decouple Order, Inventory, Payments and Fulfilment services. Producers emit domain events; consumers subscribe to topics they own.',
  'Event-driven decoupling provides the scalability and resilience the domain demands. Kafka is already deployed for analytics so the operational footprint does not grow. Loose coupling lets each team ship at their own cadence.',
  ARRAY['architecture','integration','kafka'], 'integration',
  '2025-05-10'::date, '2024-05-10'::timestamptz,
  '[{"name":"Synchronous REST APIs","pros":"Simplest mental model, easy to debug","cons":"Cascading failures, tight coupling, poor scalability","chosen":false},{"name":"Database triggers","pros":"No new infrastructure","cons":"Ties business logic to DB, hard to evolve","chosen":false},{"name":"Event-driven with Kafka","pros":"Scalable, resilient, loosely coupled","cons":"Operational complexity, eventual consistency","chosen":true}]'::jsonb,
  '{"pos":["High scalability and resilience under bursty load","Better domain decoupling — teams ship independently","Reuses existing Kafka platform"],"neg":["Increased operational complexity (topic governance, schemas)","Eventual consistency — UX needs to handle delayed updates","Need to invest in observability for async flows"]}'::jsonb,
  '[{"kind":"arb","label":"ARB-2026-0415 · Treasury Liquidity Engine","href":"#"},{"kind":"doc","label":"Event taxonomy v2 (Confluence)","href":"#"},{"kind":"ticket","label":"JIRA-EPIC-1842","href":"#"}]'::jsonb,
  '[{"kind":"proposed","who":"Priya Menon","when":"Apr 22","text":"Proposed by Priya Menon"},{"kind":"review","who":"EA panel","when":"May 02","text":"Reviewed in ARB session · 3 amendments"},{"kind":"accepted","who":"Sara Olsen","when":"May 10","text":"Accepted with conditions on observability"},{"kind":"review","who":"System","when":"+1 yr","text":"Scheduled review on 2025-05-10"}]'::jsonb,
  12, (SELECT id FROM users WHERE role='solution_architect' LIMIT 1)
ON CONFLICT (adr_id) DO NOTHING;
-- STMT_SEP

-- ── ADR-041 ──────────────────────────────────────────────────────────────────
INSERT INTO adr_register (
  adr_id, title, status, stage, owner_name, owner_role, owner_user_id,
  context, decision, rationale, tags, domain, decided_at,
  options, consequences, links, comment_count, created_by
) SELECT
  'ADR-041', 'Adopt Zero-Trust for Internal Service-to-Service',
  'proposed', 'in_review', 'Daniel Park', 'solution_architect',
  (SELECT id FROM users WHERE role='solution_architect' LIMIT 1),
  'Internal east-west traffic currently relies on network-perimeter trust. Recent audit flagged that compromised pods would have unfettered lateral movement.',
  'Adopt a zero-trust posture for service-to-service traffic using mTLS via the service mesh, with workload identity tied to SPIFFE IDs.',
  'Removes implicit trust, satisfies audit, and gives us a single chokepoint to enforce policy.',
  ARRAY['security','zero-trust','service-mesh'], 'security', '2026-05-12'::timestamptz,
  '[{"name":"Keep perimeter trust","pros":"No change","cons":"Audit finding remains open","chosen":false},{"name":"mTLS at app layer (per-service)","pros":"Granular","cons":"Per-team burden, inconsistent","chosen":false},{"name":"Service mesh mTLS (SPIFFE)","pros":"Centralised, audited","cons":"Mesh operational overhead","chosen":true}]'::jsonb,
  '{"pos":["Audit-clean lateral movement story","Uniform identity across workloads"],"neg":["Mesh sidecar memory overhead","New team capability needed"]}'::jsonb,
  '[{"kind":"doc","label":"Security Audit 2026-Q1 finding #14","href":"#"}]'::jsonb,
  5, (SELECT id FROM users WHERE role='solution_architect' LIMIT 1)
ON CONFLICT (adr_id) DO NOTHING;
-- STMT_SEP

-- ── ADR-040 ──────────────────────────────────────────────────────────────────
INSERT INTO adr_register (
  adr_id, title, status, stage, owner_name, owner_role, owner_user_id,
  context, decision, rationale, tags, domain, review_date, decided_at,
  options, consequences, comment_count, created_by
) SELECT
  'ADR-040', 'Use PostgreSQL as Primary Transactional Store',
  'published', 'published', 'Marco Bellini', 'solution_architect',
  (SELECT id FROM users WHERE role='solution_architect' LIMIT 1),
  'New product lines need a transactional store. Today we have a mix of MySQL, Oracle, and DynamoDB across legacy estates.',
  'PostgreSQL 16 (managed) for all new transactional workloads. Existing Oracle/MySQL workloads remain as-is until end-of-life.',
  'Strong ACID guarantees, broad team familiarity, mature managed offering, and the JSONB type covers semi-structured needs without standing up another store.',
  ARRAY['data','postgresql'], 'data', '2027-04-18'::date, '2026-04-18'::timestamptz,
  '[{"name":"PostgreSQL (managed)","pros":"Mature, familiar, JSONB","cons":"Vertical scaling ceiling","chosen":true},{"name":"MySQL (managed)","pros":"Familiar","cons":"Weaker type system, no JSONB parity","chosen":false},{"name":"DynamoDB","pros":"Serverless","cons":"Limited query model, costly joins","chosen":false}]'::jsonb,
  '{"pos":["Standardise on one engine for new work","Operations team can specialise"],"neg":["Vertical scaling ceiling — needs sharding plan past ~5TB"]}'::jsonb,
  8, (SELECT id FROM users WHERE role='solution_architect' LIMIT 1)
ON CONFLICT (adr_id) DO NOTHING;
-- STMT_SEP

-- ── ADR-039 ──────────────────────────────────────────────────────────────────
INSERT INTO adr_register (
  adr_id, title, status, stage, owner_name, owner_role, owner_user_id,
  context, decision, rationale, tags, domain, review_date, decided_at,
  options, consequences, links, comment_count, created_by
) SELECT
  'ADR-039', 'Replace Custom Auth with Enterprise SSO (OIDC)',
  'accepted', 'in_review', 'Aisha Verma', 'solution_architect',
  (SELECT id FROM users WHERE role='solution_architect' LIMIT 1),
  'Each internal app maintains its own auth. User offboarding takes days; access reviews are manual.',
  'All new and existing apps must integrate with the enterprise OIDC provider for sign-in. Local auth is deprecated.',
  'Centralises identity lifecycle, satisfies audit on offboarding SLAs, and unblocks SCIM provisioning.',
  ARRAY['security','identity','oidc'], 'security', '2026-09-02'::date, '2026-03-02'::timestamptz,
  '[{"name":"Enterprise OIDC","pros":"Single source of truth","cons":"Migration burden across estate","chosen":true},{"name":"SAML 2.0","pros":"Proven","cons":"Heavier for SPAs and APIs","chosen":false},{"name":"Status quo","pros":"No change","cons":"Audit finding remains","chosen":false}]'::jsonb,
  '{"pos":["Centralised lifecycle","Faster offboarding"],"neg":["Migration of 40+ apps required"]}'::jsonb,
  '[{"kind":"arb","label":"ARB-2026-0392 · Identity Platform","href":"#"}]'::jsonb,
  22, (SELECT id FROM users WHERE role='solution_architect' LIMIT 1)
ON CONFLICT (adr_id) DO NOTHING;
-- STMT_SEP

-- ── ADR-038 (superseded by ADR-042) ──────────────────────────────────────────
INSERT INTO adr_register (
  adr_id, title, status, stage, owner_name, owner_role, owner_user_id,
  context, decision, rationale, tags, domain, decided_at, superseded_by,
  options, consequences, comment_count, created_by
) SELECT
  'ADR-038', 'Synchronous REST for Order Processing',
  'evolving', 'evolving', 'Priya Menon', 'solution_architect',
  (SELECT id FROM users WHERE role='solution_architect' LIMIT 1),
  'Initial order processing built on direct REST chain.',
  'Synchronous REST calls between Order, Inventory, Payments.',
  'Fast time-to-market on initial launch.',
  ARRAY['integration','legacy'], 'integration', '2023-08-14'::timestamptz, 'ADR-042',
  '[]'::jsonb,
  '{"pos":["Shipped on time"],"neg":["Cascading failures observed under load"]}'::jsonb,
  3, (SELECT id FROM users WHERE role='solution_architect' LIMIT 1)
ON CONFLICT (adr_id) DO NOTHING;
-- STMT_SEP

-- ── ADR-037 ──────────────────────────────────────────────────────────────────
INSERT INTO adr_register (
  adr_id, title, status, stage, owner_name, owner_role, owner_user_id,
  context, decision, rationale, tags, review_date, decided_at,
  options, consequences, comment_count, created_by
) SELECT
  'ADR-037', 'Adopt Feature Flags via LaunchDarkly',
  'published', 'published', 'Sara Olsen', 'enterprise_architect',
  (SELECT id FROM users WHERE role='enterprise_architect' LIMIT 1),
  'Releases are bundled and risky; rolling back individual changes is expensive.',
  'Adopt LaunchDarkly as the enterprise feature-flag platform; all new user-facing features ship behind a flag.',
  'Decouples deploy from release, enables progressive delivery and instant kill-switches.',
  ARRAY['delivery','feature-flags'], '2027-02-19'::date, '2026-02-19'::timestamptz,
  '[{"name":"LaunchDarkly","pros":"Mature, audited","cons":"Cost per seat","chosen":true},{"name":"Build in-house","pros":"Fully owned","cons":"Years of investment","chosen":false},{"name":"Open-source (Unleash)","pros":"No licence","cons":"Self-host overhead","chosen":false}]'::jsonb,
  '{"pos":["Faster, safer rollouts"],"neg":["Annual cost per seat"]}'::jsonb,
  7, (SELECT id FROM users WHERE role='enterprise_architect' LIMIT 1)
ON CONFLICT (adr_id) DO NOTHING;
-- STMT_SEP

-- ── ADR-036 ──────────────────────────────────────────────────────────────────
INSERT INTO adr_register (
  adr_id, title, status, stage, owner_name, owner_role, owner_user_id,
  context, decision, rationale, tags, decided_at,
  options, consequences, comment_count, created_by
) SELECT
  'ADR-036', 'GraphQL Federation for Customer 360',
  'draft', 'authored', 'Alex Chen', 'solution_architect',
  (SELECT id FROM users WHERE role='solution_architect' LIMIT 1),
  'The Customer 360 view needs data from 7 backend services. Aggregation today lives in BFFs that duplicate logic.',
  '— (pending discussion)', '— (to be drafted)',
  ARRAY['api','graphql'], '2026-05-20'::timestamptz,
  '[]'::jsonb, '{"pos":[],"neg":[]}'::jsonb,
  2, (SELECT id FROM users WHERE role='solution_architect' LIMIT 1)
ON CONFLICT (adr_id) DO NOTHING;
-- STMT_SEP

-- ── ADR-035 ──────────────────────────────────────────────────────────────────
INSERT INTO adr_register (
  adr_id, title, status, stage, owner_name, owner_role, owner_user_id,
  context, decision, rationale, tags, decided_at,
  options, consequences, comment_count, created_by
) SELECT
  'ADR-035', 'Local-only Session Storage for SPA',
  'evolving', 'evolving', 'Marco Bellini', 'solution_architect',
  (SELECT id FROM users WHERE role='solution_architect' LIMIT 1),
  'Originally stored session tokens in localStorage for SPA simplicity.',
  'Tokens in localStorage.', 'Simplest at the time.',
  ARRAY['security','frontend','legacy'], '2024-01-22'::timestamptz,
  '[]'::jsonb, '{"pos":[],"neg":["XSS exposure"]}'::jsonb,
  1, (SELECT id FROM users WHERE role='solution_architect' LIMIT 1)
ON CONFLICT (adr_id) DO NOTHING;
-- STMT_SEP

-- ── ADR-034 ──────────────────────────────────────────────────────────────────
INSERT INTO adr_register (
  adr_id, title, status, stage, owner_name, owner_role, owner_user_id,
  context, decision, rationale, tags, review_date, decided_at,
  options, consequences, comment_count, created_by
) SELECT
  'ADR-034', 'Use Terraform for All Cloud Provisioning',
  'published', 'published', 'Daniel Park', 'solution_architect',
  (SELECT id FROM users WHERE role='solution_architect' LIMIT 1),
  'Cloud resources are provisioned via a mix of console, scripts and Terraform.',
  'All cloud resources must be provisioned via Terraform; manual changes are reverted nightly.',
  'Reproducibility, audit, and disaster recovery.',
  ARRAY['infrastructure','iac'], '2027-01-08'::date, '2026-01-08'::timestamptz,
  '[{"name":"Terraform","pros":"Multi-cloud, mature","cons":"State management","chosen":true},{"name":"Pulumi","pros":"Real languages","cons":"Smaller ecosystem","chosen":false},{"name":"CloudFormation","pros":"AWS-native","cons":"AWS-only","chosen":false}]'::jsonb,
  '{"pos":["Reproducible infra"],"neg":["Terraform state ops burden"]}'::jsonb,
  4, (SELECT id FROM users WHERE role='solution_architect' LIMIT 1)
ON CONFLICT (adr_id) DO NOTHING;
-- STMT_SEP

-- ── ADR-033 ──────────────────────────────────────────────────────────────────
INSERT INTO adr_register (
  adr_id, title, status, stage, owner_name, owner_role, owner_user_id,
  context, decision, rationale, tags, decided_at,
  options, consequences, links, comment_count, created_by
) SELECT
  'ADR-033', 'Deprecate SOAP Endpoints for External Partners',
  'conditional', 'in_review', 'Priya Menon', 'solution_architect',
  (SELECT id FROM users WHERE role='solution_architect' LIMIT 1),
  'Three partners still consume our SOAP endpoints. Operating two API styles doubles the surface.',
  'Deprecate SOAP with 12-month notice; partners migrate to REST.',
  'Reduces surface area, easier security review.',
  ARRAY['api','integration','sunset'], '2026-05-15'::timestamptz,
  '[{"name":"12-month sunset","pros":"Reasonable","cons":"Partner pushback expected","chosen":true},{"name":"24-month sunset","pros":"Easier on partners","cons":"Twice the operational cost","chosen":false},{"name":"Indefinite parallel","pros":"No partner friction","cons":"Permanent double surface","chosen":false}]'::jsonb,
  '{"pos":["Reduced API surface"],"neg":["Partner negotiations"]}'::jsonb,
  '[{"kind":"doc","label":"Partner comms plan","href":"#"}]'::jsonb,
  14, (SELECT id FROM users WHERE role='solution_architect' LIMIT 1)
ON CONFLICT (adr_id) DO NOTHING;
-- STMT_SEP

-- ── ADR-032 ──────────────────────────────────────────────────────────────────
INSERT INTO adr_register (
  adr_id, title, status, stage, owner_name, owner_role, owner_user_id,
  context, decision, rationale, tags, decided_at,
  options, consequences, comment_count, created_by
) SELECT
  'ADR-032', 'Mobile Offline-First Sync Strategy',
  'deferred', 'in_review', 'Aisha Verma', 'solution_architect',
  (SELECT id FROM users WHERE role='solution_architect' LIMIT 1),
  'Field agents work in low-connectivity zones; current app is online-only.',
  'Use CRDT-based local store with background sync.',
  'Conflict-free merge under intermittent connectivity.',
  ARRAY['mobile','sync'], '2026-05-08'::timestamptz,
  '[{"name":"CRDT (Yjs)","pros":"Conflict-free","cons":"Library maturity","chosen":true},{"name":"OT-based","pros":"Proven in editors","cons":"Server-coordination","chosen":false},{"name":"Last-write-wins","pros":"Trivial","cons":"Data loss","chosen":false}]'::jsonb,
  '{"pos":["Field productivity"],"neg":["New library to support"]}'::jsonb,
  6, (SELECT id FROM users WHERE role='solution_architect' LIMIT 1)
ON CONFLICT (adr_id) DO NOTHING;
-- STMT_SEP

-- ── ADR-031 ──────────────────────────────────────────────────────────────────
INSERT INTO adr_register (
  adr_id, title, status, stage, owner_name, owner_role, owner_user_id,
  context, decision, rationale, tags, domain, decided_at,
  options, consequences, comment_count, created_by
) SELECT
  'ADR-031', 'Replace Relational DB with Document Store for Core Ledger',
  'rejected', 'in_review', 'Marco Bellini', 'solution_architect',
  (SELECT id FROM users WHERE role='solution_architect' LIMIT 1),
  'Proposal to move core ledger from PostgreSQL to a document store for schema flexibility.',
  'Rejected. Strong ACID guarantees outweigh schema flexibility for the ledger workload.',
  'Ledger requires multi-row transactions and strict consistency. JSONB in PostgreSQL covers the flexible-schema use case without losing ACID.',
  ARRAY['data','rejected'], 'data', '2026-04-30'::timestamptz,
  '[{"name":"Document store (MongoDB)","pros":"Flexible schema","cons":"Weaker transactional guarantees","chosen":false},{"name":"Stay on PostgreSQL + JSONB","pros":"ACID + flexible columns","cons":"Some query complexity","chosen":true}]'::jsonb,
  '{"pos":["No migration risk on ledger"],"neg":["JSONB query patterns documented for teams"]}'::jsonb,
  11, (SELECT id FROM users WHERE role='solution_architect' LIMIT 1)
ON CONFLICT (adr_id) DO NOTHING;
-- STMT_SEP

-- ── Advance sequence so new ADRs start at ADR-043 ────────────────────────────
-- STMT_SEP
SELECT setval('adr_register_seq', 42, true);
