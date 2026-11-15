"""ChatGPT OAuth authorization code / PKCE flow, following the local Career Vault pattern."""
import hashlib
import html
import re
import secrets
import time
from base64 import urlsafe_b64encode
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from mealie.db.db_setup import generate_session
from mealie.hearth.auth import COOKIE, PUBLIC_URL, browser_identity, digest, origin, throttle
from mealie.hearth.models import OAuthClient, OAuthGrant

router = APIRouter()
RESOURCE = PUBLIC_URL + "/mcp/"
SCOPES = {"recipes.read", "recipes.write"}


@router.get("/.well-known/oauth-authorization-server")
def metadata() -> dict:
    return {"issuer": PUBLIC_URL, "authorization_endpoint": PUBLIC_URL + "/oauth/authorize",
            "token_endpoint": PUBLIC_URL + "/oauth/token", "registration_endpoint": PUBLIC_URL + "/oauth/register",
            "revocation_endpoint": PUBLIC_URL + "/oauth/revoke", "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"], "scopes_supported": sorted(SCOPES),
            "authorization_response_iss_parameter_supported": True}


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
@router.get("/.well-known/oauth-protected-resource/mcp/")
@router.get("/mcp/.well-known/oauth-protected-resource")
def resource_metadata() -> dict:
    return {"resource": RESOURCE, "authorization_servers": [PUBLIC_URL], "scopes_supported": sorted(SCOPES)}


