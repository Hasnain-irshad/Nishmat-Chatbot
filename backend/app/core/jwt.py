"""
Supabase access-token verification.

The signature is checked against Supabase's published public keys (JWKS), so
the backend never needs a shared secret. Projects still on legacy HS256 tokens
fall back to the symmetric JWT secret if one is configured.

What this module deliberately does NOT do: read a role out of the token. A JWT
tells us *who* is calling, and nothing more. Authority comes from `profiles`
in our own database — see `app/api/deps.py`. Trusting a role claim would mean
anyone able to influence their own user metadata could grant themselves admin.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import jwt
from jwt import PyJWKClient

from app.config import get_settings


# Allowance for clock drift between this server and Supabase's auth service.
LEEWAY_SECONDS = 60


class TokenError(Exception):
    """The token is missing, malformed, expired, or not ours."""


@dataclass(frozen=True)
class TokenClaims:
    subject: str          # auth.users.id
    email: str | None
    expires_at: int
    session_id: str | None


# PyJWKClient caches keys internally and refetches on an unknown `kid`, which
# is what makes key rotation transparent to us.
_jwk_client: PyJWKClient | None = None
_jwk_client_failed_at: float = 0.0
_JWKS_RETRY_SECONDS = 30.0


def _get_jwk_client() -> PyJWKClient | None:
    global _jwk_client, _jwk_client_failed_at

    if _jwk_client is not None:
        return _jwk_client

    # Do not hammer a failing JWKS endpoint on every request.
    if time.monotonic() - _jwk_client_failed_at < _JWKS_RETRY_SECONDS:
        return None

    settings = get_settings()
    try:
        client = PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=600)
        # Force one fetch so a broken URL surfaces here, not mid-request.
        client.fetch_data()
    except Exception:
        _jwk_client_failed_at = time.monotonic()
        return None

    _jwk_client = client
    return _jwk_client


def verify_token(token: str) -> TokenClaims:
    """
    Verify a Supabase access token and return its claims.

    Raises TokenError for anything that is not a valid, unexpired token issued
    by this project.
    """
    if not token or token.count(".") != 2:
        raise TokenError("Malformed token")

    settings = get_settings()

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise TokenError("Malformed token header") from exc

    algorithm = header.get("alg", "")
    options = {"require": ["exp", "sub"]}

    # Tolerate small clock differences between this server and Supabase.
    #
    # Without this, verification fails with ImmatureSignatureError whenever our
    # clock is even a second behind theirs: the token is checked milliseconds
    # after it is issued, so an `iat` a moment in the future reads as "not yet
    # valid". A second of drift between two hosts is entirely normal, and this
    # would otherwise present as intermittent, unreproducible sign-in failures.
    #
    # 60s is the conventional allowance. It does not weaken expiry meaningfully
    # — a token is still rejected within a minute of its real expiry.
    leeway = LEEWAY_SECONDS

    try:
        if algorithm in ("ES256", "RS256"):
            client = _get_jwk_client()
            if client is None:
                raise TokenError("Unable to reach the token signing keys")
            signing_key = client.get_signing_key_from_jwt(token).key
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
                issuer=settings.jwt_issuer,
                leeway=leeway,
                options=options,
            )

        elif algorithm == "HS256":
            if not settings.supabase_jwt_secret:
                raise TokenError(
                    "Token is HS256 but SUPABASE_JWT_SECRET is not configured"
                )
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                leeway=leeway,
                options=options,
            )

        else:
            # Never accept "none", and never accept an algorithm we did not
            # explicitly plan for.
            raise TokenError(f"Unsupported token algorithm: {algorithm!r}")

    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Session expired") from exc
    except jwt.ImmatureSignatureError as exc:
        # Past the leeway, this is a real clock problem on one of the hosts,
        # not a bad token. Name it so it is diagnosable from the logs.
        raise TokenError(
            "Token is not yet valid — the server clock may be out of sync"
        ) from exc
    except jwt.InvalidAudienceError as exc:
        raise TokenError("Token was not issued for this application") from exc
    except jwt.InvalidIssuerError as exc:
        raise TokenError("Token was not issued by this project") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid token") from exc

    subject = payload.get("sub")
    if not subject:
        raise TokenError("Token has no subject")

    return TokenClaims(
        subject=subject,
        email=payload.get("email"),
        expires_at=int(payload.get("exp", 0)),
        session_id=payload.get("session_id"),
    )


async def warm_jwks() -> None:
    """Fetch the signing keys at startup so the first real request is not slow."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(settings.jwks_url)
    except Exception:
        # Not fatal — verify_token retries lazily.
        pass
    _get_jwk_client()
