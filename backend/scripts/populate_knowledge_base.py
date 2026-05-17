#!/usr/bin/env python3
"""
Script to populate knowledge_base table from markdown files in knowledge-base directory.

Sources processed:
  ea-principles.md          — per-principle, category from ID prefix (G-=general, B-=business, etc.)
  ea-standards.md           — per-standard,  category from ID prefix (B-STD-=business, D-STD-=data, etc.)
  integration-principles.md — per-principle, INT-*/API-* → integration
  architecture-review-taxonomy.md — single entry, category=general
  ea-patterns.zip           — per-pattern section per file, category from filename mapping
"""

import re
import zipfile
from pathlib import Path
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.db.artefact_models import KnowledgeBase

# ── Category helpers ───────────────────────────────────────────────────────────

# Maps principle/standard ID prefixes to domain slugs
_PREFIX_TO_CATEGORY: dict = {
    "G":      "general",
    "B":      "business",
    "S":      "security",
    "A":      "application",
    "SW":     "software",
    "D":      "data",
    "I":      "infrastructure",
    # standards prefixes
    "B-STD":  "business",
    "D-STD":  "data",
    "I-STD":  "infrastructure",
    "S-STD":  "security",
    "A-STD":  "application",
    "SW-STD": "software",
    "G-STD":  "general",
    # integration file
    "INT":    "integration",
    "API":    "integration",
}

# Maps ea-patterns filenames (stem without number prefix) to domain slugs
_PATTERN_FILE_TO_CATEGORY: dict = {
    "application-architecture-patterns":      "application",
    "software-design-patterns":               "software",
    "integration-architecture-patterns":      "integration",
    "api-architecture-patterns":              "integration",
    "data-architecture-patterns":             "data",
    "infrastructure-platform-architecture-patterns": "infrastructure",
    "security-architecture-patterns":         "security",
    "devsecops-engineering-patterns":         "devsecops",
    "enterprise-crosscutting-patterns":       "general",
}

# Max characters stored per KB entry (prevents single-entry token explosions).
# ~3 chars/token → 1200 chars ≈ 400 tokens — a full principle fits comfortably.
MAX_ENTRY_CHARS = 2000


def _category_from_id(principle_id: str, fallback: str = "general") -> str:
    """Return domain slug for a principle/standard ID, longest prefix wins."""
    for prefix in sorted(_PREFIX_TO_CATEGORY, key=len, reverse=True):
        if principle_id.upper().startswith(prefix + "-"):
            return _PREFIX_TO_CATEGORY[prefix]
    return fallback


def _upsert(db: Session, entry: dict) -> None:
    """Insert or update a KnowledgeBase row by (principle_id, title).

    Always sets is_active=True so previously-deactivated entries are restored.
    """
    content = (entry["content"] or "").strip()
    if not content:
        return
    # Enforce per-entry content budget
    if len(content) > MAX_ENTRY_CHARS:
        content = content[:MAX_ENTRY_CHARS] + "\n…[truncated]"

    existing = db.query(KnowledgeBase).filter(
        KnowledgeBase.principle_id == entry.get("principle_id"),
        KnowledgeBase.title == entry["title"],
    ).first()

    if existing:
        existing.content   = content
        existing.category  = entry["category"]
        existing.is_active = True
        print(f"  Updated: [{entry['category']}] {entry['title']}")
    else:
        db.add(KnowledgeBase(
            title        = entry["title"],
            content      = content,
            category     = entry["category"],
            principle_id = entry.get("principle_id"),
            is_active    = True,
        ))
        print(f"  Added:   [{entry['category']}] {entry['title']}")


# ── Principles / standards parsers ────────────────────────────────────────────

def _parse_structured_md(content: str, fallback_category: str) -> list:
    """
    Parse a markdown file whose sections are headed by:
        ### PREFIX-ID — Title
    Returns one dict per section with principle_id, title, content, category.
    """
    entries = []
    # Split on lines that start a ### section with an ID
    sections = re.split(r'\n### ([A-Z][A-Z0-9-]*-\d+)\s*[—–-]\s*(.+)', content)
    # sections[0] = preamble; then triplets: (id, title, body)
    for i in range(1, len(sections) - 1, 3):
        pid   = sections[i].strip()
        title = sections[i + 1].strip()
        body  = sections[i + 2].strip() if i + 2 < len(sections) else ""
        entries.append({
            "principle_id": pid,
            "title":        title,
            "content":      body,
            "category":     _category_from_id(pid, fallback_category),
        })
    return entries


# ── Pattern file parser ────────────────────────────────────────────────────────

def _parse_pattern_md(content: str, category: str) -> list:
    """
    Parse an ea-patterns markdown file where sections are headed by:
        ### Pattern Name   (no ID prefix)
    Returns one dict per pattern.
    """
    entries = []
    # Split on ### headings (pattern names, not IDs)
    sections = re.split(r'\n### (.+)', content)
    # sections[0] = preamble; then pairs: (title, body)
    for i in range(1, len(sections) - 1, 2):
        title = sections[i].strip()
        body  = sections[i + 1].strip() if i + 1 < len(sections) else ""
        if not title or not body:
            continue
        entries.append({
            "principle_id": None,
            "title":        title,
            "content":      body,
            "category":     category,
        })
    return entries


