"""
End-to-end upload pipeline.

Real API, real Supabase, real storage, real worker — the only thing mocked is
the model provider, because `LLM_MODE=mock` is the default and development
must never spend the client's budget.

This proves the plumbing that unit tests cannot: that an upload actually
reaches storage, that the worker actually claims the job, and that the
extracted text actually lands back on the row.

Requires the API and the worker to be running:

    python -m uvicorn app.main:app --port 8000
    python -m app.jobs.worker
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "Data"
AUDIO = ROOT / "Audios"
API = "http://127.0.0.1:8000"


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
    not (SUPABASE_URL and ANON and SERVICE),
    reason="Supabase credentials not configured",
)


# --------------------------------------------------------------------- setup


@pytest.fixture(scope="module")
def service_headers() -> dict[str, str]:
    return {"apikey": SERVICE, "Authorization": f"Bearer {SERVICE}"}


@pytest.fixture(scope="module")
def api() -> httpx.Client:
    client = httpx.Client(base_url=API, timeout=120)
    try:
        client.get("/health").raise_for_status()
    except Exception:
        pytest.skip(f"API not reachable at {API}")
    return client


@pytest.fixture(scope="module")
def accounts(service_headers):
    """One admin and one learner, both removed afterwards."""
    made: list[str] = []

    def create(role: str) -> dict:
        email = f"nishmat-e2e-{uuid.uuid4().hex[:10]}@example.com"
        password = uuid.uuid4().hex + "Aa1!"

        with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
            created = client.post(
                "/auth/v1/admin/users",
                headers=service_headers,
                json={"email": email, "password": password, "email_confirm": True},
            )
            created.raise_for_status()
            user_id = created.json()["id"]
            made.append(user_id)

            if role == "admin":
                client.patch(
                    "/rest/v1/profiles",
                    params={"id": f"eq.{user_id}"},
                    headers={**service_headers, "Content-Type": "application/json"},
                    json={"role": "admin"},
                ).raise_for_status()

            token = client.post(
                "/auth/v1/token",
                params={"grant_type": "password"},
                headers={"apikey": ANON, "Content-Type": "application/json"},
                json={"email": email, "password": password},
            ).json()["access_token"]

        return {"id": user_id, "email": email, "headers": {"Authorization": f"Bearer {token}"}}

    yield {"admin": create("admin"), "learner": create("user")}

    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        for user_id in made:
            client.delete(f"/auth/v1/admin/users/{user_id}", headers=service_headers)


@pytest.fixture(scope="module", autouse=True)
def cleanup_uploads(service_headers):
    """
    Remove every source file this module created, and its stored object.

    Also purges *before* the run. Uploads are deduplicated by SHA-256, so a
    row left behind by a crashed run makes the next run's first upload return
    "already uploaded" with no job — which fails in a way that looks like a
    product bug and is not. Tests must be hermetic even after a crash.
    """
    _purge_test_uploads(service_headers)

    created: list[str] = []
    _REGISTRY.append(created)
    yield

    with httpx.Client(base_url=SUPABASE_URL, timeout=60) as client:
        for file_id in created:
            row = client.get(
                "/rest/v1/source_files",
                params={"id": f"eq.{file_id}", "select": "storage_path"},
                headers=service_headers,
            ).json()
            if row:
                client.delete(
                    f"/storage/v1/object/source-files/{row[0]['storage_path']}",
                    headers=service_headers,
                )
            # The job row references the file, so it goes first.
            client.delete(
                "/rest/v1/jobs",
                params={"payload->>source_file_id": f"eq.{file_id}"},
                headers=service_headers,
            )
            client.delete(
                "/rest/v1/source_files",
                params={"id": f"eq.{file_id}"},
                headers=service_headers,
            )


def _purge_test_uploads(service_headers: dict[str, str]) -> None:
    """Delete any source_files matching the corpus fixtures these tests upload."""
    import hashlib

    checksums = []
    for path in list(DATA.glob("Nishmat #*.docx"))[:20] + list(AUDIO.glob("*.ogg")):
        checksums.append(hashlib.sha256(path.read_bytes()).hexdigest())
    if not checksums:
        return

    with httpx.Client(base_url=SUPABASE_URL, timeout=60) as client:
        rows = client.get(
            "/rest/v1/source_files",
            params={
                "checksum_sha256": f"in.({','.join(checksums)})",
                "select": "id,storage_path",
            },
            headers=service_headers,
        ).json()

        for row in rows if isinstance(rows, list) else []:
            client.delete(
                f"/storage/v1/object/source-files/{row['storage_path']}",
                headers=service_headers,
            )
            client.delete(
                "/rest/v1/jobs",
                params={"payload->>source_file_id": f"eq.{row['id']}"},
                headers=service_headers,
            )
            client.delete(
                "/rest/v1/source_files",
                params={"id": f"eq.{row['id']}"},
                headers=service_headers,
            )


_REGISTRY: list[list[str]] = []


def _track(file_id: str) -> str:
    if _REGISTRY:
        _REGISTRY[0].append(file_id)
    return file_id


def _wait_for_job(api: httpx.Client, job_id: str, headers: dict, timeout: int = 90) -> dict:
    """Poll until the job finishes, the way the frontend will."""
    deadline = time.time() + timeout
    last: dict = {}

    while time.time() < deadline:
        response = api.get(f"/jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in ("succeeded", "failed", "cancelled"):
            return last
        time.sleep(1.0)

    pytest.fail(
        f"job {job_id} did not finish within {timeout}s "
        f"(status={last.get('status')}, stage={last.get('progress_stage')}). "
        f"Is the worker running?  python -m app.jobs.worker"
    )


# --------------------------------------------------------------------- tests


def test_docx_upload_extracts_hebrew_end_to_end(api, accounts):
    """Upload a real corpus lesson and get its text back, nikud intact."""
    source = DATA / "Nishmat #17.docx"
    if not source.exists():
        pytest.skip("corpus not present")

    headers = accounts["admin"]["headers"]

    response = api.post(
        "/admin/files/upload",
        headers=headers,
        files={"file": (source.name, source.read_bytes())},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    file_id = _track(body["source_file_id"])

    assert body["kind"] == "docx"
    assert body["job_id"]

    job = _wait_for_job(api, body["job_id"], headers)
    assert job["status"] == "succeeded", job.get("error")
    assert job["result"]["word_count"] > 400

    stored = api.get(f"/admin/files/{file_id}", headers=headers).json()
    assert stored["processing_status"] == "completed"
    # The lesson's real phrase, vowel points and all.
    assert "הַמְנַהֵג" in stored["extracted_text"]
    assert stored["extraction_metadata"]["has_hebrew"] is True


def test_identical_upload_is_deduplicated(api, accounts):
    """Re-uploading the same bytes must not pay to process them again."""
    source = DATA / "Nishmat #17.docx"
    if not source.exists():
        pytest.skip("corpus not present")

    headers = accounts["admin"]["headers"]
    response = api.post(
        "/admin/files/upload",
        headers=headers,
        files={"file": ("renamed-copy.docx", source.read_bytes())},
    )
    assert response.status_code == 202
    body = response.json()

    assert body["duplicate_of"], "identical content should have been deduplicated"
    assert body["job_id"] is None, "a duplicate must not queue another job"


def test_audio_upload_runs_the_transcription_path(api, accounts):
    """
    A real WhatsApp voice note through the real pipeline, transcribed by the
    mock provider — proving the plumbing without spending anything.
    """
    files = sorted(AUDIO.glob("*.ogg"))
    if not files:
        pytest.skip("no audio samples present")

    headers = accounts["admin"]["headers"]
    source = files[0]

    response = api.post(
        "/admin/files/upload",
        headers=headers,
        files={"file": (source.name, source.read_bytes())},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    file_id = _track(body["source_file_id"])
    assert body["kind"] == "audio"

    job = _wait_for_job(api, body["job_id"], headers)
    assert job["status"] == "succeeded", job.get("error")

    stored = api.get(f"/admin/files/{file_id}", headers=headers).json()
    assert stored["processing_status"] == "completed"
    assert stored["extraction_metadata"]["transcript"] is True
    assert any("transcribed from audio" in w
               for w in stored["extraction_metadata"]["warnings"])


def test_admin_can_correct_the_extracted_text(api, accounts):
    """
    The transcript-correction step. Fixing a mangled Hebrew term here is far
    cheaper than fixing the finished lesson.
    """
    source = DATA / "Nishmat #1.docx"
    if not source.exists():
        pytest.skip("corpus not present")

    headers = accounts["admin"]["headers"]
    body = api.post(
        "/admin/files/upload",
        headers=headers,
        files={"file": (source.name, source.read_bytes())},
    ).json()
    file_id = _track(body["source_file_id"])
    _wait_for_job(api, body["job_id"], headers)

    corrected = "Shavua tov. Corrected transcript with הַגָּדוֹל intact."
    response = api.patch(
        f"/admin/files/{file_id}/text",
        headers=headers,
        json={"extracted_text": corrected},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["extracted_text"] == corrected
    assert updated["extraction_metadata"]["manually_corrected"] is True


def test_a_signed_url_is_issued_and_is_not_public(api, accounts):
    source = DATA / "Nishmat #2.docx"
    if not source.exists():
        pytest.skip("corpus not present")

    headers = accounts["admin"]["headers"]
    body = api.post(
        "/admin/files/upload",
        headers=headers,
        files={"file": (source.name, source.read_bytes())},
    ).json()
    file_id = _track(body["source_file_id"])

    signed = api.get(f"/admin/files/{file_id}/download-url", headers=headers)
    assert signed.status_code == 200
    url = signed.json()["url"]
    assert "token=" in url, "the URL must be signed, not public"

    # The signed URL works...
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        assert client.get(url).status_code == 200
        # ...but the same object without the signature does not.
        unsigned = url.split("?")[0].replace("/object/sign/", "/object/public/")
        assert client.get(unsigned).status_code >= 400


def test_a_learner_cannot_touch_source_files(api, accounts):
    """Source material is the client's unpublished work. RULE: admin only."""
    learner = accounts["learner"]["headers"]
    source = DATA / "Nishmat #3.docx"
    if not source.exists():
        pytest.skip("corpus not present")

    upload = api.post(
        "/admin/files/upload",
        headers=learner,
        files={"file": (source.name, source.read_bytes())},
    )
    assert upload.status_code == 403

    assert api.get(f"/admin/files/{uuid.uuid4()}", headers=learner).status_code == 403
    assert api.get(
        f"/admin/files/{uuid.uuid4()}/download-url", headers=learner
    ).status_code == 403


