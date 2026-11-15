import hashlib
import io
import json
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from mealie.core.config import get_app_dirs
from mealie.db.db_setup import generate_session
from mealie.db.models.users.users import User
from mealie.hearth import oauth
from mealie.hearth.auth import COOKIE, PUBLIC_URL, browser_identity, check_password, csrf, new_browser_session, throttle
from mealie.hearth.domain import cooking_view
from mealie.hearth.mcp import MCPAuth, server
from mealie.hearth.models import CookSession, Draft, Food, OAuthGrant, Preference, Revision, WebSession
from mealie.hearth.repository import KitchenRepository, cooking_out, draft_out, revision_out
from mealie.hearth.service import KitchenService
from mealie.middleware.body_size_limit import BodySizeLimitMiddleware

WEB = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    from mealie.db.init_db import main
    main()
    from mealie.db.db_setup import session_context
    from mealie.hearth.catalog import initialize
    with session_context() as session:
        initialize(session)
    (get_app_dirs().DATA_DIR / "hearth-media").mkdir(parents=True, exist_ok=True)
    async with server.session_manager.run():
        yield


app = FastAPI(title="Hearth & Spoon", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.update({
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Cache-Control": "no-store", "X-Frame-Options": "DENY",
        })
        if request.url.path == "/oauth/authorize":
            response.headers["Content-Security-Policy"] = response.headers["Content-Security-Policy"].replace("form-action 'self'", "form-action 'self' https://chatgpt.com")
        return response


app.add_middleware(SecurityHeaders)
app.add_middleware(MCPAuth)
app.add_middleware(BodySizeLimitMiddleware, max_body_size=12 * 1024 * 1024)
app.include_router(oauth.router)


@app.get("/")
def home() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/kitchen/assets/{name}")
def assets(name: str) -> FileResponse:
    if name not in {"app.js", "style.css", "mark.svg"}:
        raise HTTPException(404)
    return FileResponse(WEB / name)


@app.get("/api/health")
def health(session: Session = Depends(generate_session)) -> dict:
    session.execute(text("SELECT 1"))
    return {"status": "ok", "service": "hearth-and-spoon", "engine": "mealie-3.31.0"}


@app.post("/api/kitchen/login")
def login(data: dict, request: Request, session: Session = Depends(generate_session)) -> JSONResponse:
    csrf(request)
    throttle(session, "login:" + (request.client.host if request.client else "unknown"))
    user = check_password(session, data.get("username", ""), data.get("password", ""))
    token = new_browser_session(session, user)
    response = JSONResponse({"name": user.full_name, "email": user.email})
    response.set_cookie(COOKIE, token, max_age=7 * 86400, httponly=True, secure=True, samesite="lax", path="/")
    return response


@app.get("/api/kitchen/me")
def me(identity: tuple = Depends(browser_identity), session: Session = Depends(generate_session)) -> dict:
    user = session.get(User, UUID(identity[0]))
    preference = session.get(Preference, identity[0])
    return {"name": user.full_name, "email": user.email, "mcp": PUBLIC_URL + "/mcp/", "theme": preference.theme if preference else None}


@app.put("/api/kitchen/preferences")
def preferences(data: dict, identity: tuple = Depends(browser_identity), session: Session = Depends(generate_session)) -> dict:
    value = data.get("theme")
    if value not in {"hearth", "midnight", "botanical", "nordic", "contrast"}:
        raise HTTPException(422, "Unknown theme")
    row = session.get(Preference, identity[0])
    if row:
        row.theme = value
    else:
        session.add(Preference(id=identity[0], owner=identity[0], theme=value))
    session.commit()
    return {"theme": value}


@app.post("/api/kitchen/logout")
def logout(identity: tuple = Depends(browser_identity), session: Session = Depends(generate_session)) -> JSONResponse:
    row = session.get(WebSession, identity[1])
    if row:
        session.delete(row)
        session.commit()
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="lax", path="/")
    return response


def service(identity: tuple = Depends(browser_identity), session: Session = Depends(generate_session)) -> KitchenService:
    return KitchenService(KitchenRepository(session, identity[0]))


@app.get("/api/kitchen/recipes")
def recipes(q: str = "", kitchen: KitchenService = Depends(service)) -> list[dict]:
    return kitchen.recipes(q)


@app.get("/api/kitchen/recipes/{recipe_id}")
def recipe(recipe_id: str, kitchen: KitchenService = Depends(service)) -> dict:
    return kitchen.recipe(recipe_id)


@app.get("/api/kitchen/recipes/{recipe_id}/versions")
def versions(recipe_id: str, kitchen: KitchenService = Depends(service)) -> list[dict]:
    kitchen.recipe(recipe_id)
    return [revision_out(row) for row in kitchen.repo.rows(Revision) if row.recipe_id == recipe_id]


@app.get("/api/kitchen/drafts")
def drafts(kitchen: KitchenService = Depends(service)) -> list[dict]:
    return [draft_out(row) for row in kitchen.repo.rows(Draft) if row.status == "draft"]


@app.post("/api/kitchen/drafts/bulk-publish")
def bulk_publish(data: dict, identity: tuple = Depends(browser_identity), kitchen: KitchenService = Depends(service)) -> list[dict]:
    items = data.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise HTTPException(422, "Select between 1 and 100 reviewed changes")
    throttle(kitchen.repo.session, "reauth:" + identity[0])
    user = kitchen.repo.session.get(User, UUID(identity[0]))
    verified = check_password(kitchen.repo.session, user.email, data.get("password", "")) if user else None
    if not verified or str(verified.id) != identity[0]:
        raise HTTPException(403)
    return kitchen.publish_many(items, identity[1])


