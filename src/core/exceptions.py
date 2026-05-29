"""Domain exception types used across LitHub layers."""

from __future__ import annotations


class LitHubError(Exception):
    """Base exception for LitHub Service domain errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class AuthenticationError(LitHubError):
    """Raised when JWT validation fails or required claims are missing."""


class ServiceTokenError(LitHubError):
    """Raised when an inbound X-Service-Token is missing, malformed, or rejected."""


class PaperNotFoundError(LitHubError):
    """Raised when a paper lookup by id / pmid / doi finds nothing."""


class LibraryEntryNotFoundError(LitHubError):
    """Raised when a library lookup finds nothing for the user."""


class FolderNotFoundError(LitHubError):
    """Raised when a folder lookup finds nothing for the user."""


class InvalidPaperIdentifiersError(LitHubError):
    """Raised when a save attempt has neither a PMID nor a DOI."""


class JWKSUnavailableError(LitHubError):
    """Raised when no JWKS keys are available and a token must be validated."""