def test_a_learner_cannot_read_someone_elses_job(api, accounts):
    """Job payloads name unpublished lessons, so they are not public."""
    admin = accounts["admin"]["headers"]
    learner = accounts["learner"]["headers"]

    source = DATA / "Nishmat #4.docx"
    if not source.exists():
        pytest.skip("corpus not present")

    body = api.post(
        "/admin/files/upload",
        headers=admin,
        files={"file": (source.name, source.read_bytes())},
    ).json()
    _track(body["source_file_id"])

    # 404 rather than 403 — do not confirm the job exists.
    assert api.get(f"/jobs/{body['job_id']}", headers=learner).status_code == 404


def test_an_unsupported_file_is_refused_before_storage(api, accounts):
    headers = accounts["admin"]["headers"]
    response = api.post(
        "/admin/files/upload",
        headers=headers,
        files={"file": ("payload.bin", b"\x00\x01\x02\x03" * 64)},
    )
    assert response.status_code == 400
    assert "couldn't read that file" in response.json()["error"]


def test_a_mislabelled_file_is_refused(api, accounts):
    """A DOCX renamed to .pdf is almost always the wrong file, not an attack."""
    source = DATA / "Nishmat #5.docx"
    if not source.exists():
        pytest.skip("corpus not present")

    headers = accounts["admin"]["headers"]
    response = api.post(
        "/admin/files/upload",
        headers=headers,
        files={"file": ("lesson.pdf", source.read_bytes())},
    )
    assert response.status_code == 400
    assert "right file" in response.json()["error"]
