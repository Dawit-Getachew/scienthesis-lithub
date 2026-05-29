"""Request tracing, logging middleware, and domain exception handler."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.exceptions import (
    AuthenticationError,
    FolderNotFoundError,
    InvalidPaperIdentifiersError,
    JWKSUnavailableError,
    LibraryEntryNotFoundError,
    LitHubError,
    PaperNotFoundError,
    ServiceTokenError,
)

logger = structlog.get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> JSONResponse:
        request_id = str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> JSONResponse:
        started_at = perf_counter()
        response = await call_next(request)
        duration_ms = (perf_counter() - started_at) * 1000
        request_id = getattr(request.state, "request_id", None)

        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
            request_id=request_id,
        )
        return response


async def domain_exception_handler(request: Request, exc: LitHubError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)

    if isinstance(exc, AuthenticationError):
        status_code = 401
    elif isinstance(exc, ServiceTokenError):
        status_code = 401
    elif isinstance(exc, (PaperNotFoundError, LibraryEntryNotFoundError, FolderNotFoundError)):
        status_code = 404
    elif isinstance(exc, InvalidPaperIdentifiersError):
        status_code = 422
    elif isinstance(exc, JWKSUnavailableError):
        status_code = 503
    else:
        status_code = 500

    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.message, "request_id": request_id},
    )
