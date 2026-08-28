#!/usr/bin/env python3
"""
Import the client's existing lesson corpus into Supabase.

    # Parse everything and print a report. Touches nothing.
    python backend/scripts/ingest_corpus.py --dry-run

    # Inspect exactly what one document parsed into.
    python backend/scripts/ingest_corpus.py --dry-run --show "Nishmat #17"

    # Load into the database.
    python backend/scripts/ingest_corpus.py

Idempotent: re-running with unchanged text is a no-op. Changed text creates a
new version and republishes it, so imports never rewrite history.

Requires SUPABASE_SERVICE_ROLE_KEY in backend/.env — inserting lessons has to
bypass RLS by design, which the anon key cannot and must not do.
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
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.ingestion import parse_corpus_directory  # noqa: E402
from app.services.ingestion.corpus_parser import ParsedLesson  # noqa: E402

SERIES_ID = "00000000-0000-0000-0000-000000000001"
TEMPLATE_ID = "00000000-0000-0000-0000-000000000010"

GREEN, RED, YELLOW, CYAN, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[2m", "\033[1m", "\033[0m",
)


# --------------------------------------------------------------------------- env


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


# ------------------------------------------------------------------------ client


class SupabaseRPC:
    """Minimal PostgREST caller. Stdlib only — no dependency to install."""

    def __init__(self, url: str, service_key: str):
        self.url = url.rstrip("/")
        self.key = service_key

    # Transient failures are normal over a few hundred sequential requests:
    # dropped connections, brief 5xx, gateway timeouts. Without retries a
    # single blip leaves the corpus half-imported.
    RETRIES = 4
    RETRY_STATUS = {429, 500, 502, 503, 504}

    def call(self, function: str, params: dict) -> list | dict:
        body = json.dumps(params).encode("utf-8")
        last_error = ""

        for attempt in range(self.RETRIES):
            request = urllib.request.Request(
                f"{self.url}/rest/v1/rpc/{function}",
                data=body,
                method="POST",
                headers={
                    "apikey": self.key,
                    "Authorization": f"Bearer {self.key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else []

            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                # A 4xx other than rate-limiting is our bug — do not retry it.
                if exc.code not in self.RETRY_STATUS:
                    raise RuntimeError(
                        f"{function} failed ({exc.code}): {detail}"
                    ) from None
                last_error = f"HTTP {exc.code}: {detail}"

            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = str(exc)

            if attempt < self.RETRIES - 1:
                time.sleep(1.5 * (2**attempt))  # 1.5s, 3s, 6s

        raise RuntimeError(
            f"{function} failed after {self.RETRIES} attempts: {last_error}"
        )


# ------------------------------------------------------------------------ report


def print_report(lessons: list[ParsedLesson]) -> None:
    print(f"\n{BOLD}  Parsed {len(lessons)} documents{RESET}\n")

    numbers = [l.lesson_number for l in lessons if l.lesson_number is not None]
    duplicates = [n for n, c in Counter(numbers).items() if c > 1]

    with_hebrew = sum(1 for l in lessons if l.hebrew_phrase)
    with_translit = sum(1 for l in lessons if l.transliteration)
    with_translation = sum(1 for l in lessons if l.translation)
    with_summary = sum(
        1 for l in lessons if any(s["key"] == "whatsapp_summary" for s in l.sections)
    )
    transcripts = sum(1 for l in lessons if l.is_transcript)
    words = [l.word_count for l in lessons]

    print(f"  {DIM}Coverage{RESET}")
    print(f"    Hebrew phrase       {with_hebrew}/{len(lessons)}")
    print(f"    Transliteration     {with_translit}/{len(lessons)}")
    print(f"    Translation         {with_translation}/{len(lessons)}")
    print(f"    WhatsApp summary    {with_summary}/{len(lessons)}")
    print(f"    Raw transcripts     {transcripts}/{len(lessons)}")
    if words:
        print(
            f"    Words               min {min(words)} · "
            f"median {sorted(words)[len(words) // 2]} · max {max(words)}"
        )

    if numbers:
        expected = set(range(min(numbers), max(numbers) + 1))
        missing = sorted(expected - set(numbers))
        print(f"\n  {DIM}Numbering{RESET}")
        print(f"    Range               #{min(numbers)} – #{max(numbers)}")
        if missing:
            print(f"    {YELLOW}Gaps                {missing}{RESET}")
        if duplicates:
            print(f"    {RED}Duplicates          {sorted(duplicates)}{RESET}")
        if not missing and not duplicates:
            print(f"    {GREEN}Complete, no duplicates{RESET}")

    worst = sorted(lessons, key=lambda l: l.retention)[:5]
    print(f"\n  {DIM}Content retention (parsed words / cleaned source words){RESET}")
    overall = sum(l.captured_words or l.word_count for l in lessons) / max(
        sum(l.raw_word_count for l in lessons), 1
    )
    colour = GREEN if overall >= 0.95 else YELLOW
    print(f"    Overall             {colour}{overall:.1%}{RESET}")
    for lesson in worst:
        mark = GREEN if lesson.retention >= 0.92 else RED
        print(
            f"    {mark}{lesson.retention:6.1%}{RESET} {DIM}{lesson.source_path.name}"
            f" ({lesson.captured_words or lesson.word_count}"
            f"/{lesson.raw_word_count}){RESET}"
        )

    removed = [l for l in lessons if l.removed_text]
    if removed:
        print(f"\n  {DIM}AI-assistant text removed{RESET}")
        for lesson in removed:
            print(f"    {CYAN}{lesson.source_path.name}{RESET}")
            for line in lesson.removed_text[:6]:
                print(f"      {DIM}− {line[:110]}{RESET}")

    flagged = [l for l in lessons if l.needs_review]
    print(f"\n  {DIM}Flagged for review: {len(flagged)}/{len(lessons)}{RESET}")
    for lesson in flagged:
        label = (
            f"#{lesson.lesson_number}"
            if lesson.lesson_number is not None
            else lesson.source_path.stem
        )
        print(f"    {YELLOW}{label:>5}{RESET}  {lesson.source_path.name}")
        for note in lesson.review_notes:
            print(f"           {DIM}· {note}{RESET}")
    print()


def show_lesson(lesson: ParsedLesson) -> None:
    print(f"\n{BOLD}  {lesson.source_path.name}{RESET}")
    print(f"  {DIM}{'─' * 70}{RESET}")
    print(f"  number          {lesson.lesson_number}")
    print(f"  title           {lesson.title}")
    print(f"  series          {lesson.series_title}")
    print(f"  hebrew          {lesson.hebrew_phrase}")
    print(f"  transliteration {lesson.transliteration}")
    print(f"  translation     {lesson.translation}")
    print(f"  summary         {lesson.summary}")
    print(f"  words           {lesson.word_count}")
    print(f"  transcript      {lesson.is_transcript}")
    if lesson.review_notes:
        print(f"  {YELLOW}review{RESET}          {'; '.join(lesson.review_notes)}")
    print(f"\n  {DIM}Sections ({len(lesson.sections)}){RESET}")
    for section in lesson.sections:
        heading = f" [{section['title']}]" if section.get("title") else ""
        preview = section["body"].replace("\n", " ⏎ ")[:120]
        print(
            f"    {section['order']:>2}. {CYAN}{section['key']:<18}{RESET}"
            f"{DIM}{section['dir']}{RESET}{heading}"
        )
        print(f"        {DIM}{preview}{RESET}")
    print()


# -------------------------------------------------------------------------- load


def load(lessons: list[ParsedLesson], rpc: SupabaseRPC) -> None:
    counts = Counter()
    failures: list[tuple[str, str]] = []

    print(f"\n{BOLD}  Importing {len(lessons)} lessons{RESET}\n")

    for lesson in lessons:
        params = {
            "p_series_id": SERIES_ID,
            "p_template_id": TEMPLATE_ID,
            "p_lesson_number": lesson.lesson_number,
            "p_sequence": lesson.sequence_position,
            "p_title": lesson.title,
            "p_hebrew": lesson.hebrew_phrase,
            "p_translit": lesson.transliteration,
            "p_translation": lesson.translation,
            "p_summary": lesson.summary,
            "p_content": {"sections": lesson.sections},
            "p_content_text": lesson.content_text,
            "p_word_count": lesson.word_count,
            "p_needs_review": lesson.needs_review,
            "p_review_notes": "\n".join(lesson.review_notes) or None,
            "p_created_by": None,
        }

        label = (
            f"#{lesson.lesson_number}"
            if lesson.lesson_number is not None
            else lesson.source_path.stem
        )

        try:
            result = rpc.call("import_lesson", params)
            row = result[0] if isinstance(result, list) and result else {}
            action = row.get("action", "?")
            lesson_id = row.get("lesson_id")
            counts[action] += 1

            colour = {"created": GREEN, "updated": CYAN, "unchanged": DIM}.get(
                action, YELLOW
            )
            print(f"  {colour}{action:<10}{RESET} {label:>5}  {lesson.title[:56]}")

            _import_style_example(lesson, lesson_id, rpc)

        except RuntimeError as exc:
            counts["failed"] += 1
            failures.append((label, str(exc)))
            print(f"  {RED}{'failed':<10}{RESET} {label:>5}  {exc}")

    print(f"\n  {DIM}{'─' * 70}{RESET}")
    for action in ("created", "updated", "unchanged", "failed"):
        if counts[action]:
            colour = RED if action == "failed" else GREEN
            print(f"  {colour}{counts[action]:>4}{RESET} {action}")

    if failures:
        print(f"\n  {RED}Failures:{RESET}")
        for label, error in failures:
            print(f"    {label}: {error}")
    print()


def _import_style_example(
    lesson: ParsedLesson, lesson_id: str | None, rpc: SupabaseRPC
) -> None:
    """
    Register the lesson as a style example the generator can learn from.

    Approved automatically only when the parse was clean — a stub or a document
    that still needed manual review is not something we want the AI imitating.
    """
    if lesson.word_count < 300:
        return

    tags = []
    if lesson.hebrew_phrase:
        tags.append("hebrew")
    if lesson.is_transcript:
        tags.append("transcript")
    else:
        tags.append("polished")
    if any(s["key"] == "whatsapp_summary" for s in lesson.sections):
        tags.append("has-summary")

    rpc.call(
        "upsert_style_example",
        {
            "p_title": lesson.source_path.stem,
            "p_source_text": None,
            "p_final_text": lesson.content_text,
            "p_tags": tags,
            "p_is_approved": not lesson.needs_review and not lesson.is_transcript,
            "p_notes": "Imported from the client's existing corpus.",
            "p_lesson_id": lesson_id,
        },
    )


def pair_introduction_with_lesson_one(
    lessons: list[ParsedLesson], rpc: SupabaseRPC
) -> None:
    """
    `Nishmat Introduction.docx` is the raw transcript of the recording that
    became the polished `Nishmat #1.docx`. That makes it the corpus's one
    genuine source → final pair, which is worth far more to the style system
    than either document alone.
    """
    intro = next(
        (l for l in lessons if "introduction" in l.source_path.stem.lower()), None
    )
    one = next((l for l in lessons if l.lesson_number == 1), None)
    if not intro or not one:
        return

    rpc.call(
        "upsert_style_example",
        {
            "p_title": "Introduction → Lesson #1 (raw transcript to polished lesson)",
            "p_source_text": intro.content_text,
            "p_final_text": one.content_text,
            "p_tags": ["pair", "transcript-to-polished", "hebrew"],
            "p_is_approved": True,
            "p_notes": (
                "The spoken recording and the polished lesson written from it. "
                "This is the clearest demonstration in the corpus of the "
                "transformation the generator has to reproduce."
            ),
            "p_lesson_id": None,
        },
    )
    print(f"  {GREEN}paired{RESET}     Introduction → Lesson #1 style example")


# -------------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="parse only, write nothing")
    parser.add_argument("--show", metavar="NAME", help="print one parsed document in full")
    parser.add_argument("--data", default="Data", help="corpus directory")
    parser.add_argument("--env", default="backend/.env")
    args = parser.parse_args()

    data_dir = ROOT / args.data
    if not data_dir.is_dir():
        sys.exit(f"{RED}✗{RESET} No corpus directory at {data_dir}")

    lessons = parse_corpus_directory(data_dir)
    if not lessons:
        sys.exit(f"{RED}✗{RESET} No .docx files found in {data_dir}")

    if args.show:
        needle = args.show.lower()
        matches = [l for l in lessons if needle in l.source_path.stem.lower()]
        if not matches:
            sys.exit(f"{RED}✗{RESET} Nothing matching '{args.show}'")
        for lesson in matches[:3]:
            show_lesson(lesson)
        return 0

    print_report(lessons)

    if args.dry_run:
        print(f"  {DIM}Dry run — nothing was written.{RESET}\n")
        return 0

    env = load_env(ROOT / args.env)
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not url or not key:
        sys.exit(
            f"  {RED}✗{RESET} SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set "
            f"in {args.env}.\n"
            f"    Get the service-role key from Supabase → Settings → API.\n"
        )

    rpc = SupabaseRPC(url, key)
    load(lessons, rpc)
    pair_introduction_with_lesson_one(lessons, rpc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

