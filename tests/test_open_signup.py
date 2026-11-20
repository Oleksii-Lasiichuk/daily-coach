"""Open sign-up: any verified Google account can sign in. Newcomers use the app's OpenRouter key
with a small starter cap; a blocked person never reaches the model without their own key.
Members (ALLOWED_EMAILS) get the bigger cap."""

import uuid

import pytest

from app import auth, crypto, llm, store
from app.config import get_settings
from app.db import connection


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


def test_blocked_without_key_never_reaches_the_model(open_signup, users, monkeypatch):
    guest = users()
    store.set_ai_access(guest.id, access="blocked", cap=None, key_pool="main")
    called = []
    monkeypatch.setattr(llm._client.chat.completions, "create", lambda **k: called.append(k))
    with pytest.raises(llm.BudgetExceeded):
        llm.complete(name="x", messages=[{"role": "user", "content": "hi"}], user_id=guest.id)
    assert not called
    store.save_secret(guest.id, "openrouter", crypto.encrypt("sk-or-test"), "test", None)
    llm.check_budget(guest.id)  # with their own key: allowed


def test_newcomer_gets_starter_cap_member_gets_more(open_signup, users, monkeypatch):
    guest, member = users(), users()
    monkeypatch.setattr(get_settings(), "allowed_emails", member.email)
    assert llm.cap_for(guest.id) == llm.STARTER_CAP_USD
    assert llm.cap_for(member.id) == llm.MEMBER_CAP_USD
    llm.check_budget(guest.id)  # allowed at once, no own key needed
    monkeypatch.setattr(store, "month_cost", lambda user_id: llm.STARTER_CAP_USD)
    with pytest.raises(llm.BudgetExceeded):
        llm.check_budget(guest.id)
    store.set_ai_access(guest.id, access="allowed", cap=5, key_pool="family")
    llm.check_budget(guest.id)  # the admin raised the cap
