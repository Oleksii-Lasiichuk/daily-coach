from fastapi.routing import APIRoute

from app import auth
from app.auth import PUBLIC_PATHS, current_user
from app.main import app
from tests.conftest import login


def _depends_on_current_user(dependant) -> bool:
    return any(d.call is current_user or _depends_on_current_user(d)
               for d in dependant.dependencies)


def test_every_route_requires_a_session_except_public():
    unprotected = [r.path for r in app.routes if isinstance(r, APIRoute)
                   and r.path not in PUBLIC_PATHS and not _depends_on_current_user(r.dependant)]
    assert unprotected == []


def test_no_session_redirects_html_and_401s_htmx(client):
    r = client.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    r = client.get("/", headers={"HX-Request": "true"})
    assert r.status_code == 401 and r.headers["HX-Redirect"] == "/login"


def test_session_gives_access(client, users):
    user = users()
    login(client, user)
    r = client.get("/profile")
    assert r.status_code == 200 and user.email in r.text
    r = client.get("/", follow_redirects=False)  # a new user goes to the first-run window
    assert r.status_code == 303 and r.headers["location"] == "/welcome"


def test_session_for_deleted_user_is_rejected(client):
    from app.db import connection
    from tests.conftest import make_user
    user = make_user()
    with connection() as c:
        c.execute("delete from users where id = %s", (user.id,))
    login(client, user)
    assert client.get("/", headers={"HX-Request": "true"}).status_code == 401


def test_bad_origin_is_rejected(client, users):
    login(client, users())
    r = client.post("/auth/logout", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_allowlist(monkeypatch, client):
    claims = {"sub": "x", "email": "stranger@gmail.com", "email_verified": True}
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", lambda *a, **k: claims)
    r = client.post("/auth/session", json={"id_token": "t"})
    assert r.status_code == 403
    from app.db import connection
    with connection() as c:
        row = c.execute("select 1 from users where email = %s", (claims["email"],)).fetchone()
        assert row is None


def test_unverified_email_is_refused(monkeypatch, client):
    allowed = sorted(auth.get_settings().allowed_email_set)[0]
    claims = {"sub": "y", "email": allowed, "email_verified": False}
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", lambda *a, **k: claims)
    assert client.post("/auth/session", json={"id_token": "t"}).status_code == 403


def test_invalid_token_is_401(client):
    assert client.post("/auth/session", json={"id_token": "not-a-jwt"}).status_code == 401


def test_cron_tick_needs_secret_not_origin():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:  # no Origin header, like Cloud Scheduler
        assert c.post("/cron/tick").status_code == 403
        assert c.post("/cron/tick", headers={"X-Cron-Secret": "wrong"}).status_code == 403
