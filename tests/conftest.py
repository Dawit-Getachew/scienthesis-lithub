"""Pytest fixtures for LitHub tests."""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _generate_rsa_pem() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


# Generated once per session before any `src.*` import — Settings caches.
_PRIVATE_PEM, _PUBLIC_PEM = _generate_rsa_pem()
os.environ.setdefault("APP_NAME", "ScienthesisLitHubTest")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/14")
os.environ.setdefault("IDENTITY_BASE_URL", "http://identity.test")
os.environ.setdefault("IDENTITY_JWKS_URL", "http://identity.test/.well-known/jwks.json")
os.environ.setdefault("IDENTITY_JWT_ISSUER", "scienthesis-identity")
os.environ.setdefault("IDENTITY_JWT_AUDIENCE", "lithub")
os.environ.setdefault("SERVICE_TOKEN_SECRET", secrets.token_urlsafe(32))
os.environ.setdefault("SERVICE_TOKEN_ALLOWED_ISSUERS", "litpulse,litportal,identity")

# Stash the test PEMs so tests can mint user tokens that the LitHub validator
# will accept.
os.environ["LITHUB_TEST_PRIVATE_PEM"] = _PRIVATE_PEM
os.environ["LITHUB_TEST_PUBLIC_PEM"] = _PUBLIC_PEM
os.environ["LITHUB_TEST_KEY_ID"] = "test-key"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator:
    """Yield a fresh in-memory async Redis stand-in."""
    from tests.fakes import FakeAsyncRedis

    client = FakeAsyncRedis()
    yield client
    await client.flushall()


@pytest_asyncio.fixture
async def sqlite_engine():
    """An async aiosqlite engine with the LitHub schema applied."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(sqlite_engine) -> AsyncIterator:
    """Yield one async SQLAlchemy session backed by the in-memory SQLite engine."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_factory = async_sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
def test_user_id():
    """Stable user UUID for per-test isolation."""
    return uuid4()
