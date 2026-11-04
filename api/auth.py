import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, PyJWTError
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError


bearer_scheme = HTTPBearer(auto_error=False)
ALLOWED_ALGORITHMS = ("RS256",)
DEFAULT_REQUIRED_SCOPE = "catalog:access"


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str
    audience: str
    jwks_url: str
    required_scope: str

    @classmethod
    def from_environment(cls) -> "OIDCSettings":
        issuer = os.environ.get("AUTH0_ISSUER", "").strip()
        audience = os.environ.get("AUTH0_AUDIENCE", "").strip()
        jwks_url = os.environ.get("AUTH0_JWKS_URL", "").strip()
        required_scope = os.environ.get(
            "CATALOG_RESCUE_REQUIRED_SCOPE",
            DEFAULT_REQUIRED_SCOPE,
        ).strip()
        if not issuer or not audience or not required_scope:
            raise RuntimeError("OIDC issuer, audience, and required scope must be configured.")
        if not _is_https_url(issuer) or not _is_https_url(
            jwks_url or f"{issuer.rstrip('/')}/.well-known/jwks.json"
        ):
            raise RuntimeError("OIDC issuer and JWKS URL must use HTTPS.")
        return cls(
            issuer=issuer,
            audience=audience,
            jwks_url=jwks_url or f"{issuer.rstrip('/')}/.well-known/jwks.json",
            required_scope=required_scope,
        )


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    email: str | None = None


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True, timeout=5)


def _unauthorized(detail: str = "Bearer token is invalid or expired.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_authenticated_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> VerifiedIdentity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("A bearer token is required.")

    try:
        settings = OIDCSettings.from_environment()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        ) from exc

    try:
        signing_key = _jwks_client(settings.jwks_url).get_signing_key_from_jwt(
            credentials.credentials
        )
        claims: dict[str, Any] = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=list(ALLOWED_ALGORITHMS),
            audience=settings.audience,
            issuer=settings.issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except PyJWKClientConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The authentication provider is temporarily unavailable.",
        ) from exc
    except PyJWKClientError as exc:
        raise _unauthorized() from exc
    except (PyJWTError, ValueError, TypeError) as exc:
        raise _unauthorized() from exc

    scope_claim = claims.get("scope", "")
    scopes = scope_claim.split() if isinstance(scope_claim, str) else []
    if settings.required_scope not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The bearer token does not grant the required API scope.",
            headers={"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{settings.required_scope}"'},
        )

    issuer = claims.get("iss")
    subject = claims.get("sub")
    if not isinstance(issuer, str) or not isinstance(subject, str) or not subject:
        raise _unauthorized()

    email = claims.get("email") if claims.get("email_verified") is True else None
    if email is not None and not isinstance(email, str):
        email = None
    return VerifiedIdentity(issuer=issuer, subject=subject, email=email)
