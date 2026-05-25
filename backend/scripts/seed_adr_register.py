#!/usr/bin/env python3
"""
Seed the adr_register table with 12 prototype ADRs.

Usage:
  python3 seed_adr_register.py              # both (default)
  python3 seed_adr_register.py --target local
  python3 seed_adr_register.py --target supabase
  python3 seed_adr_register.py --target both
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

LOCAL_DB_URL        = os.getenv("DATABASE_URL", "postgresql://vijaykumardixit@localhost:5432/arb_ai_agent")
SUPABASE_PROJECT    = os.getenv("SUPABASE_PROJECT_REF", "lufwpadentelascwohlg")
SUPABASE_TOKEN      = os.getenv("SUPABASE_ACCESS_TOKEN", "")   # set via env — never hardcode
SUPABASE_QUERY_URL  = f"https://api.supabase.com/v1/projects/{SUPABASE_PROJECT}/database/query"

SEED_FILE = Path(__file__).parent.parent / "migrations" / "20260525_adr_register_seed.sql"


def split_statements(sql: str) -> list[str]:
    """Split on -- STMT_SEP markers (safe; never appears inside string literals)."""
    stmts = []
    for raw in sql.split("-- STMT_SEP"):
        s = raw.strip()
        lines = [l for l in s.splitlines() if l.strip() and not l.strip().startswith("--")]
        if lines:
            stmts.append(s)
    return stmts


def apply_local(sql: str) -> None:
    print("▶ Applying seed to local Postgres …")
    result = subprocess.run(
        ["psql", LOCAL_DB_URL],
        input=sql, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ✗ psql error:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("  ✓ Local Postgres seed complete")


def supabase_query(sql: str) -> list:
    payload = json.dumps({"query": sql}).encode()
    req = urllib.request.Request(
        SUPABASE_QUERY_URL, data=payload,
        headers={
            "Authorization": f"Bearer {SUPABASE_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "adr-seed/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def apply_supabase(sql: str) -> None:
    print(f"▶ Applying seed to Supabase ({SUPABASE_PROJECT}) …")
    statements = split_statements(sql)
    ok = 0
    for i, stmt in enumerate(statements, 1):
        try:
            supabase_query(stmt)
            ok += 1
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"  ✗ Statement {i} failed (HTTP {e.code}): {body[:200]}", file=sys.stderr)
            sys.exit(1)
    print(f"  ✓ Supabase seed complete ({ok} statements)")


def verify(target: str) -> None:
    q = "SELECT COUNT(*) AS cnt FROM adr_register"
    if target in ("local", "both"):
        r = subprocess.run(["psql", LOCAL_DB_URL, "-Atc", q], capture_output=True, text=True)
        print(f"  ℹ Local adr_register rows: {r.stdout.strip()}")
    if target in ("supabase", "both"):
        rows = supabase_query(q)
        print(f"  ℹ Supabase adr_register rows: {rows[0]['cnt']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["local", "supabase", "both"], default="both")
    args = parser.parse_args()

    if not SEED_FILE.exists():
        print(f"✗ Seed file not found: {SEED_FILE}", file=sys.stderr)
        sys.exit(1)

    sql = SEED_FILE.read_text()
    print(f"Seed file: {SEED_FILE.name}  ({len(sql):,} bytes, 12 ADRs)\n")

    if args.target in ("local", "both"):
        apply_local(sql)
    if args.target in ("supabase", "both"):
        apply_supabase(sql)

    print("\nVerifying row counts …")
    verify(args.target)
    print("\nDone.")


if __name__ == "__main__":
    main()
