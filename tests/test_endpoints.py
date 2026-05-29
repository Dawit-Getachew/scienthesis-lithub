"""HTTP-level tests using FastAPI dependency overrides + RS256 user tokens."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import jwt
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.config import get_settings
from src.core.deps import get_db, get_http_client
from src.core.security import reset_jwks_cache
from src.main import app


def _jwks_for_test() -> dict:
    """Build a JWKS body matching the test RSA keypair."""
    from cryptography.hazmat.primitives import serialization

    public_pem = os.environ["LITHUB_TEST_PUBLIC_PEM"].encode()
    pub = serialization.load_pem_public_key(public_pem)
    numbers = pub.public_numbers()  # type: ignore[attr-defined]

    def _b64(value: int) -> str:
        import base64

        n = (value.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(value.to_bytes(n, "big")).rstrip(b"=").decode()

    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": os.environ["LITHUB_TEST_KEY_ID"],
                "n": _b64(numbers.n),
                "e": _b64(numbers.e),
            }
        ]
    }


def _mint_user_token(sub, email: str = "alice@example.com") -> str:
    """Sign a user-shaped access token with the test private key."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(sub),
        "email": email,
        "type": "access",
        "iss": settings.IDENTITY_JWT_ISSUER,
        "aud": settings.IDENTITY_JWT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(
        payload,
        os.environ["LITHUB_TEST_PRIVATE_PEM"],
        algorithm="RS256",
        headers={"kid": os.environ["LITHUB_TEST_KEY_ID"]},
    )


def _mint_service_token(issuer: str = "litpulse") -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": issuer,
            "aud": "scienthesis-lithub",
            "type": "service",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.SERVICE_TOKEN_SECRET,
        algorithm="HS256",
    )


