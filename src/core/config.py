"""Application settings loaded from environment variables."""

from __future__ import annotations

import json
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the LitHub Service."""

    APP_NAME: str = "ScienthesisLitHub"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8200

    DATABASE_URL: str
    REDIS_URL: str

    CORS_ORIGINS: str = "*"

    IDENTITY_BASE_URL: str = ""
    IDENTITY_JWKS_URL: str = ""
    IDENTITY_JWT_ISSUER: str = "scienthesis-identity"
    IDENTITY_JWT_AUDIENCE: str = "lithub"
    JWKS_CACHE_TTL_SECONDS: int = 300

    SERVICE_TOKEN_SECRET: str = ""
    SERVICE_TOKEN_ALLOWED_ISSUERS: str = "litpulse,litportal,identity"

    NCBI_API_KEY: str = ""
    NCBI_CONTACT_EMAIL: str = "info@scienthesis.ai"

    PAPER_METADATA_CACHE_TTL_SECONDS: int = 86400  # 24h

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS to a list. Accepts '*', JSON array, or comma-separated."""
        v = self.CORS_ORIGINS.strip()
        if v.startswith("["):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                pass
        return [origin.strip() for origin in v.split(",") if origin.strip()]

    @property
    def service_token_allowed_issuers_list(self) -> list[str]:
        return [i.strip() for i in self.SERVICE_TOKEN_ALLOWED_ISSUERS.split(",") if i.strip()]

    def resolve_jwks_url(self) -> str:
        if self.IDENTITY_JWKS_URL:
            return self.IDENTITY_JWKS_URL
        if self.IDENTITY_BASE_URL:
            return f"{self.IDENTITY_BASE_URL.rstrip('/')}/.well-known/jwks.json"
        raise RuntimeError(
            "LitHub cannot validate tokens: set IDENTITY_BASE_URL or IDENTITY_JWKS_URL.",
        )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