@app.get("/api/kitchen/drafts/{draft_id}")
def draft(draft_id: str, kitchen: KitchenService = Depends(service)) -> dict:
    return draft_out(kitchen.repo.owned(Draft, draft_id))


@app.post("/api/kitchen/drafts")
def create_draft(data: dict, kitchen: KitchenService = Depends(service)) -> dict:
    return kitchen.create_draft(data.get("document", {}), data.get("recipeId"), data.get("requestId"))


@app.put("/api/kitchen/drafts/{draft_id}")
def update_draft(draft_id: str, data: dict, kitchen: KitchenService = Depends(service)) -> dict:
    return kitchen.update_draft(draft_id, data.get("document", {}), data.get("hash", ""))


@app.post("/api/kitchen/drafts/{draft_id}/review")
def review(draft_id: str, data: dict, identity: tuple = Depends(browser_identity), kitchen: KitchenService = Depends(service)) -> dict:
    return kitchen.review(draft_id, data.get("hash", ""), identity[1])


@app.post("/api/kitchen/drafts/{draft_id}/publish")
def publish(draft_id: str, data: dict, identity: tuple = Depends(browser_identity), kitchen: KitchenService = Depends(service)) -> dict:
    row = kitchen.repo.owned(Draft, draft_id)
    if row.recipe_id:
        throttle(kitchen.repo.session, "reauth:" + identity[0])
        user = kitchen.repo.session.get(User, UUID(identity[0]))
        verified = check_password(kitchen.repo.session, user.email, data.get("password", ""))
        if str(verified.id) != identity[0]:
            raise HTTPException(403)
    return kitchen.publish(draft_id, data.get("hash", ""), identity[1])


@app.post("/api/kitchen/import")
def import_recipe(data: dict, kitchen: KitchenService = Depends(service)) -> dict:
    from mealie.hearth.importer import import_url
    throttle(kitchen.repo.session, "import:" + kitchen.repo.owner, 30, 3600)
    return kitchen.create_draft(import_url(data.get("url", "")))


@app.get("/api/kitchen/foods")
def foods(q: str = "", kitchen: KitchenService = Depends(service)) -> list[dict]:
    rows = kitchen.repo.session.scalars(select(Food).where(Food.name.ilike("%" + q[:120] + "%")).limit(35))
    return [{"id": row.id, "name": row.name, "per100g": row.nutrients, "source": row.source} for row in rows]


@app.post("/api/kitchen/media")
async def media_upload(file: UploadFile, identity: tuple = Depends(browser_identity)) -> dict:
    from mealie.hearth.media import save_image
    raw = await file.read(10_000_001)
    return {"url": save_image(identity[0], raw)}


@app.get("/kitchen/media/{name}")
def media(name: str, identity: tuple = Depends(browser_identity)) -> FileResponse:
    import re
    if not re.fullmatch(r"[a-f0-9]{64}\.webp", name):
        raise HTTPException(404)
    path = get_app_dirs().DATA_DIR / "hearth-media" / identity[0] / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/webp")


@app.post("/api/kitchen/cooking")
def start_cooking(data: dict, kitchen: KitchenService = Depends(service)) -> dict:
    return kitchen.start_cooking(data.get("recipeId", ""), data.get("factor", 1), data.get("components", []), data.get("revision"))


@app.get("/api/kitchen/cooking")
def cooking_sessions(kitchen: KitchenService = Depends(service)) -> list[dict]:
    return [cooking_out(row) for row in kitchen.repo.rows(CookSession)]


@app.get("/api/kitchen/cooking/{key}")
def cooking(key: str, kitchen: KitchenService = Depends(service)) -> dict:
    return kitchen.cooking(key)


@app.put("/api/kitchen/cooking/{key}")
def progress(key: str, data: dict, kitchen: KitchenService = Depends(service)) -> dict:
    return kitchen.progress(key, data.get("completed", []))


@app.get("/api/kitchen/connections")
def connections(kitchen: KitchenService = Depends(service)) -> list[dict]:
    # Grant values are secret-bearing: return only client IDs, scope names and expiry metadata.
    rows = kitchen.repo.rows(OAuthGrant)
    return [{"clientId": row.client_id, "scopes": row.payload.get("scope", ""), "expires": row.expires}
            for row in rows if row.kind == "refresh" and row.expires > time.time()]


@app.delete("/api/kitchen/connections/{client_id}")
def disconnect(client_id: str, kitchen: KitchenService = Depends(service)) -> dict:
    for row in kitchen.repo.session.scalars(select(OAuthGrant).where(OAuthGrant.owner == kitchen.repo.owner, OAuthGrant.client_id == client_id)):
        kitchen.repo.session.delete(row)
    kitchen.repo.event("client_revoked", client_id)
    kitchen.repo.session.commit()
    return {"ok": True}


@app.get("/api/kitchen/export")
def export(kitchen: KitchenService = Depends(service)) -> Response:
    result = {"format": "hearth-and-spoon-1", "recipes": kitchen.recipes(),
              "revisions": [revision_out(row) for row in kitchen.repo.rows(Revision)],
              "drafts": [draft_out(row) for row in kitchen.repo.rows(Draft)]}
    return Response(json.dumps(result), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="hearth-and-spoon.json"'})


app.mount("/", server.streamable_http_app())
