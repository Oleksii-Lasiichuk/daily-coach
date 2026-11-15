"""Test helpers. Tests run against the Neon dev branch (`main`) from .env; every test user
has a unique email under @test.invalid and is deleted afterwards."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app import store
from app.config import get_settings
from app.db import connection
from app.main import app

ORIGIN = get_settings().origins[0]


@pytest.fixture
def client():
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as c:
        yield c


def make_user() -> store.User:
    uid = uuid.uuid4().hex[:10]
    return store.upsert_user(f"test-{uid}", f"{uid}@test.invalid", f"Test {uid}")


def login(client: TestClient, user: store.User) -> None:
    """Sets a valid session cookie for `user` without going through Google."""
    import base64
    import json

    from itsdangerous import TimestampSigner  # same signer Starlette uses

    from app.crypto import derived_key

    data = base64.b64encode(json.dumps({"user_id": user.id}).encode())
    signed = TimestampSigner(derived_key("session-cookie")).sign(data).decode()
    client.cookies.set("__session", signed)


@pytest.fixture
def users():
    made = []

    def _make():
        u = make_user()
        made.append(u)
        return u

    yield _make
    with connection() as c:
        for u in made:
            c.execute("delete from users where id = %s", (u.id,))
