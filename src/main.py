"""FastAPI application entrypoint for the Scienthesis LitHub Service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import httpx
import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.folders import router as folders_router
from src.api.v1.internal import router as internal_router
from src.api.v1.library import router as library_router
from src.api.v1.papers import router as papers_router
from src.core.config import get_settings
from src.core.database import create_engine, create_session_factory
from src.core.deps import get_db
from src.core.exceptions import LitHubError
from src.core.logging import configure_logging
from src.core.middleware import (
    RequestIDMiddleware,
    StructuredLoggingMiddleware,
    domain_exception_handler,
)
from src.core.redis import create_redis_pool

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(debug=settings.DEBUG)

    engine = create_engine()
    db_session_factory = create_session_factory(engine)
    redis_client = create_redis_pool()
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))

    app.state.engine = engine
    app.state.db_session_factory = db_session_factory
    app.state.redis = redis_client
    app.state.http_client = http_client
    logger.info("lithub_startup_complete")

    try:
        yield
    finally:
        await http_client.aclose()
        await redis_client.aclose()
        await engine.dispose()
        logger.info("lithub_shutdown_complete")


app = FastAPI(
    title="Scienthesis LitHub",
    version="0.1.0",
    lifespan=lifespan,
)
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(StructuredLoggingMiddleware)
app.add_exception_handler(LitHubError, domain_exception_handler)

app.include_router(library_router, prefix="/api/v1")
app.include_router(folders_router, prefix="/api/v1")
app.include_router(papers_router, prefix="/api/v1")
app.include_router(internal_router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "Scienthesis LitHub", "version": "0.1.0", "status": "ok"}


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    database_status = "connected"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        database_status = "unavailable"
    return {"status": "ok", "database": database_status}
