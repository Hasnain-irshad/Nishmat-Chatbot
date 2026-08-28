"""
End-to-end check of the deployed lesson-generation pipeline.

    python -m scripts.verify_production

Drives the REAL production API at Railway, as a real admin, through the whole
admin workflow the client will use:

    corpus visible -> create a lesson from a brief -> attach a photographed
    page -> generate -> read the draft back -> check what it was written from

Then deletes everything it created, including the temporary account.

Why a temporary account rather than a stored one: signing in as the client's
own admin would need their password, and minting a magic link for them would
send them an email about a test. This creates a throwaway user, promotes it,
uses it, and removes it.

Nothing here is a substitute for the unit tests — it answers a different
question. The unit tests say the code is correct; this says the thing actually
deployed, talking to the actual database, does the job.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402

API = "https://nishmat-ai-production.up.railway.app"

ROOT = Path(__file__).resolve().parents[2]
PAGE_IMAGE = (
    ROOT / "Reference" / "Nishmat" / "edut_hamizrach"
    / "nishmat_edut_hamizrach_original.png"
)

# A phrase from the middle of the prayer, pointed exactly as the siddur has it.
# Chosen because the stanza it belongs to is not the opening one — matching it
# proves the lookup found the right stanza rather than simply the first.
TEST_PHRASE = "וְרוֹפֵא חוֹלִים"

# Far above the real series, so nothing in it can collide with a real lesson
# even for the moments this exists.
TEST_LESSON_NUMBER = 9001

PASS, FAIL, INFO = "  [PASS]", "  [FAIL]", "       -"


class Checks:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def ok(self, label: str, condition: bool, detail: str = "") -> bool:
        print(f"{PASS if condition else FAIL} {label}" + (f"  {detail}" if detail else ""))
        if not condition:
            self.failures.append(label)
        return condition

    def note(self, text: str) -> None:
        print(f"{INFO} {text}")


async def main() -> int:
    settings = get_settings()
    base = settings.supabase_url
    service_key = settings.supabase_service_role_key
    checks = Checks()

    admin_headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    email = f"deploy-check+{uuid.uuid4().hex[:10]}@nishmat.local"
    password = f"Tv{uuid.uuid4().hex}!Aa1"

    user_id: str | None = None
    lesson_id: str | None = None

    async with httpx.AsyncClient(timeout=120) as http:
        try:
            # ---------------------------------------------- temporary admin
            created = await http.post(
                f"{base}/auth/v1/admin/users",
                headers=admin_headers,
                json={"email": email, "password": password, "email_confirm": True},
            )
            if created.status_code >= 400:
                print(f"{FAIL} could not create the check account: {created.text[:200]}")
                return 1
            user_id = created.json()["id"]

            await http.patch(
                f"{base}/rest/v1/profiles?id=eq.{user_id}",
                headers={**admin_headers, "Content-Type": "application/json"},
                json={"role": "admin"},
            )

            token_response = await http.post(
                f"{base}/auth/v1/token?grant_type=password",
                headers={"apikey": settings.supabase_anon_key},
                json={"email": email, "password": password},
            )
            token = token_response.json().get("access_token")
            if not checks.ok("signed in as an admin", bool(token)):
                return 1

            auth = {"Authorization": f"Bearer {token}"}

            # ------------------------------------------------- the corpus
            corpus = (await http.get(f"{API}/admin/references/corpus", headers=auth)).json()
            documents = corpus.get("documents", [])
            kinds = {d["kind"] for d in documents}

            checks.ok(
                "the deployed API serves the reference corpus",
                {"nishmat_text", "scripture", "commentary"} <= kinds,
                f"{len(documents)} documents",
            )
            for document in documents:
                checks.note(
                    f"{document['title']} — {document['chunks']} chunks "
                    f"({document['authority']})"
                )
            checks.note(f"not held: {', '.join(corpus.get('missing', [])) or 'nothing'}")

            # ------------------------------------------ a brief-led lesson
            lesson = (
                await http.post(
                    f"{API}/admin/lessons",
                    headers=auth,
                    json={
                        "title": "[deployment check] please ignore",
                        "lesson_number": TEST_LESSON_NUMBER,
                        "brief": {
                            "phrase": TEST_PHRASE,
                            "theme": "relying on Hashem when our own strength runs out",
                            "length": "short",
                        },
                    },
                )
            ).json()
            lesson_id = lesson.get("id")
            if not checks.ok(
                "a lesson can be created from a brief with no uploaded file",
                bool(lesson_id),
                str(lesson.get("error", ""))[:120],
            ):
                return 1
            checks.ok(
                "the brief is stored on the lesson",
                (lesson.get("generation_brief") or {}).get("phrase") == TEST_PHRASE,
            )

            # -------------------------------------- a photographed page
            if PAGE_IMAGE.exists():
                upload = await http.post(
                    f"{API}/admin/files/upload",
                    headers=auth,
                    files={"file": (PAGE_IMAGE.name, PAGE_IMAGE.read_bytes(), "image/png")},
                    data={
                        "lesson_id": lesson_id,
                        "role": "reference",
                        "reference_book": "Deployment check — sample page",
                        "reference_page": "1",
                    },
                )
                body = upload.json()
                checks.ok(
                    "a reference page is accepted by the deployed API",
                    upload.status_code < 400 and body.get("role") == "reference",
                    str(body)[:120],
                )

                if body.get("job_id"):
                    # Generous: a full page of vocalised Hebrew is a few
                    # thousand output tokens from the vision model.
                    job = await poll(
                        http, f"{API}/jobs/{body['job_id']}", auth, timeout=420
                    )
                    checks.ok(
                        "the worker read the page and indexed it",
                        job.get("status") == "succeeded"
                        and (job.get("result") or {}).get("reference_chunks", 0) > 0,
                        f"status={job.get('status')} "
                        f"chunks={(job.get('result') or {}).get('reference_chunks')} "
                        f"error={str(job.get('error'))[:100]}",
                    )

                pages = (
                    await http.get(
                        f"{API}/admin/references/lessons/{lesson_id}/pages", headers=auth
                    )
                ).json()
                checks.ok(
                    "the page is listed against the lesson",
                    isinstance(pages, list) and len(pages) == 1,
                    f"{len(pages) if isinstance(pages, list) else '?'} page(s)",
                )
            else:
                checks.note("no sample page image on disk; skipping the upload check")

            # ------------------------------------------------- generation
            queued = await http.post(
                f"{API}/admin/lessons/{lesson_id}/generate", headers=auth, json={}
            )
            job_id = queued.json().get("job_id")
            if not checks.ok(
                "generation was accepted without any uploaded transcript",
                bool(job_id),
                str(queued.json())[:160],
            ):
                return 1

            job = await poll(http, f"{API}/jobs/{job_id}", auth, timeout=420)
            if not checks.ok(
                "the worker generated a draft",
                job.get("status") == "succeeded",
                f"status={job.get('status')} error={str(job.get('error'))[:120]}",
            ):
                return 1

            result = job.get("result") or {}
            references = result.get("references") or {}

            checks.ok(
                "the draft used the stored Nishmat text",
                bool(references.get("primary_text")),
                str(references.get("primary_text")),
            )
            checks.ok(
                "the draft used Tehillim",
                bool(references.get("scripture")),
                str(references.get("scripture")),
            )
            checks.ok(
                "the draft used the uploaded page",
                bool(references.get("uploaded_pages")),
                f"{len(references.get('uploaded_pages') or [])} chunk(s)",
            )
            checks.note(f"sources: {result.get('sources')}")
            checks.note(
                f"{result.get('word_count')} words, verdict {result.get('verdict')}, "
                f"{result.get('issues')} issue(s), ${result.get('cost_usd')}"
            )

            # ------------------------------------------- what came back
            detail = (await http.get(f"{API}/admin/lessons/{lesson_id}", headers=auth)).json()
            version = detail.get("current_version") or {}
            sections = (version.get("content") or {}).get("sections") or []
            metadata = version.get("model_metadata") or {}

            checks.ok("a version was saved", bool(sections), f"{len(sections)} sections")
            checks.ok(
                "it was written by the new pipeline",
                str(metadata.get("prompt_version", "")).startswith("2026-08-26"),
                f"prompt_version={metadata.get('prompt_version')}",
            )
            checks.ok(
                "the lesson is a draft, not published",
                detail.get("status") != "published"
                and not detail.get("published_version_id"),
                f"status={detail.get('status')}",
            )

            hebrew = " ".join(
                s.get("body", "") for s in sections if s.get("dir") == "rtl"
            )
            checks.note(
                f"Hebrew in the draft: {hebrew[:70] if hebrew else '(none in rtl sections)'}"
            )

            checks.ok(
                "the sources used are recorded on the version",
                bool(metadata.get("sources_used")),
                json.dumps(metadata.get("sources_used"), ensure_ascii=False)[:160],
            )

            series = metadata.get("series_context") or {}
            checks.ok(
                "continuity saw earlier lessons",
                bool(series.get("recent")),
                f"recent={series.get('recent')}",
            )

            print("\n  --- first section as generated ---")
            if sections:
                for line in (sections[0].get("body") or "").splitlines()[:8]:
                    print(f"  | {line}")

        finally:
            # ------------------------------------------------------ cleanup
            print("\n  --- cleaning up ---")
            if lesson_id:
                await http.delete(
                    f"{base}/rest/v1/reference_documents?lesson_id=eq.{lesson_id}",
                    headers=admin_headers,
                )
                await http.delete(
                    f"{base}/rest/v1/source_files?lesson_id=eq.{lesson_id}",
                    headers=admin_headers,
                )
                await http.delete(
                    f"{base}/rest/v1/jobs?lesson_id=eq.{lesson_id}", headers=admin_headers
                )
                await http.patch(
                    f"{base}/rest/v1/lessons?id=eq.{lesson_id}",
                    headers={**admin_headers, "Content-Type": "application/json"},
                    json={"current_version_id": None, "published_version_id": None},
                )
                await http.delete(
                    f"{base}/rest/v1/lesson_versions?lesson_id=eq.{lesson_id}",
                    headers=admin_headers,
                )
                await http.delete(
                    f"{base}/rest/v1/lessons?id=eq.{lesson_id}", headers=admin_headers
                )
                print(f"       - removed lesson {lesson_id}")
            if user_id:
                await http.delete(
                    f"{base}/auth/v1/admin/users/{user_id}", headers=admin_headers
                )
                print(f"       - removed the check account")

    print()
    if checks.failures:
        print(f"  {len(checks.failures)} check(s) FAILED:")
        for failure in checks.failures:
            print(f"    - {failure}")
        return 1

    print("  All checks passed against production.")
    return 0


async def poll(http: httpx.AsyncClient, url: str, auth: dict, timeout: int = 300) -> dict:
    """Wait for a job to reach a terminal state, reporting its stage as it goes."""
    deadline = asyncio.get_event_loop().time() + timeout
    last = ""

    while asyncio.get_event_loop().time() < deadline:
        job = (await http.get(url, headers=auth)).json()
        stage = f"{job.get('progress_stage')} ({job.get('progress_pct')}%)"
        if stage != last:
            print(f"{INFO} {stage}")
            last = stage
        if job.get("status") in ("succeeded", "failed", "cancelled"):
            return job
        await asyncio.sleep(3)

    return {"status": "timed out"}


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
