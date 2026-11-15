"""Sign-in and access control.

Flow: Firebase JS (Google popup) gives the browser an ID token → POST /auth/session →
we verify it against Google's public keys (no Google credentials needed), require a verified
email on ALLOWED_EMAILS, and store only user_id in the signed `__session` cookie.
Every route depends on `current_user` except PUBLIC_PATHS (tested in test_routes_protected).
"""

from fastapi import Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from starlette.responses import JSONResponse, Response

from app import store
from app.config import get_settings

# /healthz is reserved on Cloud Run; /cron/tick checks its own secret header; /sw.js is static JS;
# /demo-login answers 404 unless ENV=dev and the request comes from localhost.
PUBLIC_PATHS = {"/login", "/auth/session", "/status", "/sw.js", "/cron/tick", "/demo-login"}
SESSION_MAX_AGE = 14 * 24 * 3600

_google_request = google_requests.Request()


class NotAuthenticated(Exception):
    pass


class NotAllowed(Exception):
    pass


def verify_google_login(token: str) -> dict:
    """Returns the token claims, or raises NotAllowed. ValueError on a bad token."""
    claims = id_token.verify_firebase_token(token, _google_request,
                                            audience=get_settings().firebase_project_id)
    if not claims or not claims.get("email_verified"):
        raise NotAllowed("email not verified")
    s = get_settings()
    if not s.open_signup and claims["email"].lower() not in s.allowed_email_set:
        raise NotAllowed("email not on the allowlist")
    return claims


def current_user(request: Request) -> store.User:
    user_id = request.session.get("user_id")
    user = store.get_user(user_id) if user_id else None
    if user is None:
        request.session.clear()
        raise NotAuthenticated()
    return user


def not_authenticated_response(request: Request) -> Response:
    if request.headers.get("HX-Request"):
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
        return Response(status_code=303, headers={"Location": "/login"})
    return JSONResponse({"error": "not signed in"}, status_code=401)


def origin_ok(request: Request) -> bool:
    """CSRF guard: state-changing requests must come from our own pages."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    if request.url.path == "/cron/tick":  # server-to-server; checked by its secret header
        return True
    origin = (request.headers.get("origin") or request.headers.get("referer", "")).rstrip("/")
    return any(origin == o or origin.startswith(o + "/") for o in get_settings().origins)
