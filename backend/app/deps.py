import uuid
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuthSession, Child, Device, Parent, utcnow
from app.security import sha256

SESSION_COOKIE = "rq_session"

DB = Annotated[Session, Depends(get_db)]


def current_parent(
    db: DB,
    rq_session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> Parent:
    """Session from the HttpOnly cookie (PWA) or a Bearer header (tests, tooling)."""
    token = rq_session
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    s = db.scalars(select(AuthSession).where(AuthSession.token_hash == sha256(token))).first()
    if s is None or s.revoked_at is not None or s.expires_at <= utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
    parent = db.get(Parent, s.parent_id)
    if parent is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
    return parent


CurrentParent = Annotated[Parent, Depends(current_parent)]


def owned_child(db: Session, parent: Parent, child_id: uuid.UUID) -> Child:
    child = db.get(Child, child_id)
    if child is None or child.family_id != parent.family_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "child not found")  # never reveal other families
    return child


def current_device(
    db: DB,
    authorization: Annotated[str | None, Header()] = None,
    x_device_id: Annotated[str | None, Header()] = None,
) -> Device:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "device token required")
    token = authorization.removeprefix("Bearer ")
    dev = db.scalars(select(Device).where(Device.token_hash == sha256(token))).first()
    if dev is None or dev.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "device token revoked")
    if x_device_id is not None and x_device_id != dev.device_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "device id mismatch")
    dev.last_seen_at = utcnow()
    return dev


CurrentDevice = Annotated[Device, Depends(current_device)]
