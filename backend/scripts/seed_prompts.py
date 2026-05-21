"""
Seed / update prompt_templates from the live agent source code.

Run from backend/:  python3 scripts/seed_prompts.py
Re-running inserts a new version and deactivates the old one for any changed prompts.
Pass --dry-run to preview SQL without writing to DB.
"""
import sys, os, hashlib, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import psycopg2

# ── Pull prompt text from agent source ───────────────────────────────────────

from app.agents.enhanced_domain_agents import EnhancedDomainValidationAgent
from app.agents.enhanced_orchestrator import EnhancedARBOrchestrator
from app.core.config import settings

# ── DB connection (needed before building prompts to load domain metadata) ────

DB_URL = settings.DATABASE_URL
conn_pre = psycopg2.connect(DB_URL)
cur_pre  = conn_pre.cursor()

# Load active domains from DB — no hardcoded slug list
cur_pre.execute("SELECT slug, name FROM domains WHERE is_active = true ORDER BY seq_number")
DB_DOMAINS = cur_pre.fetchall()  # [(slug, name), ...]

cur_pre.close()
conn_pre.close()

# Build a minimal fake agent for calling _build_system_prompt (no DB calls needed there)
_agent = EnhancedDomainValidationAgent.__new__(EnhancedDomainValidationAgent)
_agent.db    = None
_agent._meta = None  # _build_system_prompt doesn't use _meta

# Generic domain template — keep placeholders for super_admin editing
_sentinel_label = "DOMAIN_LABEL_PLACEHOLDER"
_sentinel_slug  = "DOMAIN_SLUG_PLACEHOLDER"
_raw_generic = _agent._build_system_prompt(_sentinel_label, _sentinel_slug)
DOMAIN_SYSTEM_GENERIC = (
    _raw_generic
    .replace(_sentinel_label, "{domain_label}")
    .replace(_sentinel_slug,  "{domain_slug}")
)

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

# Add one entry per active domain — labels from DB, no hardcoded list
for slug, name in DB_DOMAINS:
    content = _agent._build_system_prompt(name, slug)
    PROMPTS.append({
        "prompt_key":  f"domain.system.{slug}",
        "prompt_type": "system",
        "domain_code": slug,
        "content":     content,
        "notes":       f"{name} domain system prompt. Overrides domain.system for the {slug} domain.",
    })

# ── DB connection for upsert ──────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true", help="Print SQL without executing")
args = parser.parse_args()

conn = psycopg2.connect(DB_URL)
cur  = conn.cursor()

inserted = 0
updated  = 0
skipped  = 0

for p in PROMPTS:
    key     = p["prompt_key"]
    content = p["content"]

    # Check if an active row already exists and whether content has changed
    cur.execute(
        """
        SELECT id, version, content
        FROM   prompt_templates
        WHERE  prompt_key = %s AND is_active = true
        ORDER  BY version DESC
        LIMIT  1
        """,
        (key,),
    )
    existing = cur.fetchone()

    if existing:
        existing_id, existing_version, existing_content = existing
        if hashlib.sha256(existing_content.encode()).digest() == hashlib.sha256(content.encode()).digest():
            skipped += 1
            continue  # content unchanged — no action needed

        next_version = existing_version + 1
        if args.dry_run:
            print(f"[DRY-RUN] WOULD update {key} v{existing_version} → v{next_version}")
            updated += 1
            continue

        # Deactivate the old version
        cur.execute(
            "UPDATE prompt_templates SET is_active = false WHERE id = %s",
            (existing_id,),
        )
        # Insert new version
        cur.execute(
            """
            INSERT INTO prompt_templates
                (prompt_key, prompt_type, domain_code, version, content, is_active, notes)
            VALUES (%s, %s, %s, %s, %s, true, %s)
            """,
            (key, p["prompt_type"], p["domain_code"], next_version, content, p["notes"]),
        )
        print(f"  Updated: {key} (v{existing_version} → v{next_version})")
        updated += 1
    else:
        if args.dry_run:
            print(f"[DRY-RUN] WOULD insert {key} v1")
            inserted += 1
            continue

        cur.execute(
            """
            INSERT INTO prompt_templates
                (prompt_key, prompt_type, domain_code, version, content, is_active, notes)
            VALUES (%s, %s, %s, 1, %s, true, %s)
            """,
            (key, p["prompt_type"], p["domain_code"], content, p["notes"]),
        )
        print(f"  Inserted: {key} v1")
        inserted += 1

if not args.dry_run:
    conn.commit()
cur.close()
conn.close()

print(f"\nDone: {inserted} inserted, {updated} updated, {skipped} unchanged.")
