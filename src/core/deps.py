"""FastAPI dependency providers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

import httpx
import structlog
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings as get_cached_settings
from src.core.database import get_db_session
from src.core.exceptions import AuthenticationError, ServiceTokenError
from src.core.security import validate_access_token, validate_service_token
from src.repositories.folder_repo import FolderRepository
from src.repositories.library_repo import LibraryRepository
from src.repositories.paper_repo import PaperRepository
from src.services.library_service import LibraryService

logger = structlog.get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=True)


def get_settings() -> Settings:
    return get_cached_settings()


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory = request.app.state.db_session_factory
    async for session in get_db_session(session_factory):
        yield session


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


# ── Repositories ────────────────────────────────────────────────────


async def get_paper_repo(db: AsyncSession = Depends(get_db)) -> PaperRepository:
    return PaperRepository(db=db)


async def get_library_repo(db: AsyncSession = Depends(get_db)) -> LibraryRepository:
    return LibraryRepository(db=db)


async def get_folder_repo(db: AsyncSession = Depends(get_db)) -> FolderRepository:
    return FolderRepository(db=db)


async def get_library_service(
    paper_repo: PaperRepository = Depends(get_paper_repo),
    library_repo: LibraryRepository = Depends(get_library_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
) -> LibraryService:
    return LibraryService(papers=paper_repo, library=library_repo, folders=folder_repo)


# ── Authenticated user ──────────────────────────────────────────────


class AuthenticatedUser:
    """Lightweight bearer of identity claims from the validated user token."""

    def __init__(self, *, sub: UUID, email: str | None) -> None:
        self.id = sub
        self.email = email


async def get_current_user(
    token: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> AuthenticatedUser:
    payload = await validate_access_token(
        token.credentials,
        http_client=http_client,
        settings=get_settings(),
    )
    try:
        user_id = UUID(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthenticationError("Token subject is not a UUID.") from exc
    return AuthenticatedUser(sub=user_id, email=payload.get("email"))


# ── Service-to-service ──────────────────────────────────────────────


async def require_service_token(
    x_service_token: str | None = Header(default=None, alias="X-Service-Token"),
) -> dict:
    if not x_service_token:
        raise ServiceTokenError("Missing X-Service-Token header.")
    return validate_service_token(x_service_token, settings=get_settings())
