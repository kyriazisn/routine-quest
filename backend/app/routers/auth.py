from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import DB, SESSION_COOKIE, CurrentParent
from app.mailer import send_magic_link
from app.models import AuthSession, Family, MagicLink, Parent, utcnow
from app.schemas import MagicLinkIn, MeOut, VerifyIn
from app.security import magic_link_limiter, new_token, sha256

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def issue_magic_link(db, email: str, invite_family_id=None) -> None:
    s = get_settings()
    token = new_token()
    db.add(
        MagicLink(
            email=email,
            token_hash=sha256(token),
            invite_family_id=invite_family_id,
            expires_at=utcnow() + timedelta(minutes=s.magic_link_ttl_min),
        )
    )
    db.commit()
    send_magic_link(email, f"{s.public_app_url}/auth?token={token}")


@router.post("/magic-link", status_code=status.HTTP_202_ACCEPTED)
def request_magic_link(body: MagicLinkIn, request: Request, db: DB) -> dict:
    email = body.email.lower()
    ip = request.client.host if request.client else "?"
    if not (magic_link_limiter.allow(f"e:{email}") and magic_link_limiter.allow(f"i:{ip}")):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many requests, try later")
    issue_magic_link(db, email)
    # Same response whether or not the account exists (no account enumeration)
    return {"status": "sent"}


@router.post("/verify", response_model=MeOut)
def verify(body: VerifyIn, response: Response, db: DB) -> MeOut:
    s = get_settings()
    link = db.scalars(select(MagicLink).where(MagicLink.token_hash == sha256(body.token))).first()
    if link is None or link.used_at is not None or link.expires_at <= utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "link invalid or expired")
    link.used_at = utcnow()

    parent = db.scalars(select(Parent).where(Parent.email == link.email)).first()
    if parent is None:
        if link.invite_family_id is not None:
            family_id = link.invite_family_id
        else:
            family = Family()
            db.add(family)
            db.flush()
            family_id = family.id
        parent = Parent(email=link.email, family_id=family_id)
        db.add(parent)
        db.flush()

    token = new_token()
    db.add(
        AuthSession(
            parent_id=parent.id,
            token_hash=sha256(token),
            expires_at=utcnow() + timedelta(days=s.session_ttl_days),
        )
    )
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=s.session_ttl_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )
    from app.routers.parent import me_out

    return me_out(db, parent)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DB, parent: CurrentParent) -> None:
    token = request.cookies.get(SESSION_COOKIE) or request.headers.get("authorization", "").removeprefix(
        "Bearer "
    )
    s = db.scalars(select(AuthSession).where(AuthSession.token_hash == sha256(token))).first()
    if s is not None:
        s.revoked_at = utcnow()
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
