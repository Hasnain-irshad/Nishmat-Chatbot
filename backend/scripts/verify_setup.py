#!/usr/bin/env python3
"""
Verify that a Supabase project is correctly set up for Nishmat AI.

Checks connectivity, that every table exists, that the seed data landed, and
that RLS is actually protecting the admin-only tables from an anonymous
caller. Uses only the standard library, so it runs before any dependency is
installed.

Usage:
    python backend/scripts/verify_setup.py
    python backend/scripts/verify_setup.py --env frontend/.env.local
"""

from __future__ import annotations

import argparse
import json
import sys

# Windows consoles default to cp1252 and cannot encode box-drawing characters
# or Hebrew. Without this a script can do all its work and still exit non-zero
# on its closing summary.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import urllib.error
import urllib.request
from pathlib import Path

TABLES = [
    "profiles",
    "series",
    "lesson_templates",
    "lesson_template_versions",
    "lessons",
    "lesson_versions",
    "source_files",
    "lesson_chunks",
    "style_examples",
    "conversations",
    "messages",
    "jobs",
    "audit_log",
    "ai_usage",
]

# Tables an anonymous caller must NOT be able to read rows from.
ADMIN_ONLY = ["lesson_templates", "source_files", "style_examples", "jobs"]

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[2m",
    "\033[0m",
)


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        sys.exit(f"{RED}✗{RESET} No env file at {path}")
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def request(url: str, key: str, timeout: int = 20):
    req = urllib.request.Request(
        url,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body or b"null")
        except json.JSONDecodeError:
            return exc.code, {"raw": body.decode("utf-8", "replace")[:200]}
    except Exception as exc:  # network, DNS, TLS
        return 0, {"error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="frontend/.env.local")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    env = load_env(root / args.env)

    url = env.get("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
    anon = env.get("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")
    if not url or not anon:
        sys.exit(
            f"{RED}✗{RESET} NEXT_PUBLIC_SUPABASE_URL / "
            f"NEXT_PUBLIC_SUPABASE_ANON_KEY missing from {args.env}"
        )

    print(f"\n  Project: {DIM}{url}{RESET}\n")
    failures: list[str] = []
    warnings: list[str] = []

    # ---------------------------------------------------------------- auth
    status, body = request(f"{url}/auth/v1/health", anon)
    if status == 200:
        print(f"  {GREEN}✓{RESET} Auth service reachable "
              f"{DIM}({body.get('version', '?')}){RESET}")
    else:
        print(f"  {RED}✗{RESET} Auth service unreachable ({status})")
        failures.append("auth unreachable")

    # -------------------------------------------------------------- tables
    print(f"\n  {DIM}Tables{RESET}")
    missing: list[str] = []
    for table in TABLES:
        status, body = request(f"{url}/rest/v1/{table}?select=*&limit=1", anon)
        if status in (200, 206):
            print(f"  {GREEN}✓{RESET} {table}")
        elif status == 404 and isinstance(body, dict) and body.get("code") == "PGRST205":
            print(f"  {RED}✗{RESET} {table} {DIM}— does not exist{RESET}")
            missing.append(table)
        elif status in (401, 403):
            # Blocked by RLS, which still proves the table is there.
            print(f"  {GREEN}✓{RESET} {table} {DIM}(RLS blocked — expected){RESET}")
        else:
            print(f"  {YELLOW}?{RESET} {table} {DIM}— HTTP {status}{RESET}")
            warnings.append(f"{table}: HTTP {status}")

    if missing:
        failures.append(f"{len(missing)} table(s) missing")

    # ----------------------------------------------------------- seed data
    if "series" not in missing:
        print(f"\n  {DIM}Seed data{RESET}")
        status, body = request(f"{url}/rest/v1/series?select=title,slug", anon)
        if status == 200 and isinstance(body, list) and body:
            print(f"  {GREEN}✓{RESET} Series: {body[0].get('title')}")
        else:
            print(f"  {RED}✗{RESET} No series row — 0002_seed_template.sql did not run")
            failures.append("seed missing")

    # ------------------------------------------------------ RLS protection
    print(f"\n  {DIM}Row Level Security (as an anonymous caller){RESET}")
    for table in ADMIN_ONLY:
        if table in missing:
            continue
        status, body = request(f"{url}/rest/v1/{table}?select=*", anon)
        leaked = status == 200 and isinstance(body, list) and len(body) > 0
        if leaked:
            print(f"  {RED}✗{RESET} {table} {DIM}— readable anonymously!{RESET}")
            failures.append(f"{table} exposed")
        else:
            print(f"  {GREEN}✓{RESET} {table} {DIM}— not readable{RESET}")

    # ------------------------------------------------------------- summary
    print()
    if failures:
        print(f"  {RED}{len(failures)} problem(s):{RESET}")
        for f in failures:
            print(f"    · {f}")
        if missing:
            print(
                f"\n  {YELLOW}→{RESET} Run "
                f"{DIM}backend/migrations/apply_all.sql{RESET} "
                "in the Supabase SQL Editor.\n"
            )
        return 1

    if warnings:
        print(f"  {YELLOW}Warnings:{RESET}")
        for w in warnings:
            print(f"    · {w}")

    print(f"  {GREEN}Everything checks out.{RESET}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
