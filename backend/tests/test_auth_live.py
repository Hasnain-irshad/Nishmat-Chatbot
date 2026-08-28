"""
Live authorisation tests.

These run against the real Supabase project and a running API. They create a
throwaway user, exercise the actual token path, and delete the user again.

This is the suite that protects the product's core rules:

    a learner must not be able to reach an admin endpoint by calling it directly

Mocked tests cannot prove that — the whole risk lives in the real interaction
between Supabase's signing keys, our JWT verification, and the role lookup.

    pytest backend/tests/test_auth_live.py -v

Skipped automatically when the API is not running or credentials are absent,
so it never breaks an offline test run.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
API = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / "backend" / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


ENV = _load_env()
SUPABASE_URL = ENV.get("SUPABASE_URL", "").rstrip("/")
ANON = ENV.get("SUPABASE_ANON_KEY", "")
SERVICE = ENV.get("SUPABASE_SERVICE_ROLE_KEY", "")

pytestmark = pytest.mark.skipif(
    not (SUPABASE_URL and ANON and SERVICE),
    reason="Supabase credentials not configured in backend/.env",
)


# --------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def api() -> httpx.Client:
    client = httpx.Client(base_url=API, timeout=30)
    try:
        client.get("/health").raise_for_status()
    except Exception:
        pytest.skip(f"API not reachable at {API}")
    return client


@pytest.fixture(scope="module")
def admin_headers() -> dict[str, str]:
    return {"apikey": SERVICE, "Authorization": f"Bearer {SERVICE}"}


@pytest.fixture(scope="module")
def test_user(admin_headers):
    """A throwaway learner account, removed when the module finishes."""
    email = f"nishmat-test-{uuid.uuid4().hex[:10]}@example.com"
    password = uuid.uuid4().hex + "Aa1!"

    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        created = client.post(
            "/auth/v1/admin/users",
            headers=admin_headers,
            json={"email": email, "password": password, "email_confirm": True},
        )
        assert created.status_code in (200, 201), created.text
        user_id = created.json()["id"]

        token_response = client.post(
            "/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": ANON, "Content-Type": "application/json"},
            json={"email": email, "password": password},
        )
        assert token_response.status_code == 200, token_response.text
        access_token = token_response.json()["access_token"]

    yield {"id": user_id, "email": email, "token": access_token}

    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        client.delete(f"/auth/v1/admin/users/{user_id}", headers=admin_headers)


def _set_role(user_id: str, role: str, admin_headers: dict[str, str]) -> None:
    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        response = client.patch(
            "/rest/v1/profiles",
            params={"id": f"eq.{user_id}"},
            headers={**admin_headers, "Content-Type": "application/json",
                     "Prefer": "return=representation"},
            json={"role": role},
        )
        assert response.status_code in (200, 204), response.text


# ------------------------------------------------------------------ the tests


def test_health_needs_no_auth(api):
    response = api.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_signup_trigger_creates_a_profile_defaulting_to_user(test_user, admin_headers):
    """Role must default to 'user'. Nothing a person supplies may influence it."""
    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as client:
        response = client.get(
            "/rest/v1/profiles",
            params={"id": f"eq.{test_user['id']}", "select": "id,email,role"},
            headers=admin_headers,
        )
    rows = response.json()
    assert len(rows) == 1, "the signup trigger did not create a profile"
    assert rows[0]["role"] == "user"


def test_me_returns_the_signed_in_learner(api, test_user):
    response = api.get("/me", headers={"Authorization": f"Bearer {test_user['token']}"})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == test_user["email"]
    assert body["role"] == "user"
    assert body["is_admin"] is False


def test_learner_cannot_reach_an_admin_endpoint(api, test_user):
    """RULE 1/2/3: a learner calling the API directly must be refused."""
    response = api.get(
        "/admin/overview", headers={"Authorization": f"Bearer {test_user['token']}"}
    )
    assert response.status_code == 403
    assert "admin" in response.json()["error"].lower()


def test_admin_can_reach_an_admin_endpoint(api, test_user, admin_headers):
    _set_role(test_user["id"], "admin", admin_headers)
    try:
        response = api.get(
            "/admin/overview", headers={"Authorization": f"Bearer {test_user['token']}"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["lessons_total"] >= 0
        assert "ai_spend_usd" in body
    finally:
        _set_role(test_user["id"], "user", admin_headers)


def test_role_change_takes_effect_immediately(api, test_user, admin_headers):
    """
    Role is read from the database on every request, not cached from the token.
    The same unchanged token must lose admin access the moment the role is
    revoked — otherwise a demoted admin keeps their powers until logout.
    """
    headers = {"Authorization": f"Bearer {test_user['token']}"}

    _set_role(test_user["id"], "admin", admin_headers)
    assert api.get("/admin/overview", headers=headers).status_code == 200

    _set_role(test_user["id"], "user", admin_headers)
    assert api.get("/admin/overview", headers=headers).status_code == 403


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({}, 401),
        ({"Authorization": "Bearer not-a-token"}, 401),
        ({"Authorization": "Basic abc123"}, 401),
        ({"Authorization": "Bearer"}, 401),
        ({"Authorization": "Bearer a.b.c"}, 401),
    ],
    ids=["missing", "garbage", "wrong-scheme", "no-token", "fake-jwt-shape"],
)
def test_bad_credentials_are_rejected(api, headers, expected):
    assert api.get("/me", headers=headers).status_code == expected
    assert api.get("/admin/overview", headers=headers).status_code == expected


def test_a_tampered_token_is_rejected(api, test_user):
    """Flipping the payload must invalidate the signature."""
    header, payload, signature = test_user["token"].split(".")
    tampered = f"{header}.{payload[:-4]}AAAA.{signature}"
    response = api.get("/me", headers={"Authorization": f"Bearer {tampered}"})
    assert response.status_code == 401


def test_the_anon_key_is_not_a_valid_user_token(api):
    """
    The publishable key is a JWT, and it is public. It must never be accepted
    as proof of identity.
    """
    response = api.get("/me", headers={"Authorization": f"Bearer {ANON}"})
    assert response.status_code in (401, 403)


def test_every_admin_route_carries_the_admin_dependency():
    """
    Structural guarantee: the check lives on the router, so a new admin
    endpoint cannot ship without it. This test fails if someone mounts an
    admin route another way.
    """
    from app.api.deps import require_admin
    from app.main import create_app

    app = create_app()
    unprotected = []

    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/admin"):
            continue
        dependant = getattr(route, "dependant", None)
        calls = {d.call for d in getattr(dependant, "dependencies", [])}
        # require_admin may appear directly, or nested under another dependency.
        if require_admin not in calls and not _has_nested(dependant, require_admin):
            unprotected.append(path)

    assert not unprotected, f"admin routes missing require_admin: {unprotected}"


def _has_nested(dependant, target) -> bool:
    if dependant is None:
        return False
    for sub in getattr(dependant, "dependencies", []):
        if sub.call is target or _has_nested(sub, target):
            return True
    return False
