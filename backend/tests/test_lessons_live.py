"""
Lesson management, versioning and publishing.

Read tests run against the client's real imported corpus. Every test that
*mutates* anything works on a scratch lesson it creates and removes, so a test
run can never damage the client's own work.

The important assertions here are the product rules:

  * editing creates a new version and never touches the published one;
  * a learner sees only what has been explicitly published;
  * unpublishing removes a lesson from the chatbot index in the same action.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
API = "http://127.0.0.1:8000"
SERIES_ID = "00000000-0000-0000-0000-000000000001"


def _env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / "backend" / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


ENV = _env()
SUPABASE_URL = ENV.get("SUPABASE_URL", "").rstrip("/")
ANON = ENV.get("SUPABASE_ANON_KEY", "")
SERVICE = ENV.get("SUPABASE_SERVICE_ROLE_KEY", "")

pytestmark = pytest.mark.skipif(
    not (SUPABASE_URL and ANON and SERVICE), reason="Supabase not configured"
)


# --------------------------------------------------------------------- setup


@pytest.fixture(scope="module")
def service_headers() -> dict[str, str]:
    return {
        "apikey": SERVICE,
        "Authorization": f"Bearer {SERVICE}",
        "Content-Type": "application/json",
    }


@pytest.fixture(scope="module")
def api() -> httpx.Client:
    client = httpx.Client(base_url=API, timeout=60)
    try:
        client.get("/health").raise_for_status()
    except Exception:
        pytest.skip(f"API not reachable at {API}")
    return client


@pytest.fixture(scope="module")
def accounts(service_headers):
    made: list[str] = []

    def create(role: str) -> dict:
        email = f"nishmat-lesson-{uuid.uuid4().hex[:10]}@example.com"
        password = uuid.uuid4().hex + "Aa1!"
        with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
            user_id = client.post(
                "/auth/v1/admin/users",
                headers=service_headers,
                json={"email": email, "password": password, "email_confirm": True},
            ).json()["id"]
            made.append(user_id)

            if role == "admin":
                client.patch(
                    "/rest/v1/profiles",
                    params={"id": f"eq.{user_id}"},
                    headers=service_headers,
                    json={"role": "admin"},
                )

            token = client.post(
                "/auth/v1/token",
                params={"grant_type": "password"},
                headers={"apikey": ANON, "Content-Type": "application/json"},
                json={"email": email, "password": password},
            ).json()["access_token"]

        return {"id": user_id, "headers": {"Authorization": f"Bearer {token}"}}

    yield {"admin": create("admin"), "learner": create("user")}

    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        for user_id in made:
            client.delete(f"/auth/v1/admin/users/{user_id}", headers=service_headers)


SCRATCH_NUMBER = 9001


def _purge_scratch(service_headers: dict[str, str]) -> None:
    """
    Remove a scratch lesson left behind by a crashed run.

    `lesson_number` is unique per series, so a stale row makes every
    subsequent run fail at fixture setup with a constraint violation that
    looks nothing like its actual cause.
    """
    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        rows = client.get(
            "/rest/v1/lessons",
            params={"lesson_number": f"eq.{SCRATCH_NUMBER}", "select": "id"},
            headers=service_headers,
        ).json()
        for row in rows if isinstance(rows, list) else []:
            lesson_id = row["id"]
            client.delete("/rest/v1/lesson_chunks",
                          params={"lesson_id": f"eq.{lesson_id}"}, headers=service_headers)
            client.patch("/rest/v1/lessons", params={"id": f"eq.{lesson_id}"},
                         headers=service_headers,
                         json={"current_version_id": None, "published_version_id": None})
            client.delete("/rest/v1/lesson_versions",
                          params={"lesson_id": f"eq.{lesson_id}"}, headers=service_headers)
            client.delete("/rest/v1/jobs",
                          params={"lesson_id": f"eq.{lesson_id}"}, headers=service_headers)
            client.delete("/rest/v1/lessons",
                          params={"id": f"eq.{lesson_id}"}, headers=service_headers)


@pytest.fixture
def scratch_lesson(service_headers):
    """A throwaway lesson, hard-deleted afterwards. Never touches real content."""
    _purge_scratch(service_headers)

    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        lesson = client.post(
            "/rest/v1/lessons",
            headers={**service_headers, "Prefer": "return=representation"},
            json={
                "series_id": SERIES_ID,
                "title": "Scratch lesson (test)",
                "lesson_number": SCRATCH_NUMBER,
                "status": "draft",
            },
        ).json()[0]

        version = client.post(
            "/rest/v1/lesson_versions",
            headers={**service_headers, "Prefer": "return=representation"},
            json={
                "lesson_id": lesson["id"],
                "version_number": 1,
                "content": {
                    "sections": [
                        {"key": "series_title", "title": None,
                         "body": "Nishmat: A Journey of Praise", "dir": "ltr", "order": 1},
                        {"key": "body_1", "title": None,
                         "body": "First version body.", "dir": "ltr", "order": 2},
                    ]
                },
                "content_text": "First version body.",
                "word_count": 3,
                "origin": "imported",
            },
        ).json()[0]

        client.patch(
            "/rest/v1/lessons",
            params={"id": f"eq.{lesson['id']}"},
            headers=service_headers,
            json={"current_version_id": version["id"]},
        )

    yield {"lesson_id": lesson["id"], "version_id": version["id"]}

    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        client.delete(
            "/rest/v1/lesson_chunks",
            params={"lesson_id": f"eq.{lesson['id']}"},
            headers=service_headers,
        )
        client.patch(
            "/rest/v1/lessons",
            params={"id": f"eq.{lesson['id']}"},
            headers=service_headers,
            json={"current_version_id": None, "published_version_id": None},
        )
        client.delete(
            "/rest/v1/lesson_versions",
            params={"lesson_id": f"eq.{lesson['id']}"},
            headers=service_headers,
        )
        client.delete(
            "/rest/v1/jobs",
            params={"lesson_id": f"eq.{lesson['id']}"},
            headers=service_headers,
        )
        client.delete(
            "/rest/v1/lessons",
            params={"id": f"eq.{lesson['id']}"},
            headers=service_headers,
        )


# ---------------------------------------------------------------- read tests


def test_admin_sees_the_imported_corpus(api, accounts):
    response = api.get(
        "/admin/lessons", headers=accounts["admin"]["headers"], params={"limit": 200}
    )
    assert response.status_code == 200
    lessons = response.json()
    assert len(lessons) >= 100, "the imported corpus should be visible"

    numbered = [l for l in lessons if l["lesson_number"] is not None]
    # Returned in series order — the series is sequential and order matters.
    assert numbered == sorted(numbered, key=lambda l: l["lesson_number"])


def test_flagged_lessons_can_be_filtered(api, accounts):
    """The 15 lessons the importer flagged must be findable."""
    response = api.get(
        "/admin/lessons",
        headers=accounts["admin"]["headers"],
        params={"needs_review": "true", "limit": 200},
    )
    assert response.status_code == 200
    flagged = response.json()
    assert flagged, "the importer flagged lessons; they should be listed"
    assert all(l["needs_review"] for l in flagged)
    assert all(l["review_notes"] for l in flagged)


def test_search_finds_a_lesson_by_transliteration(api, accounts):
    response = api.get(
        "/admin/lessons",
        headers=accounts["admin"]["headers"],
        params={"q": "Shochen", "limit": 50},
    )
    assert response.status_code == 200
    hits = response.json()
    assert hits, "expected to find the 'Shochen Ad' lessons"
    assert any("shochen" in (l["transliteration"] or "").lower() for l in hits)


def test_an_unknown_status_filter_is_rejected(api, accounts):
    response = api.get(
        "/admin/lessons",
        headers=accounts["admin"]["headers"],
        params={"status": "published,banana"},
    )
    assert response.status_code == 400
    assert "banana" in response.json()["error"]


def test_lesson_detail_includes_the_current_version(api, accounts, scratch_lesson):
    response = api.get(
        f"/admin/lessons/{scratch_lesson['lesson_id']}",
        headers=accounts["admin"]["headers"],
    )
    assert response.status_code == 200
    lesson = response.json()
    assert lesson["current_version"]["version_number"] == 1
    assert lesson["current_version"]["content"]["sections"]


# ------------------------------------------------------------- version tests


def test_editing_creates_a_new_version_and_leaves_the_old_intact(
    api, accounts, scratch_lesson
):
    headers = accounts["admin"]["headers"]
    lesson_id = scratch_lesson["lesson_id"]

    created = api.post(
        f"/admin/lessons/{lesson_id}/versions",
        headers=headers,
        json={
            "content": {
                "sections": [
                    {"key": "body_1", "title": None, "body": "Edited body.",
                     "dir": "ltr", "order": 1}
                ]
            },
            "note": "manual edit",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["version_number"] == 2

    # Version 1 must be untouched — history is not rewritten.
    original = api.get(
        f"/admin/lessons/{lesson_id}/versions/{scratch_lesson['version_id']}",
        headers=headers,
    ).json()
    assert original["content_text"] == "First version body."

    versions = api.get(f"/admin/lessons/{lesson_id}/versions", headers=headers).json()
    assert [v["version_number"] for v in versions] == [2, 1]
    assert versions[0]["is_current"] and not versions[0]["is_published"]


def test_restoring_moves_forward_rather_than_rewinding(api, accounts, scratch_lesson):
    """Restoring v1 must create v3, not delete v2."""
    headers = accounts["admin"]["headers"]
    lesson_id = scratch_lesson["lesson_id"]

    api.post(
        f"/admin/lessons/{lesson_id}/versions",
        headers=headers,
        json={"content": {"sections": [
            {"key": "body_1", "title": None, "body": "Second.", "dir": "ltr", "order": 1}
        ]}},
    )

    restored = api.post(
        f"/admin/lessons/{lesson_id}/versions/{scratch_lesson['version_id']}/restore",
        headers=headers,
    )
    assert restored.status_code == 201, restored.text
    body = restored.json()
    assert body["version_number"] == 3

    # Restore reproduces the *content*. `content_text` is a derived field —
    # it is recomputed from the sections rather than copied, so comparing it
    # would be asserting on the derivation, not on the restore.
    original = api.get(
        f"/admin/lessons/{lesson_id}/versions/{scratch_lesson['version_id']}",
        headers=headers,
    ).json()
    assert body["content"]["sections"] == original["content"]["sections"]
    assert "First version body." in body["content_text"]

    versions = api.get(f"/admin/lessons/{lesson_id}/versions", headers=headers).json()
    assert len(versions) == 3, "restoring must not delete the intervening version"


def test_an_empty_version_is_refused(api, accounts, scratch_lesson):
    response = api.post(
        f"/admin/lessons/{scratch_lesson['lesson_id']}/versions",
        headers=accounts["admin"]["headers"],
        json={"content": {"sections": []}},
    )
    assert response.status_code == 400


# ------------------------------------------------------------- publish tests


def test_publishing_makes_a_lesson_visible_to_learners(
    api, accounts, scratch_lesson, service_headers
):
    headers = accounts["admin"]["headers"]
    lesson_id = scratch_lesson["lesson_id"]

    published = api.post(
        f"/admin/lessons/{lesson_id}/publish",
        headers=headers,
        json={"version_id": scratch_lesson["version_id"]},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    # Now visible through the anon key, which is what a learner uses.
    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        rows = client.get(
            "/rest/v1/lessons",
            params={"id": f"eq.{lesson_id}", "select": "id,status"},
            headers={"apikey": ANON, "Authorization": f"Bearer {ANON}"},
        ).json()
    assert len(rows) == 1 and rows[0]["status"] == "published"


def test_a_draft_edit_is_invisible_until_published(api, accounts, scratch_lesson):
    """
    The heart of the versioning model: the admin drafts v2 while learners
    continue to see v1, until publish is pressed.
    """
    headers = accounts["admin"]["headers"]
    lesson_id = scratch_lesson["lesson_id"]

    api.post(
        f"/admin/lessons/{lesson_id}/publish",
        headers=headers,
        json={"version_id": scratch_lesson["version_id"]},
    )
    api.post(
        f"/admin/lessons/{lesson_id}/versions",
        headers=headers,
        json={"content": {"sections": [
            {"key": "body_1", "title": None, "body": "Unpublished draft.",
             "dir": "ltr", "order": 1}
        ]}},
    )

    detail = api.get(f"/admin/lessons/{lesson_id}", headers=headers).json()
    assert detail["current_version_id"] != detail["published_version_id"]
    assert detail["has_unpublished_changes"] is True

    # A learner still sees only the published version's text.
    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        versions = client.get(
            "/rest/v1/lesson_versions",
            params={"lesson_id": f"eq.{lesson_id}", "select": "id,content_text"},
            headers={"apikey": ANON, "Authorization": f"Bearer {ANON}"},
        ).json()

    texts = {v["content_text"] for v in versions}
    assert "First version body." in texts
    assert "Unpublished draft." not in texts, "a draft leaked to learners"


def test_unpublishing_hides_the_lesson_and_clears_the_index(
    api, accounts, scratch_lesson, service_headers
):
    headers = accounts["admin"]["headers"]
    lesson_id = scratch_lesson["lesson_id"]

    api.post(
        f"/admin/lessons/{lesson_id}/publish",
        headers=headers,
        json={"version_id": scratch_lesson["version_id"]},
    )

    # Plant a chunk as though the lesson had been indexed.
    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        client.post(
            "/rest/v1/lesson_chunks",
            headers=service_headers,
            json={
                "lesson_id": lesson_id,
                "version_id": scratch_lesson["version_id"],
                "chunk_index": 0,
                "chunk_text": "First version body.",
            },
        )

    response = api.post(f"/admin/lessons/{lesson_id}/unpublish", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "archived"

    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        learner_view = client.get(
            "/rest/v1/lessons",
            params={"id": f"eq.{lesson_id}", "select": "id"},
            headers={"apikey": ANON, "Authorization": f"Bearer {ANON}"},
        ).json()
        chunks = client.get(
            "/rest/v1/lesson_chunks",
            params={"lesson_id": f"eq.{lesson_id}", "select": "id"},
            headers=service_headers,
        ).json()

    assert learner_view == [], "an unpublished lesson is still visible to learners"
    assert chunks == [], "an unpublished lesson is still in the chatbot index"


def test_publishing_a_version_from_another_lesson_is_refused(
    api, accounts, scratch_lesson
):
    """A mistyped id must not expose unrelated content."""
    headers = accounts["admin"]["headers"]

    other = api.get(
        "/admin/lessons", headers=headers, params={"status": "published", "limit": 1}
    ).json()
    if not other:
        pytest.skip("no published lesson to borrow a version from")

    foreign = api.get(
        f"/admin/lessons/{other[0]['id']}/versions", headers=headers
    ).json()[0]

    response = api.post(
        f"/admin/lessons/{scratch_lesson['lesson_id']}/publish",
        headers=headers,
        json={"version_id": foreign["id"]},
    )
    assert response.status_code == 400
    assert "different lesson" in response.json()["error"]


# ------------------------------------------------------------ security tests


def test_a_learner_cannot_read_or_change_lessons(api, accounts, scratch_lesson):
    learner = accounts["learner"]["headers"]
    lesson_id = scratch_lesson["lesson_id"]

    assert api.get("/admin/lessons", headers=learner).status_code == 403
    assert api.get(f"/admin/lessons/{lesson_id}", headers=learner).status_code == 403
    assert api.patch(
        f"/admin/lessons/{lesson_id}", headers=learner, json={"title": "hacked"}
    ).status_code == 403
    assert api.delete(f"/admin/lessons/{lesson_id}", headers=learner).status_code == 403


def test_a_learner_cannot_publish(api, accounts, scratch_lesson):
    """RULE 2: normal users can NEVER publish."""
    learner = accounts["learner"]["headers"]
    response = api.post(
        f"/admin/lessons/{scratch_lesson['lesson_id']}/publish",
        headers=learner,
        json={"version_id": scratch_lesson["version_id"]},
    )
    assert response.status_code == 403

    # And the lesson really did not move.
    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        rows = client.get(
            "/rest/v1/lessons",
            params={"id": f"eq.{scratch_lesson['lesson_id']}", "select": "status"},
            headers={"apikey": SERVICE, "Authorization": f"Bearer {SERVICE}"},
        ).json()
    assert rows[0]["status"] != "published"


def test_a_learner_cannot_create_a_version(api, accounts, scratch_lesson):
    """RULE 3: only an admin may modify lesson content."""
    response = api.post(
        f"/admin/lessons/{scratch_lesson['lesson_id']}/versions",
        headers=accounts["learner"]["headers"],
        json={"content": {"sections": [
            {"key": "body_1", "title": None, "body": "x", "dir": "ltr", "order": 1}
        ]}},
    )
    assert response.status_code == 403
