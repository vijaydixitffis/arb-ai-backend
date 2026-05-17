"""
Seed default prompt_templates from the live agent source code.
Run from backend/: python3 scripts/seed_prompts.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import psycopg2

# ── Pull prompt text from agent source ───────────────────────────────────────

from app.agents.enhanced_domain_agents import (
    EnhancedDomainValidationAgent, DOMAIN_LABEL,
)
from app.agents.enhanced_orchestrator import EnhancedARBOrchestrator

class _FakeDB:
    def query(self, *a, **kw): return self
    def filter(self, *a, **kw): return self
    def order_by(self, *a, **kw): return self
    def first(self): return None

_agent = EnhancedDomainValidationAgent.__new__(EnhancedDomainValidationAgent)
_agent.db = _FakeDB()

# Generic domain template — keep placeholders for super_admin editing
_sentinel_label = "DOMAIN_LABEL_PLACEHOLDER"
_sentinel_slug  = "DOMAIN_SLUG_PLACEHOLDER"
_raw_generic = _agent._build_system_prompt(_sentinel_label, _sentinel_slug)
DOMAIN_SYSTEM_GENERIC = (
    _raw_generic
    .replace(_sentinel_label, "{domain_label}")
    .replace(_sentinel_slug,  "{domain_slug}")
)

# Per-domain system prompts — literal content for each of the 9 domains
DOMAIN_SLUGS = [
    "solution", "business", "application", "integration",
    "data", "security", "infrastructure", "devsecops", "nfr",
]

# Synthesizer system prompt
SYNTHESIZER_SYSTEM = EnhancedARBOrchestrator._SYNTHESIS_SYSTEM_PROMPT.strip()

# ── Prompts to seed ───────────────────────────────────────────────────────────

PROMPTS = [
    {
        "prompt_key":  "domain.system",
        "prompt_type": "system",
        "domain_code": None,
        "content":     DOMAIN_SYSTEM_GENERIC,
        "notes":       "Generic domain agent system prompt (fallback). Use {domain_label} and {domain_slug} as placeholders.",
    },
    {
        "prompt_key":  "synthesizer.system",
        "prompt_type": "synthesizer",
        "domain_code": None,
        "content":     SYNTHESIZER_SYSTEM,
        "notes":       "Default synthesis (Tier-2) system prompt.",
    },
]

# Add one entry per domain — full literal prompt including any domain-specific appendix
for slug in DOMAIN_SLUGS:
    label   = DOMAIN_LABEL.get(slug, slug.title())
    content = _agent._build_system_prompt(label, slug)
    PROMPTS.append({
        "prompt_key":  f"domain.system.{slug}",
        "prompt_type": "system",
        "domain_code": slug,
        "content":     content,
        "notes":       f"{label} domain system prompt. Overrides domain.system for the {slug} domain.",
    })

# ── DB connection ─────────────────────────────────────────────────────────────

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://vijaykumardixit@localhost/arb_ai_agent"
)

conn = psycopg2.connect(DB_URL)
cur  = conn.cursor()

inserted = 0
for p in PROMPTS:
    cur.execute(
        """
        INSERT INTO prompt_templates
            (prompt_key, prompt_type, domain_code, version, content, is_active, notes)
        VALUES (%s, %s, %s, 1, %s, true, %s)
        ON CONFLICT DO NOTHING
        """,
        (p["prompt_key"], p["prompt_type"], p["domain_code"], p["content"], p["notes"]),
    )
    inserted += cur.rowcount

conn.commit()
cur.close()
conn.close()

print(f"Seeded {inserted} prompt(s) into prompt_templates (total configured: {len(PROMPTS)}).")
if inserted == 0:
    print("(All prompts already exist — nothing changed.)")