@router.post("/oauth/register", status_code=201)
def register(request: Request, data: dict, session: Session = Depends(generate_session)) -> dict:
    throttle(session, "registration:" + (request.client.host if request.client else "unknown"), 20, 3600)
    uris = data.get("redirect_uris", [])
    if data.get("token_endpoint_auth_method", "none") != "none" or not isinstance(uris, list) or not 1 <= len(uris) <= 5:
        raise HTTPException(400, "Only public ChatGPT clients are supported")
    for uri in uris:
        parsed = urlsplit(uri)
        chatgpt_callback = parsed.path == "/connector_platform_oauth_redirect" or parsed.path.startswith("/connector/oauth/")
        if parsed.scheme != "https" or parsed.netloc != "chatgpt.com" or not chatgpt_callback or parsed.query or parsed.fragment or len(uri) > 1024:
            raise HTTPException(400, "Only ChatGPT connector HTTPS callbacks are allowed")
    client = OAuthClient(id=secrets.token_urlsafe(24), owner="public", name=str(data.get("client_name", "ChatGPT"))[:240], redirects=uris)
    session.add(client)
    session.commit()
    return {"client_id": client.id, "client_name": client.name, "redirect_uris": client.redirects,
            "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]}


@router.get("/oauth/authorize")
def authorize(request: Request, session: Session = Depends(generate_session)):
    query = dict(request.query_params)
    client = session.get(OAuthClient, query.get("client_id", ""))
    scope = set(query.get("scope", "recipes.read recipes.write").split())
    if not client or query.get("redirect_uri") not in client.redirects or query.get("response_type") != "code" or query.get("code_challenge_method") != "S256" or not re.fullmatch(r"[A-Za-z0-9_-]{43}", query.get("code_challenge", "")) or not scope or not scope <= SCOPES or query.get("resource") != RESOURCE or len(query.get("state", "")) > 2048:
        raise HTTPException(400, "Invalid OAuth authorization request")
    try:
        owner, browser_key = browser_identity(request, session)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        return RedirectResponse("/?connect=" + urlencode({"next": "/oauth/authorize?" + str(request.url.query)})[5:], status_code=303)
    consent = secrets.token_urlsafe(40)
    query["browser"] = browser_key
    query["scope"] = " ".join(sorted(scope))
    session.add(OAuthGrant(id=digest(consent), owner=owner, kind="consent", client_id=client.id, payload=query, expires=time.time() + 600))
    session.commit()
    return HTMLResponse(f'''<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/kitchen/assets/style.css"><title>Connect ChatGPT · Hearth &amp; Spoon</title></head><body><main class="auth-card"><div class="eyebrow">YOUR KITCHEN, CONNECTED</div><h1>Invite ChatGPT<br>to the table.</h1><p>Allow {html.escape(client.name)} to read your recipes{", create drafts and propose changes" if "recipes.write" in scope else ""}.</p><p>Existing recipes stay protected. Changes require two confirmations in your kitchen.</p><form action="/oauth/authorize" method="post"><input type="hidden" name="consent" value="{consent}"><button class="primary">Connect ChatGPT</button></form><a href="/">Cancel</a></main></body></html>''')


@router.post("/oauth/authorize")
async def consent(request: Request, session: Session = Depends(generate_session)):
    origin(request)
    # Consent is an HTML form: session and one-time nonce replace the JSON CSRF header.
    from mealie.hearth.models import WebSession
    browser_key = digest(request.cookies.get(COOKIE, ""))
    browser = session.get(WebSession, browser_key)
    form = await request.form()
    row = session.scalar(select(OAuthGrant).where(OAuthGrant.id == digest(str(form.get("consent", "")))).with_for_update())
    if not browser or min(browser.expires, browser.absolute_expires) <= time.time() or not row or row.kind != "consent" or row.expires <= time.time() or row.owner != browser.owner or row.payload.get("browser") != browser_key:
        raise HTTPException(400, "Consent expired. Restart the connection.")
    payload, client_id, owner = row.payload, row.client_id, row.owner
    code = secrets.token_urlsafe(48)
    session.delete(row)
    session.add(OAuthGrant(id=digest(code), owner=owner, kind="code", client_id=client_id, payload=payload, expires=time.time() + 300))
    session.commit()
    return RedirectResponse(payload["redirect_uri"] + "?" + urlencode({"code": code, "state": payload.get("state", ""), "iss": PUBLIC_URL}), status_code=303)


@router.post("/oauth/token")
async def token(request: Request, session: Session = Depends(generate_session)):
    form = await request.form()
    if form.get("resource") != RESOURCE:
        raise HTTPException(400, "Invalid resource")
    grant_type = form.get("grant_type")
    kind, supplied = ("code", form.get("code")) if grant_type == "authorization_code" else ("refresh", form.get("refresh_token"))
    if grant_type not in ("authorization_code", "refresh_token") or not isinstance(supplied, str):
        raise HTTPException(400, "Invalid grant")
    row = session.scalar(select(OAuthGrant).where(OAuthGrant.id == digest(supplied)).with_for_update())
    if not row or row.kind != kind or row.expires <= time.time() or row.client_id != form.get("client_id"):
        raise HTTPException(400, "Invalid or expired grant")
    if kind == "code":
        verifier = str(form.get("code_verifier", ""))
        challenge = urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        if not 43 <= len(verifier) <= 128 or form.get("redirect_uri") != row.payload.get("redirect_uri") or not secrets.compare_digest(challenge, row.payload.get("code_challenge", "")):
            raise HTTPException(400, "Invalid PKCE verifier or callback")
    owner, client_id, payload = row.owner, row.client_id, row.payload
    session.delete(row)
    access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    for value, kind, duration in ((access, "access", 3600), (refresh, "refresh", 30 * 86400)):
        session.add(OAuthGrant(id=digest(value), owner=owner, kind=kind, client_id=client_id, payload=payload, expires=time.time() + duration))
    session.commit()
    return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": 3600,
                         "refresh_token": refresh, "scope": payload["scope"]}, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.post("/oauth/revoke")
async def revoke(request: Request, session: Session = Depends(generate_session)) -> dict:
    form = await request.form()
    row = session.get(OAuthGrant, digest(str(form.get("token", ""))))
    if row and row.client_id == form.get("client_id"):
        # Revoke every grant for this client / user, including refresh and consent.
        for grant in session.scalars(select(OAuthGrant).where(OAuthGrant.client_id == row.client_id, OAuthGrant.owner == row.owner)):
            session.delete(grant)
        session.commit()
    return {}