def _category_from_pattern_filename(stem: str) -> str:
    """Strip leading NN- digit prefix and look up pattern category."""
    clean = re.sub(r'^\d+-', '', stem)  # remove "01-", "02-", etc.
    return _PATTERN_FILE_TO_CATEGORY.get(clean, "general")


# ── File processors ───────────────────────────────────────────────────────────

def process_principles_file(file_path: str, db: Session, fallback_category: str = "general") -> int:
    print(f"Processing principles: {file_path}")
    content = Path(file_path).read_text(encoding="utf-8")
    entries = _parse_structured_md(content, fallback_category)
    if not entries:
        # Fallback: single entry for the whole file
        entries = [{
            "principle_id": None,
            "title":        Path(file_path).stem.replace("-", " ").title(),
            "content":      content,
            "category":     fallback_category,
        }]
    for e in entries:
        _upsert(db, e)
    db.commit()
    print(f"  → {len(entries)} entries committed")
    return len(entries)


def process_pattern_file(file_path: str, category: str, db: Session) -> int:
    print(f"Processing patterns: {file_path} → [{category}]")
    content = Path(file_path).read_text(encoding="utf-8")
    entries = _parse_pattern_md(content, category)
    for e in entries:
        _upsert(db, e)
    db.commit()
    print(f"  → {len(entries)} pattern entries committed")
    return len(entries)


def process_patterns_zip(zip_path: str, db: Session) -> int:
    """Extract ea-patterns.zip in-memory and load each .md file."""
    print(f"Processing patterns zip: {zip_path}")
    total = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        md_names = [n for n in zf.namelist() if n.endswith(".md")]
        for name in sorted(md_names):
            stem     = Path(name).stem
            category = _category_from_pattern_filename(stem)
            content  = zf.read(name).decode("utf-8")
            entries  = _parse_pattern_md(content, category)
            for e in entries:
                _upsert(db, e)
            db.commit()
            print(f"  {name} → [{category}] {len(entries)} patterns")
            total += len(entries)
    return total


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Populating knowledge_base table…")
    db = SessionLocal()
    try:
        kb_dir = Path(__file__).resolve().parents[2] / "knowledge-base"
        total  = 0

        # Deactivate all whole-file blob entries (principle_id IS NULL and content > 5000 chars).
        # These were loaded as single-file entries and cause token explosions in LLM prompts.
        # Per-section entries inserted below will be reactivated or freshly inserted as active.
        deactivated = (
            db.query(KnowledgeBase)
            .filter(KnowledgeBase.principle_id == None)
            .all()
        )
        for row in deactivated:
            row.is_active = False
        db.commit()
        print(f"Deactivated {len(deactivated)} existing whole-file entries — replacing with per-section entries")

        # 1. EA Principles (per-principle, ID-based categorization)
        principles_md = kb_dir / "ea-principles.md"
        if principles_md.exists():
            total += process_principles_file(str(principles_md), db, fallback_category="general")

        # 2. EA Standards (per-standard, ID-based categorization)
        standards_md = kb_dir / "ea-standards.md"
        if standards_md.exists():
            total += process_principles_file(str(standards_md), db, fallback_category="standards")

        # 3. Integration Principles
        integration_md = kb_dir / "integration-principles.md"
        if integration_md.exists():
            total += process_principles_file(str(integration_md), db, fallback_category="integration")

        # 4. Architecture Review Taxonomy (single entry)
        taxonomy_md = kb_dir / "architecture-review-taxonomy.md"
        if taxonomy_md.exists():
            print(f"Processing taxonomy: {taxonomy_md}")
            content = taxonomy_md.read_text(encoding="utf-8")
            _upsert(db, {
                "principle_id": None,
                "title":        "Architecture Review Taxonomy",
                "content":      content,
                "category":     "general",
            })
            db.commit()
            total += 1

        # 5. EA Patterns zip
        patterns_zip = kb_dir / "ea-patterns.zip"
        if patterns_zip.exists():
            total += process_patterns_zip(str(patterns_zip), db)
        else:
            print(f"WARNING: {patterns_zip} not found — skipping patterns")

        print(f"\nDone — {total} total entries in knowledge_base")

        # Summary by category
        from app.db.artefact_models import KnowledgeBase as KB
        cats = db.query(KB.category, KB.principle_id).filter(KB.is_active == True).all()
        from collections import Counter
        summary = Counter(c for c, _ in cats)
        for cat, cnt in sorted(summary.items()):
            print(f"  {cat:<25} {cnt:>4} entries")

    except Exception as exc:
        print(f"Error: {exc}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
