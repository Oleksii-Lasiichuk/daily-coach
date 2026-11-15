"""Open sign-up: any verified Google account can sign in as a guest, but guests never spend the
app's OpenRouter key and can't finish setup without their own. Members are unchanged."""

import uuid

import pytest

from app import auth, crypto, llm, store
from app.config import get_settings
from app.db import connection
from tests.conftest import login


@pytest.fixture
def open_signup(monkeypatch):
    monkeypatch.setattr(get_settings(), "open_signup", True)


def test_stranger_can_sign_in_when_open(open_signup, monkeypatch, client):
    email = f"guest-{uuid.uuid4().hex[:8]}@test.invalid"
    claims = {"sub": f"g-{email}", "email": email, "email_verified": True}
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", lambda *a, **k: claims)
    try:
        assert client.post("/auth/session", json={"id_token": "t"}).status_code == 200
    finally:
        with connection() as c:
            c.execute("delete from users where email = %s", (email,))


def test_unverified_email_still_refused_when_open(open_signup, monkeypatch, client):
    claims = {"sub": "z", "email": "someone@gmail.com", "email_verified": False}
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", lambda *a, **k: claims)
    assert client.post("/auth/session", json={"id_token": "t"}).status_code == 403


def test_guest_without_key_never_reaches_the_model(open_signup, users, monkeypatch):
    guest = users()
    called = []
    monkeypatch.setattr(llm._client.chat.completions, "create", lambda **k: called.append(k))
    with pytest.raises(llm.BudgetExceeded):
        llm.complete(name="x", messages=[{"role": "user", "content": "hi"}], user_id=guest.id)
    assert not called
    store.save_secret(guest.id, "openrouter", crypto.encrypt("sk-or-test"), "test", None)
    llm.check_budget(guest.id)  # with their own key: allowed


def test_member_uses_app_key_when_open(open_signup, users, monkeypatch):
    member = users()
    monkeypatch.setattr(get_settings(), "allowed_emails", member.email)
    llm.check_budget(member.id)  # no exception


def test_guest_setup_needs_key_and_sample_data_works(open_signup, client, users):
    guest = users()
    login(client, guest)
    r = client.post("/intervals/sample")
    assert r.status_code == 200 and "Sample watch data" in r.text
    assert store.get_secret(guest.id, "intervals")["external_id"] == "demo"
    client.post("/welcome/1", follow_redirects=False)
    assert store.get_user(guest.id).setup_step == 1  # blocked: no own key yet
    store.save_secret(guest.id, "openrouter", crypto.encrypt("sk-or-test"), "test", None)
    client.post("/welcome/1", follow_redirects=False)
    assert store.get_user(guest.id).setup_step == 2
