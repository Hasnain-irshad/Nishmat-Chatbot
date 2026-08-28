#!/usr/bin/env python3
"""
Build the chatbot's search index over every published lesson.

    python backend/scripts/index_corpus.py --dry-run   # chunk only, no embeddings
    python backend/scripts/index_corpus.py             # embed and store

Safe to re-run: each lesson's chunks are replaced wholesale.

Cost is trivial — embedding the whole 131-lesson corpus with
text-embedding-3-small is around one cent — but `--dry-run` still exists so the
chunking can be inspected before anything is spent.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Windows consoles default to cp1252 and cannot encode box-drawing characters
# or Hebrew. Without this a script can do all its work and still exit non-zero
# on its closing summary.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT / "backend")
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import supabase  # noqa: E402
from app.llm import usage as usage_tracker  # noqa: E402
from app.services import chunking_service, indexing_service  # noqa: E402

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m",
)


async def published_lessons() -> list[dict]:
    return await supabase.service().select(
        "lessons",
        columns=(
            "id, title, lesson_number, hebrew_phrase, transliteration, "
            "published_version_id, series_id"
        ),
        filters={"status": "eq.published", "deleted_at": "is.null"},
        order="lesson_number.asc.nullslast",
        limit=500,
    )


async def dry_run() -> int:
    lessons = await published_lessons()
    print(f"\n{BOLD}  {len(lessons)} published lessons{RESET}\n")

    db = supabase.service()
    total_chunks = 0
    total_words = 0
    per_lesson: list[int] = []
    smallest: tuple[int, str] | None = None
    largest: tuple[int, str] | None = None

    for lesson in lessons:
        version = await db.select(
            "lesson_versions",
            columns="content",
            filters={"id": f"eq.{lesson['published_version_id']}"},
            single=True,
        )
        sections = (version or {}).get("content", {}).get("sections") or []

        chunks = chunking_service.chunk_lesson(
            sections=sections,
            lesson_number=lesson.get("lesson_number"),
            title=lesson.get("title") or "Untitled",
            hebrew_phrase=lesson.get("hebrew_phrase"),
            transliteration=lesson.get("transliteration"),
        )

        words = sum(c.word_count for c in chunks)
        total_chunks += len(chunks)
        total_words += words
        per_lesson.append(len(chunks))

        label = f"#{lesson.get('lesson_number')}"
        if smallest is None or len(chunks) < smallest[0]:
            smallest = (len(chunks), label)
        if largest is None or len(chunks) > largest[0]:
            largest = (len(chunks), label)

    ordered = sorted(per_lesson)
    print(f"  chunks total        {total_chunks}")
    print(f"  per lesson          min {ordered[0]} · "
          f"median {ordered[len(ordered) // 2]} · max {ordered[-1]}")
    print(f"  fewest / most       {smallest[1]} ({smallest[0]}) / "
          f"{largest[1]} ({largest[0]})")
    print(f"  words indexed       {total_words:,}")

    # ~1.3 tokens per word, plus the context header on each chunk.
    tokens = int(total_words * 1.35) + total_chunks * 20
    print(f"  approx tokens       {tokens:,}")
    print(f"  estimated cost      ${tokens * 0.02 / 1_000_000:.4f}")
    print(f"\n  {DIM}Dry run — nothing was embedded or written.{RESET}\n")
    return 0


async def run() -> int:
    settings = get_settings()
    if settings.llm_mode != "live":
        print(
            f"  {YELLOW}LLM_MODE is '{settings.llm_mode}'.{RESET} "
            f"Mock embeddings are deterministic hashes and are useless for "
            f"retrieval.\n  Set LLM_MODE=live to build a real index.\n"
        )
        return 1

    lessons = await published_lessons()
    before = await usage_tracker.total_spend(refresh=True)

    print(f"\n{BOLD}  Indexing {len(lessons)} lessons{RESET}")
    print(f"  {DIM}spend before ${before:.4f}{RESET}\n")

    indexed = 0
    chunks = 0
    failures: list[tuple[str, str]] = []

    for lesson in lessons:
        label = (
            f"#{lesson['lesson_number']}"
            if lesson.get("lesson_number") is not None
            else lesson["id"][:8]
        )
        try:
            result = await indexing_service.index_lesson(lesson["id"])
            chunks += result["chunks"]
            indexed += 1
            print(f"  {GREEN}{result['chunks']:>3} chunks{RESET}  {label:>5}  "
                  f"{(lesson.get('title') or '')[:52]}")
        except Exception as exc:
            failures.append((label, str(exc)))
            print(f"  {RED}   failed{RESET}  {label:>5}  {exc}")

    after = await usage_tracker.total_spend(refresh=True)

    print(f"\n  {DIM}{'─' * 66}{RESET}")
    print(f"  {GREEN}{indexed}{RESET} lessons indexed · {chunks} chunks")
    print(f"  cost this run ${after - before:.4f} · total spent ${after:.4f}")

    if failures:
        print(f"\n  {RED}{len(failures)} failed:{RESET}")
        for label, error in failures:
            print(f"    {label}: {error}")
    print()
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(dry_run() if args.dry_run else run())


if __name__ == "__main__":
    raise SystemExit(main())
