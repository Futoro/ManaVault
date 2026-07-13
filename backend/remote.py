from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
import urllib.parse
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from backend import main as core


AUTH_FILE = Path(os.environ.get("MANAVAULT_REMOTE_AUTH_FILE", core.DATA_DIR / "remote-auth.json"))
COOKIE_NAME = "manavault_remote_session"
SESSION_SECONDS = 12 * 60 * 60
FAILED_WINDOW_SECONDS = 10 * 60
MAX_FAILED_ATTEMPTS = 10
failed_attempts: dict[str, deque[float]] = defaultdict(deque)

app = FastAPI(
    title="ManaVault authenticated remote access",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def load_auth() -> dict[str, Any] | None:
    if not AUTH_FILE.exists():
        return None
    try:
        payload = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    required = {"username", "salt", "password_hash", "session_secret"}
    return payload if required.issubset(payload) else None


def password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)


def verify_password(password: str, config: dict[str, Any]) -> bool:
    try:
        expected = b64decode(str(config["password_hash"]))
        actual = password_hash(password, b64decode(str(config["salt"])))
    except (KeyError, TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def create_session(config: dict[str, Any]) -> str:
    expires = int(time.time()) + SESSION_SECONDS
    payload = f"{config['username']}|{expires}|{secrets.token_urlsafe(12)}"
    encoded = b64encode(payload.encode("utf-8"))
    signature = hmac.new(
        b64decode(str(config["session_secret"])),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded}.{b64encode(signature)}"


def valid_session(token: str | None, config: dict[str, Any]) -> bool:
    if not token or "." not in token:
        return False
    encoded, supplied_signature = token.split(".", 1)
    try:
        expected_signature = hmac.new(
            b64decode(str(config["session_secret"])),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected_signature, b64decode(supplied_signature)):
            return False
        username, expires, _nonce = b64decode(encoded).decode("utf-8").split("|", 2)
        return username == str(config["username"]) and int(expires) >= int(time.time())
    except (ValueError, UnicodeDecodeError):
        return False


def safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def login_page(message: str = "", next_path: str = "/", setup_missing: bool = False) -> HTMLResponse:
    notice = ""
    if setup_missing:
        notice = "<p class='error'>Login wurde auf dem Server noch nicht eingerichtet.</p>"
    elif message:
        notice = f"<p class='error'>{html.escape(message)}</p>"
    content = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ManaVault Login</title><style>
:root {{ color-scheme: light; font-family: Inter,system-ui,sans-serif; background:#eef1ed; color:#142126; }}
body {{ min-height:100vh; margin:0; display:grid; place-items:center; padding:1rem; box-sizing:border-box; }}
main {{ width:min(420px,100%); background:#fffdf8; border:1px solid #ccd4ce; border-radius:18px; padding:1.5rem; box-shadow:0 18px 50px #1c30252b; }}
h1 {{ margin:0 0 .35rem; }} p {{ color:#68727f; }} label {{ display:grid; gap:.35rem; margin-top:1rem; font-weight:700; }}
input {{ font:inherit; padding:.85rem; border:1px solid #aeb8b1; border-radius:10px; }}
button {{ width:100%; margin-top:1.25rem; padding:.9rem; border:0; border-radius:10px; background:#197465; color:white; font:inherit; font-weight:800; cursor:pointer; }}
.error {{ color:#a51d23; background:#fff0f0; border-radius:9px; padding:.7rem; }}
</style></head><body><main><h1>ManaVault</h1><p>Geschuetzter externer Zugang</p>{notice}
<form method="post" action="/remote-login">
<input type="hidden" name="next" value="{html.escape(safe_next(next_path), quote=True)}">
<label>Benutzername<input name="username" autocomplete="username" required autofocus></label>
<label>Passwort<input name="password" type="password" autocomplete="current-password" required></label>
<button type="submit">Anmelden</button></form></main></body></html>"""
    return HTMLResponse(content, headers={"Cache-Control": "no-store"})


def request_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def is_rate_limited(key: str) -> bool:
    now = time.monotonic()
    attempts = failed_attempts[key]
    while attempts and now - attempts[0] > FAILED_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= MAX_FAILED_ATTEMPTS


@app.middleware("http")
async def require_remote_login(request: Request, call_next):
    if request.url.path in {"/remote-login", "/remote-logout"}:
        response = await call_next(request)
    else:
        config = load_auth()
        if not config or not valid_session(request.cookies.get(COOKIE_NAME), config):
            if request.url.path.startswith("/api/"):
                response = JSONResponse({"detail": "Anmeldung erforderlich."}, status_code=401)
            else:
                target = urllib.parse.quote(safe_next(request.url.path), safe="/")
                response = RedirectResponse(f"/remote-login?next={target}", status_code=303)
        else:
            response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/remote-login")
def remote_login_page(request: Request) -> HTMLResponse:
    config = load_auth()
    if config and valid_session(request.cookies.get(COOKIE_NAME), config):
        return RedirectResponse("/", status_code=303)
    return login_page(next_path=request.query_params.get("next", "/"), setup_missing=config is None)


@app.post("/remote-login")
async def remote_login(request: Request):
    config = load_auth()
    if not config:
        return login_page(setup_missing=True)
    try:
        content_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        content_length = 0
    if content_length > 8192:
        return JSONResponse({"detail": "Anfrage zu gross."}, status_code=413)
    key = request_key(request)
    if is_rate_limited(key):
        response = login_page("Zu viele Fehlversuche. Bitte spaeter erneut versuchen.")
        response.status_code = 429
        return response
    body = (await request.body()).decode("utf-8", errors="replace")
    form = urllib.parse.parse_qs(body, keep_blank_values=True)
    username = form.get("username", [""])[0]
    password = form.get("password", [""])[0]
    next_path = safe_next(form.get("next", ["/"])[0])
    if username != str(config["username"]) or not verify_password(password, config):
        failed_attempts[key].append(time.monotonic())
        response = login_page("Benutzername oder Passwort ist falsch.", next_path=next_path)
        response.status_code = 401
        return response
    failed_attempts.pop(key, None)
    response = RedirectResponse(next_path, status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        create_session(config),
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


@app.get("/remote-logout")
def remote_logout() -> RedirectResponse:
    response = RedirectResponse("/remote-login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")
    return response


@app.on_event("startup")
def startup() -> None:
    core.init_db()


app.mount("/", core.app)
