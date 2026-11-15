from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from app import demo, store
from app.auth import NotAllowed, current_user, verify_google_login
from app.web import templates

router = APIRouter()


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
        "auth_domain": auth_domain, "demo": demo.enabled() and _local(request)})


def _local(request: Request) -> bool:
    """True only for a browser on this machine (not behind a proxy or a hosted domain)."""
    host = (request.url.hostname or "").lower()
    return (host in ("localhost", "127.0.0.1") and not request.headers.get("x-forwarded-host")
            and (request.client.host if request.client else "") in ("127.0.0.1", "::1",
                                                                     "testclient"))


@router.get("/demo-login")
def demo_login(request: Request):
    """Local demo only: sign in as the synthetic Demo Athlete (seeded on first use)."""
    if not (demo.enabled() and _local(request)):
        raise HTTPException(status_code=404)
    uid = demo.user_id() or demo.seed()
    request.session.clear()
    request.session["user_id"] = uid
    return RedirectResponse("/", status_code=303)


@router.post("/auth/session")
def create_session(body: SessionIn, request: Request):
    try:
        claims = verify_google_login(body.id_token)
    except NotAllowed:
        return JSONResponse({"error": "private"}, status_code=403)
    except ValueError:
        return JSONResponse({"error": "invalid token"}, status_code=401)
    user = store.upsert_user(claims["sub"], claims["email"], claims.get("name"))
    request.session.clear()
    request.session["user_id"] = user.id
    return {"ok": True}


@router.post("/auth/logout")
def logout(request: Request, _user: store.User = Depends(current_user)):
    request.session.clear()
    return RedirectResponse("/login", status_code=303, headers={"HX-Redirect": "/login"})
