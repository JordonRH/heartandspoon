import hashlib
import os
import secrets
import time
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mealie.core.security.hasher import get_hasher
from mealie.db.db_setup import generate_session
from mealie.db.models.users.users import User
from mealie.hearth.models import Audit, Limit, WebSession

PUBLIC_URL = os.getenv("BASE_URL", "https://recipes.jrhtechservices.party").rstrip("/")
COOKIE = "__Host-hearth_session"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def origin(request: Request) -> None:
    if request.headers.get("origin") != PUBLIC_URL:
        raise HTTPException(403, "Request origin rejected")


def csrf(request: Request) -> None:
    origin(request)
    if request.headers.get("x-hearth-request") != "1":
        raise HTTPException(403, "Request verification missing")


def throttle(session: Session, key: str, maximum: int = 12, window: int = 600) -> None:
    key = digest(key)
    row = session.scalar(select(Limit).where(Limit.id == key).with_for_update())
    if row and row.expires > time.time():
        if row.count >= maximum:
            raise HTTPException(429, "Too many attempts. Try again later.")
        row.count += 1
    else:
        if row:
            row.count = 1
            row.expires = time.time() + window
        else:
            session.add(Limit(id=key, owner="system", count=1, expires=time.time() + window))
    session.commit()


def check_password(session: Session, username: str, password: str) -> User:
    if not isinstance(username, str) or not isinstance(password, str) or len(username) > 240 or not 1 <= len(password.encode()) <= 72:
        raise HTTPException(401, "Email or password not accepted")
    user = session.scalar(select(User).where((func.lower(User.username) == username.lower()) | (func.lower(User.email) == username.lower())))
    ready = session.scalar(select(Audit.id).where(Audit.action == "owner_configured").limit(1))
    if not user or not ready or user.locked_at is not None:
        # A fixed, non-secret dummy hash avoids leaking account existence through timing.
        get_hasher().verify("invalid", "$2b$12$JdHtJOlkPFwyxdjdygEzPOtYmdQF5/R5tHxw5Tq8pxjubyLqdIX5i")
        raise HTTPException(401, "Email or password not accepted")
    if not get_hasher().verify(password, user.password):
        raise HTTPException(401, "Email or password not accepted")
    return user


def browser_identity(request: Request, session: Session = Depends(generate_session)) -> tuple[str, str]:
    raw = request.cookies.get(COOKIE, "")
    row = session.get(WebSession, digest(raw)) if raw else None
    if not row or min(row.expires, row.absolute_expires) <= time.time():
        raise HTTPException(401, "Please sign in")
    user = session.get(User, UUID(row.owner))
    if not user or user.locked_at is not None:
        raise HTTPException(401, "Account unavailable")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        csrf(request)
    # Do not hold a transaction open across downstream operations.
    owner, key = row.owner, row.id
    row.expires = min(time.time() + 86400, row.absolute_expires)
    session.commit()
    return owner, key


def new_browser_session(session: Session, user: User) -> str:
    token = secrets.token_urlsafe(48)
    session.add(WebSession(id=digest(token), owner=str(user.id), expires=time.time() + 86400,
                           absolute_expires=time.time() + 7 * 86400))
    session.commit()
    return token
