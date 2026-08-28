"""
Load the permanent reference corpus.

    python -m scripts.index_references            # everything not yet loaded
    python -m scripts.index_references --force    # rebuild everything
    python -m scripts.index_references --only nishmat,tehillim
    python -m scripts.index_references --status   # what is loaded, no writes

Run rarely and by a person. The corpus is three documents that change only when
someone hands us a corrected file, and every run costs embeddings — roughly
$0.01 for all three, but there is no reason to pay it twice.

Idempotent: a document is keyed on (kind, variant), so re-running replaces
rather than duplicating. Without `--force` a document already present is
skipped entirely, so the safe thing to do after a deploy is simply run it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import supabase  # noqa: E402
from app.services import reference_indexing  # noqa: E402
from app.services.ingestion.reference_parsers import (  # noqa: E402
    parse_commentary,
    parse_nishmat,
    parse_tehillim,
)

REFERENCE_ROOT = Path(__file__).resolve().parents[2] / "Reference" / "Nishmat"

NUSACH = "Edot HaMizrach"


# Each entry is one document in the corpus. `kind` and `variant` together are
# its identity; `authority` is how far the generator may lean on it, and is the
# field that keeps the client's own reference document from being quoted as
# though it were the prayer.
SOURCES = {
    "nishmat": {
        "path": REFERENCE_ROOT / "edut_hamizrach" / "nishmat_edut_hamizrach.txt",
        "title": "Nishmat Kol Chai — Nusach Edot HaMizrach",
        "kind": "nishmat_text",
        "authority": "primary",
        "variant": NUSACH,
        "language": "he",
        "attribution": "Siddur, Nusach Edot HaMizrach",
        "notes": "The prayer text the teacher davens. Quote exactly.",
    },
    "tehillim": {
        "path": REFERENCE_ROOT / "tehillim" / "tehillim_hebrew_150_psalms.docx",
        "title": "Tehillim — complete Hebrew text, chapters 1–150",
        "kind": "scripture",
        "authority": "primary",
        "variant": "Hebrew 1-150",
        "language": "he",
        "attribution": "Tehillim",
        "notes": "Hebrew with an English rendering beneath each verse.",
    },
    "magnificent": {
        "path": REFERENCE_ROOT / "The magnificent Nishmat Kol Chai.docx",
        "title": "The Magnificent Nishmat Kol Chai",
        "kind": "commentary",
        "authority": "client_supplied",
        "variant": "client reference document",
        "language": "en",
        "attribution": "Supplied by the teacher",
        "notes": (
            "Themes, nusach comparisons and lesson ideas supplied by the client. "
            "Useful for direction. NOT an authority: where it disagrees with the "
            "prayer text or with Tehillim, the primary text is correct."
        ),
    },
}


# ---------------------------------------------------------------- loading


def _docx_paragraphs(path: Path) -> list[str]:
    import docx

    return [p.text for p in docx.Document(str(path)).paragraphs]


def build_chunks(name: str, spec: dict) -> list:
    path: Path = spec["path"]
    if not path.exists():
        raise FileNotFoundError(f"{name}: {path} is not there")

    if name == "nishmat":
        return parse_nishmat(path.read_text(encoding="utf-8"), variant=spec["variant"])
    if name == "tehillim":
        return parse_tehillim(_docx_paragraphs(path))
    return parse_commentary(_docx_paragraphs(path), title=spec["title"])


# ------------------------------------------------------------------ main


async def existing_documents() -> dict[tuple[str, str | None], dict]:
    rows = await supabase.service().select(
        "reference_documents",
        columns="id, title, kind, variant, metadata, updated_at",
        filters={"lesson_id": "is.null"},
    )
    return {(row["kind"], row.get("variant")): row for row in rows or []}


async def run(names: list[str], *, force: bool, status_only: bool) -> int:
    present = await existing_documents()

    if status_only:
        print("Reference corpus:\n")
        for name, spec in SOURCES.items():
            row = present.get((spec["kind"], spec["variant"]))
            if row:
                count = (row.get("metadata") or {}).get("chunk_count", "?")
                print(f"  [loaded] {name:12} {spec['title']}  ({count} chunks)")
            else:
                print(f"  [ MISSING ] {name:12} {spec['title']}")
        extra = set(present) - {(s["kind"], s["variant"]) for s in SOURCES.values()}
        for kind, variant in sorted(extra):
            print(f"  [ extra  ] {kind} / {variant}")
        return 0

    failures = 0
    for name in names:
        spec = SOURCES[name]
        key = (spec["kind"], spec["variant"])

        if key in present and not force:
            count = (present[key].get("metadata") or {}).get("chunk_count", "?")
            print(f"- {name}: already loaded ({count} chunks). --force to rebuild.")
            continue

        try:
            chunks = build_chunks(name, spec)
        except FileNotFoundError as exc:
            print(f"! {name}: {exc}")
            failures += 1
            continue

        print(f"- {name}: {len(chunks)} chunks, embedding…", flush=True)
        try:
            result = await reference_indexing.upsert_document(
                title=spec["title"],
                kind=spec["kind"],
                authority=spec["authority"],
                chunks=chunks,
                variant=spec["variant"],
                language=spec["language"],
                attribution=spec["attribution"],
                notes=spec["notes"],
            )
        except Exception as exc:
            print(f"! {name}: {exc}")
            failures += 1
            continue

        print(f"  indexed {result['chunks']} chunks as {result['document_id']}")

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild even if loaded")
    parser.add_argument("--status", action="store_true", help="report, do not write")
    parser.add_argument(
        "--only",
        default="",
        help=f"comma-separated subset of: {', '.join(SOURCES)}",
    )
    args = parser.parse_args()

    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(SOURCES)
    unknown = set(names) - set(SOURCES)
    if unknown:
        print(f"Unknown source(s): {', '.join(sorted(unknown))}")
        return 2

    return asyncio.run(run(names, force=args.force, status_only=args.status))


if __name__ == "__main__":
    raise SystemExit(main())
