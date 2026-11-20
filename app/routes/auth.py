import logging
import threading

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from app import i18n, push, store
from app.auth import NotAllowed, current_user, verify_google_login
from app.config import get_settings
from app.web import templates, ui

router = APIRouter()
log = logging.getLogger("auth")


class SessionIn(BaseModel):
    id_token: str


# Firebase serves its sign-in handler (/__/auth/handler) on every Hosting domain. Signing in on
# the app's own domain avoids the cross-site storage that phone browsers block ("missing
# initial state"). localhost keeps the default firebaseapp.com handler.
HOSTED_DOMAINS = ("daily-coach-af64d.web.app", "daily-coach-af64d.firebaseapp.com",
                  "coach.lasiichuk.com")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    host = (request.headers.get("x-forwarded-host") or request.url.hostname or "").split(":")[0]
    auth_domain = host if host in HOSTED_DOMAINS else None
    return templates.TemplateResponse(request, "login.html", {
        **ui(None, request), "auth_domain": auth_domain,
        "open_signup": get_settings().open_signup})


@router.post("/lang")
def set_language(request: Request, lang: str = Form("en"), next: str = Form("/")):
    """The EN / UA toggle. Works before sign-in too: kept in the session cookie (Firebase
    Hosting forwards only `__session`), and saved to the account when signed in."""
    if lang in i18n.LANGS:
        request.session["lang"] = lang
        user_id = request.session.get("user_id")
        if user_id and store.get_user(user_id):
            store.set_lang(user_id, lang)
    ok = next.startswith("/") and not next.startswith("//")
    return RedirectResponse(next if ok else "/", status_code=303)


@router.post("/auth/session")
def create_session(body: SessionIn, request: Request):
    try:
        claims = verify_google_login(body.id_token)
    except NotAllowed:
        return JSONResponse({"error": "private"}, status_code=403)
    except ValueError:
        return JSONResponse({"error": "invalid token"}, status_code=401)
    user = store.upsert_user(claims["sub"], claims["email"], claims.get("name"))
    lang = request.session.get("lang")
    request.session.clear()
    request.session["user_id"] = user.id
    if lang in i18n.LANGS:
        request.session["lang"] = lang
    if user.is_new:
        if lang in i18n.LANGS:  # the language picked on the sign-in page
            store.set_lang(user.id, lang)
        threading.Thread(target=_tell_admins, args=(user,), daemon=True).start()
    return {"ok": True}


def _tell_admins(user: store.User) -> None:
    """A push to the admins on each new sign-up, so they can check who it is on /admin."""
    try:
        push.notify_admins("New sign-up", f"{user.display_name or ''} {user.email}".strip())
    except Exception:  # never break a sign-in over a notification
        log.exception("sign-up notification failed")


@router.post("/auth/logout")
def logout(request: Request, _user: store.User = Depends(current_user)):
    request.session.clear()
    return RedirectResponse("/login", status_code=303, headers={"HX-Redirect": "/login"})
