-- Migration: add return_domains to ea_review
-- Stores the list of domain slugs the EA flagged for rework when issuing a RETURN decision.
ALTER TABLE ea_review ADD COLUMN IF NOT EXISTS return_domains text[] NULL;

COMMENT ON COLUMN ea_review.return_domains IS
    'Domain slugs the EA flagged for rework on a RETURN decision (e.g. ["security","data"]).';