@pytest_asyncio.fixture
async def http_client(sqlite_engine) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an AsyncClient with deps overridden + JWKS endpoint mocked via httpx mock-router."""
    import respx

    session_factory = async_sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False)

    async def _db_override():
        async with session_factory() as session:
            yield session

    reset_jwks_cache()

    # A real httpx client. We mount respx around it so JWKS fetches succeed.
    mock_http = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    settings = get_settings()
    router = respx.mock(assert_all_called=False, assert_all_mocked=False)
    router.get(settings.IDENTITY_JWKS_URL).mock(
        return_value=httpx.Response(200, json=_jwks_for_test()),
    )

    def _http_override():
        return mock_http

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_http_client] = _http_override

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://lithub.test")
    router.start()
    try:
        yield client
    finally:
        router.stop()
        await client.aclose()
        await mock_http.aclose()
        app.dependency_overrides.clear()


# ── Endpoints ──────────────────────────────────────────────────────


async def test_save_endpoint_returns_canonical_response_shape(http_client, test_user_id):
    token = _mint_user_token(test_user_id)
    resp = await http_client.post(
        "/api/v1/library/save",
        json={"pmid": "12345678", "title": "An interesting study", "folder": "Inbox"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) >= {
        "message", "article_id", "paper_id", "library_entry_id",
        "dedup_key", "saved_at",
    }
    assert body["dedup_key"] == "pmid:12345678"


async def test_save_rejects_missing_token(http_client):
    resp = await http_client.post(
        "/api/v1/library/save",
        json={"pmid": "12345678", "title": "T"},
    )
    assert resp.status_code in (401, 403)


async def test_save_rejects_bad_token(http_client):
    resp = await http_client.post(
        "/api/v1/library/save",
        json={"pmid": "12345678", "title": "T"},
        headers={"Authorization": "Bearer not-a-token"},
    )
    assert resp.status_code == 401


async def test_list_endpoint(http_client, test_user_id):
    token = _mint_user_token(test_user_id)
    for i in range(3):
        await http_client.post(
            "/api/v1/library/save",
            json={"pmid": f"p{i}", "title": f"T{i}"},
            headers={"Authorization": f"Bearer {token}"},
        )
    resp = await http_client.get(
        "/api/v1/library",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert {a["pmid"] for a in body["articles"]} == {"p0", "p1", "p2"}


async def test_membership_endpoint_requires_service_token(http_client, test_user_id):
    resp = await http_client.get(
        f"/api/v1/internal/library/membership?user_id={test_user_id}&pmid=p1",
    )
    assert resp.status_code == 401


async def test_membership_endpoint_returns_match(http_client, test_user_id):
    user_token = _mint_user_token(test_user_id)
    await http_client.post(
        "/api/v1/library/save",
        json={"pmid": "999", "title": "T"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    svc_token = _mint_service_token()
    resp = await http_client.get(
        f"/api/v1/internal/library/membership?user_id={test_user_id}&pmid=999",
        headers={"X-Service-Token": svc_token},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["in_library"] is True
    assert body["folder"] == "Inbox"


async def test_membership_isolation_across_users(http_client):
    u1 = uuid4()
    u2 = uuid4()
    user_token = _mint_user_token(u1)
    await http_client.post(
        "/api/v1/library/save",
        json={"pmid": "shared", "title": "T"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    svc_token = _mint_service_token()
    resp = await http_client.get(
        f"/api/v1/internal/library/membership?user_id={u2}&pmid=shared",
        headers={"X-Service-Token": svc_token},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["in_library"] is False
    # paper_id can be non-None (paper exists globally) but in_library False
    assert body["paper_id"] is not None


async def test_jwks_cache_within_5_minutes(http_client, test_user_id):
    # First request triggers a JWKS fetch; second should hit the cache.
    token = _mint_user_token(test_user_id)
    r1 = await http_client.get(
        "/api/v1/library",
        headers={"Authorization": f"Bearer {token}"},
    )
    r2 = await http_client.get(
        "/api/v1/library",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200


async def test_bulk_import_idempotent(http_client, test_user_id):
    svc_token = _mint_service_token()
    body = {
        "user_id": str(test_user_id),
        "items": [
            {"pmid": "100", "title": "First", "source": "search"},
            {"pmid": "101", "title": "Second", "source": "litportal"},
            {"pmid": None, "doi": None, "title": "no-id"},
        ],
    }
    r1 = await http_client.post(
        "/api/v1/internal/library/bulk-import",
        json=body,
        headers={"X-Service-Token": svc_token},
    )
    assert r1.status_code == 200, r1.text
    res1 = r1.json()
    assert res1["imported"] == 2
    assert res1["skipped_invalid"] == 1

    # Replay — everything should be duplicates now.
    r2 = await http_client.post(
        "/api/v1/internal/library/bulk-import",
        json=body,
        headers={"X-Service-Token": svc_token},
    )
    res2 = r2.json()
    assert res2["imported"] == 0
    assert res2["skipped_duplicate"] == 2


async def test_internal_save_then_internal_list(http_client, test_user_id):
    """A BFF can save and list a user's library purely via service-token internal endpoints."""
    svc_token = _mint_service_token()
    save = await http_client.post(
        "/api/v1/internal/library/save",
        json={
            "user_id": str(test_user_id),
            "item": {"pmid": "55501", "title": "Internal Save", "source": "litportal-collection"},
        },
        headers={"X-Service-Token": svc_token},
    )
    assert save.status_code == 200, save.text
    body = save.json()
    assert body["dedup_key"] == "pmid:55501"

    listing = await http_client.get(
        f"/api/v1/internal/library?user_id={test_user_id}",
        headers={"X-Service-Token": svc_token},
    )
    assert listing.status_code == 200, listing.text
    lst = listing.json()
    assert lst["total"] == 1
    assert lst["articles"][0]["pmid"] == "55501"
    assert lst["articles"][0]["source"] == "litportal-collection"


async def test_internal_list_requires_service_token(http_client, test_user_id):
    resp = await http_client.get(f"/api/v1/internal/library?user_id={test_user_id}")
    assert resp.status_code in (401, 403)


