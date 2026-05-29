"""Redis client setup."""

from __future__ import annotations

from redis.asyncio import Redis

from src.core.config import get_settings

_redis_client: Redis | None = None


def create_redis_pool() -> Redis:
    global _redis_client
    settings = get_settings()
    _redis_client = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=False,
        max_connections=20,
    )
    return _redis_client


def get_redis() -> Redis:
    if _redis_client is None:
        raise RuntimeError("Redis client has not been initialized. Call create_redis_pool() first.")
    return _redis_client
