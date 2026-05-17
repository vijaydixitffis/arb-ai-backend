-- Merge software sub-domain into application agent.
-- app-soft-* questions (SBOM, versioning, resilience, docs) were previously
-- processed by a separate 'software' agent run that read the same frontend tab
-- and KB as the 'application' agent, causing duplicate findings.
-- This reassigns them so one application agent covers all app-* questions.
UPDATE question_registry
SET agent_domain = 'application'
WHERE agent_domain = 'software';