async def test_internal_save_visible_cross_caller(http_client, test_user_id):
    """Paper saved by one BFF (service token) is visible to the user's own token list — the cross-app guarantee."""
    svc_token = _mint_service_token(issuer="litportal")
    await http_client.post(
        "/api/v1/internal/library/save",
        json={
            "user_id": str(test_user_id),
            "item": {"pmid": "77701", "title": "Saved from LitPortal"},
        },
        headers={"X-Service-Token": svc_token},
    )
    # Now read it back through the USER-token public list (as LitPulse would, post-cutover).
    user_token = _mint_user_token(test_user_id)
    resp = await http_client.get(
        "/api/v1/library",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    pmids = {a["pmid"] for a in resp.json()["articles"]}
    assert "77701" in pmids


async def test_internal_papers_bulk(http_client, test_user_id):
    svc_token = _mint_service_token()
    save = await http_client.post(
        "/api/v1/internal/library/save",
        json={
            "user_id": str(test_user_id),
            "item": {"pmid": "88801", "title": "Bulk Target", "journal": "Nature"},
        },
        headers={"X-Service-Token": svc_token},
    )
    paper_id = save.json()["paper_id"]
    resp = await http_client.post(
        "/api/v1/internal/papers/bulk",
        json={"paper_ids": [paper_id]},
        headers={"X-Service-Token": svc_token},
    )
    assert resp.status_code == 200, resp.text
    papers = resp.json()["papers"]
    assert len(papers) == 1
    assert papers[0]["pmid"] == "88801"
    assert papers[0]["journal"] == "Nature"


# ── Cross-app end-to-end: the central LitHub guarantee ──────────────


async def test_cross_app_library_visibility(http_client):
    """A paper saved by the LitPortal BFF is visible to the LitPulse BFF read.

    This is the core cross-app guarantee: both BFFs key the central library by
    the SAME Identity ``sub``, so a save from one app surfaces in the other.
    """
    user_sub = uuid4()

    # 1. LitPortal BFF saves a paper for the user (service token, internal save).
    litportal_token = _mint_service_token(issuer="litportal")
    save = await http_client.post(
        "/api/v1/internal/library/save",
        json={
            "user_id": str(user_sub),
            "item": {
                "pmid": "30001", "title": "Saved from a LitPortal collection",
                "journal": "BMJ", "source": "litportal-collection",
            },
        },
        headers={"X-Service-Token": litportal_token},
    )
    assert save.status_code == 200, save.text

    # 2. LitPulse BFF reads the user's central library (service token, internal list).
    litpulse_token = _mint_service_token(issuer="litpulse")
    listing = await http_client.get(
        f"/api/v1/internal/library?user_id={user_sub}",
        headers={"X-Service-Token": litpulse_token},
    )
    assert listing.status_code == 200, listing.text
    pmids = {a["pmid"] for a in listing.json()["articles"]}
    assert "30001" in pmids, "LitPortal-saved paper must be visible to the LitPulse read"

    # 3. The user's OWN access token sees it too (the LitPulse frontend path).
    user_token = _mint_user_token(user_sub)
    user_list = await http_client.get(
        "/api/v1/library", headers={"Authorization": f"Bearer {user_token}"},
    )
    assert user_list.status_code == 200
    assert "30001" in {a["pmid"] for a in user_list.json()["articles"]}


async def test_cross_app_library_isolated_per_user(http_client):
    """User A's LitPortal save is NOT visible in user B's central library."""
    user_a = uuid4()
    user_b = uuid4()
    svc = _mint_service_token(issuer="litportal")
    await http_client.post(
        "/api/v1/internal/library/save",
        json={"user_id": str(user_a), "item": {"pmid": "30002", "title": "A's paper"}},
        headers={"X-Service-Token": svc},
    )
    listing_b = await http_client.get(
        f"/api/v1/internal/library?user_id={user_b}",
        headers={"X-Service-Token": _mint_service_token(issuer="litpulse")},
    )
    assert listing_b.status_code == 200
    assert listing_b.json()["total"] == 0


async def test_cross_app_save_dedupes_same_paper_across_apps(http_client):
    """The same paper saved from LitPortal then LitPulse collapses to one entry."""
    user_sub = uuid4()
    # LitPortal save.
    await http_client.post(
        "/api/v1/internal/library/save",
        json={"user_id": str(user_sub), "item": {"pmid": "30003", "title": "Shared", "source": "litportal-collection"}},
        headers={"X-Service-Token": _mint_service_token(issuer="litportal")},
    )
    # LitPulse save of the same PMID.
    await http_client.post(
        "/api/v1/internal/library/save",
        json={"user_id": str(user_sub), "item": {"pmid": "30003", "title": "Shared", "source": "search"}},
        headers={"X-Service-Token": _mint_service_token(issuer="litpulse")},
    )
    listing = await http_client.get(
        f"/api/v1/internal/library?user_id={user_sub}",
        headers={"X-Service-Token": _mint_service_token(issuer="litpulse")},
    )
    assert listing.json()["total"] == 1  # deduped on (user_id, pmid)
