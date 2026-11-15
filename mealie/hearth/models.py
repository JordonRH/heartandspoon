"""Workflow records live in the same database as Mealie recipes."""
import time
from uuid import uuid4

from sqlalchemy import JSON, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mealie.db.models._model_base import SqlAlchemyBase


def new_id() -> str:
    return str(uuid4())


class Record:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    owner: Mapped[str] = mapped_column(String(64), index=True)


class KitchenState(Record, SqlAlchemyBase):
    __tablename__ = "hearth_recipes"
    revision: Mapped[str] = mapped_column(String(64))
    archived: Mapped[bool] = mapped_column(default=False)


class Revision(Record, SqlAlchemyBase):
    __tablename__ = "hearth_revisions"
    __table_args__ = (UniqueConstraint("recipe_id", "number"),)
    recipe_id: Mapped[str] = mapped_column(String(64), index=True)
    number: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))


class Draft(Record, SqlAlchemyBase):
    __tablename__ = "hearth_drafts"
    __table_args__ = (UniqueConstraint("owner", "request_key"),)
    recipe_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="draft")
    reviewed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_session: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CookSession(Record, SqlAlchemyBase):
    __tablename__ = "hearth_cooking_sessions"
    revision: Mapped[str] = mapped_column(String(64))
    selection: Mapped[dict] = mapped_column(JSON)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)


class WebSession(Record, SqlAlchemyBase):
    __tablename__ = "hearth_web_sessions"
    expires: Mapped[float] = mapped_column(Float)
    absolute_expires: Mapped[float] = mapped_column(Float)


class OAuthClient(Record, SqlAlchemyBase):
    __tablename__ = "hearth_oauth_clients"
    name: Mapped[str] = mapped_column(String(240))
    redirects: Mapped[list] = mapped_column(JSON)


class OAuthGrant(Record, SqlAlchemyBase):
    __tablename__ = "hearth_oauth_grants"
    kind: Mapped[str] = mapped_column(String(24))
    client_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    expires: Mapped[float] = mapped_column(Float)


class Food(Record, SqlAlchemyBase):
    __tablename__ = "hearth_foods"
    name: Mapped[str] = mapped_column(Text, index=True)
    nutrients: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(Text)


class Audit(Record, SqlAlchemyBase):
    __tablename__ = "hearth_audit"
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(64))
    at: Mapped[float] = mapped_column(Float, default=time.time)


class Limit(Record, SqlAlchemyBase):
    __tablename__ = "hearth_limits"
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires: Mapped[float] = mapped_column(Float)


class Preference(Record, SqlAlchemyBase):
    __tablename__ = "hearth_preferences"
    theme: Mapped[str] = mapped_column(String(24), default="hearth")


TABLES = [cls.__table__ for cls in (
    KitchenState, Revision, Draft, CookSession, WebSession, OAuthClient, OAuthGrant, Food, Audit, Limit, Preference
)]
