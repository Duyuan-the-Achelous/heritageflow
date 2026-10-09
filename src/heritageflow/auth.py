from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, Request, status


ALLOWED_ROLES = {"platform_admin", "tenant_admin", "validator", "visitor"}


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    role: str


def authenticate(request: Request, authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    settings = request.app.state.settings

    configured = settings.api_keys.get(token)
    if configured:
        principal = Principal(
            tenant_id=str(configured.get("tenant_id", "")),
            role=str(configured.get("role", "")),
        )
    elif settings.environment == "development" and token.startswith("demo:"):
        parts = token.split(":", 2)
        if len(parts) != 3:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid demo token")
        principal = Principal(tenant_id=parts[1], role=parts[2])
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")

    if not principal.tenant_id or principal.role not in ALLOWED_ROLES:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token mapping")
    return principal


def require_roles(principal: Principal, *roles: str) -> None:
    if principal.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="role not permitted")

