"""v7: chat turns survive leaving the page, admin page and caps, sign-up notification,
simple sign-up, language before sign-in, nutrition day view."""

import threading
import time

from app import agent, store
from tests.conftest import login

WAIT = 'hx-get="/chat/turns/'  # the "Coach is replying…" bubble


def _wait_done(client, html: str, timeout: float = 10) -> str:
    """Follows the "Coach is replying…" bubble like the page does."""
    import re
    tid = re.search(r"/chat/turns/(\d+)", html).group(1)
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/chat/turns/{tid}")
        if WAIT not in r.text:
            return r.text
        time.sleep(0.2)
    raise AssertionError("turn did not finish")


def test_chat_turn_runs_in_background_and_other_pages_still_load(client, users, monkeypatch):
    u = users()
    store.set_setup_step(u.id, 6)
    login(client, u)
    release = threading.Event()

    def slow_run(user, text, images=None, **kw):
        release.wait(10)
        return {"reply": "Logged your oatmeal.", "actions": []}

    monkeypatch.setattr(agent, "run", slow_run)
    t0 = time.time()
    r = client.post("/chat", data={"text": "oatmeal"})
    assert r.status_code == 200 and WAIT in r.text
    assert time.time() - t0 < 5  # the request does not wait for the model
    # while the coach works: another page loads, and Today shows the turn as still running
    assert client.get("/nutrition").status_code == 200
    assert WAIT in client.get("/").text
    # a second message waits for the first
    assert "still answering" in client.post("/chat", data={"text": "again"}).text
    release.set()
    assert "Logged your oatmeal." in _wait_done(client, r.text)
    page = client.get("/").text
    assert "Logged your oatmeal." in page and WAIT not in page


def test_chat_turn_failure_is_shown_not_lost(client, users, monkeypatch):
    from app import llm
    u = users()
    store.set_setup_step(u.id, 6)
    login(client, u)

    def boom(*a, **k):
        raise llm.LLMError("model down")

    monkeypatch.setattr(agent, "run", boom)
    r = client.post("/chat", data={"text": "hello"})
    assert "try again" in _wait_done(client, r.text)


def test_turns_are_private(client, users, monkeypatch):
    a, b = users(), users()
    store.set_setup_step(a.id, 6)
    monkeypatch.setattr(agent, "run", lambda *x, **k: {"reply": "secret reply", "actions": []})
    login(client, a)
    r = client.post("/chat", data={"text": "hi"})
    import re
    tid = re.search(r"/chat/turns/(\d+)", r.text).group(1)
    _wait_done(client, r.text)
    login(client, b)
    assert client.get(f"/chat/turns/{tid}").status_code == 404


def test_admin_page_only_for_admins(client, users, monkeypatch):
    from app.config import get_settings
    admin, other = users(), users()
    monkeypatch.setattr(get_settings(), "admin_emails", admin.email)
    login(client, other)
    assert client.get("/admin").status_code == 404
    assert client.post(f"/admin/users/{other.id}", data={"cap": "100"}).status_code == 404
    assert store.get_user(other.id).monthly_cap_usd is None
    login(client, admin)
    page = client.get("/admin")
    assert page.status_code == 200 and other.email in page.text
    r = client.post(f"/admin/users/{other.id}", data={"cap": "7.5", "access": "blocked"},
                    follow_redirects=False)
    assert r.status_code == 303
    u = store.get_user(other.id)
    assert (u.monthly_cap_usd, u.ai_access) == (7.5, "blocked")
    assert client.post("/admin/users/not-a-uuid", data={}).status_code == 404


def test_new_sign_up_notifies_admins_once(client, monkeypatch):
    import uuid

    from app import auth, push
    from app.db import connection
    sent = []
    monkeypatch.setattr(push, "notify_admins", lambda title, body, url="/admin": sent.append(body))
    email = f"new-{uuid.uuid4().hex[:8]}@test.invalid"
    claims = {"sub": f"n-{email}", "email": email, "email_verified": True, "name": "New Person"}
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", lambda *a, **k: claims)
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "open_signup", True)
    try:
        assert client.post("/auth/session", json={"id_token": "t"}).status_code == 200
        assert client.post("/auth/session", json={"id_token": "t"}).status_code == 200
        time.sleep(0.5)  # the notification runs in a thread
        assert sent == [f"New Person {email}"]
    finally:
        with connection() as c:
            c.execute("delete from users where email = %s", (email,))


def test_one_screen_sign_up_then_setup_cards_and_no_watch_needed(client, users, monkeypatch):
    from app import weather
    u = users()
    login(client, u)
    assert client.get("/", follow_redirects=False).headers["location"] == "/welcome"
    assert "What do you want to track?" in client.get("/welcome").text
    monkeypatch.setattr(weather, "geocode", lambda name: None)  # no network in tests
    r = client.post("/welcome", data={"name": "Ivan", "sport": "Run", "goal": "Run 10 km",
                                      "tracks": ["training", "weather"]}, follow_redirects=False)
    assert r.headers["location"] == "/"
    me = store.get_user(u.id)
    assert (me.setup_step, me.tracks, me.display_name) == (6, ["training", "weather"], "Ivan")
    assert any(f["text"] == "Run 10 km" for f in store.list_facts(u.id))
    rail = client.get("/rail").text
    assert "Connect your watch" in rail and "Your height and weight" in rail
    assert "Turn on reminders" not in rail  # not chosen
    assert "intervals.icu" in client.get("/setup/watch/sheet").text
    client.post("/setup/body", data={"weight_kg": "80", "height_cm": "180", "birth_year": "1965"})
    assert "Your height and weight" not in client.get("/rail").text
    assert "find that city" in client.post("/setup/city", data={"city": "Nowhere"}).text
    # every page works without intervals.icu
    for path in ["/", "/rail", "/training", "/health", "/nutrition", "/day", "/day/2026-11-01",
                 "/memory", "/settings", "/more"]:
        assert client.get(path).status_code == 200, path


def test_language_toggle_before_sign_in(client):
    assert "Continue with Google" in client.get("/login").text
    r = client.post("/lang", data={"lang": "uk", "next": "/login"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    page = client.get("/login").text
    assert "Продовжити з Google" in page and 'lang="uk"' in page
    assert client.post("/lang", data={"lang": "uk", "next": "//evil.example"},
                       follow_redirects=False).headers["location"] == "/"


def test_browser_language_picks_ukrainian(client):
    assert 'lang="uk"' in client.get("/login", headers={"Accept-Language": "uk-UA,uk;q=0.9"}).text


def test_every_ui_text_has_a_ukrainian_translation():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import i18n_check
    assert i18n_check.missing() == []


def test_nutrition_day_view_navigation_and_cached_review(client, users, monkeypatch):
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.pipeline import day_review
    u = users()
    store.set_setup_step(u.id, 6)
    login(client, u)
    today = datetime.now(ZoneInfo(u.time_zone)).date()
    y = today - timedelta(days=1)
    at = datetime.combine(y, datetime.min.time(), ZoneInfo(u.time_zone)).replace(hour=8)
    store.add_log(u.id, "meal", y, {"description": "Oatmeal", "nutrition": {"totals": {
        "kcal": 480, "protein_g": 14, "carbs_g": 86, "fat_g": 9}}}, at)
    page = client.get(f"/nutrition?day={y}").text
    assert "Yesterday" in page and "Breakfast" in page and "Oatmeal" in page
    assert f"/nutrition?day={y - timedelta(days=1)}" in page  # ‹ previous day
    assert "Nothing logged this day" in client.get("/nutrition").text  # today: empty
    assert client.get(f"/nutrition?day={today + timedelta(days=5)}").status_code == 200  # clamped
    assert client.get("/nutrition?day=not-a-date").status_code == 200
    calls = []

    def fake(payload, user_id=None):
        calls.append(payload)
        return day_review.DayReview(good="g", short="s", tip="t")

    monkeypatch.setattr(day_review, "review", fake)
    assert "badge good" in client.get(f"/nutrition/review?day={y}").text
    client.get(f"/nutrition/review?day={y}")
    assert len(calls) == 1  # cached while the day's numbers stay the same
    store.add_log(u.id, "meal", y, {"description": "Apple", "nutrition": {"totals": {
        "kcal": 80}}}, at.replace(hour=16))
    client.get(f"/nutrition/review?day={y}")
    assert len(calls) == 2  # a new meal → a new review
    assert date.fromisoformat(calls[0]["day"]) == y
    assert "?days=7" in client.get("/nutrition?days=7").text


def test_day_review_analysis_is_code():
    from app.pipeline.day_review import analyse
    day = {"day_is_over": True, "day_type": "push", "meals_logged": 3,
           "targets": {"kcal": 3000, "protein_g": 135, "carbs_g": 490, "fat_g": 75,
                       "fiber_g": 30, "sugar_g": 50, "salt_g": 5},
           "eaten": {"kcal": 2900, "protein_g": 140, "carbs_g": 210, "fat_g": 70,
                     "fiber_g": 28, "sugar_g": 30, "salt_g": 4},
           "meals": [{"time": "12:30", "what": "rice", "kcal": 900}],
           "drinks": {"water_l": 2, "caffeine_mg": 95, "alcohol_g": 40},
           "training": [{"type": "Run", "minutes": 95}]}
    a = analyse(day)
    assert a["status"]["protein_g"]["status"] == "on target"
    assert a["status"]["carbs_g"]["difference"] == -280
    worst = a["issues_worst_first"]
    assert worst[0].startswith("alcohol 40 g") and any("carbs_g 210" in x for x in worst)
    assert any("no real breakfast" in x for x in worst)
    assert analyse(day | {"day_is_over": False})["issues_worst_first"][0].startswith("alcohol")
    assert not any("carbs_g" in x for x in analyse(day | {"day_is_over": False})
                   ["issues_worst_first"])  # an open day is not "under" yet


def test_cpu_hold_needs_the_secret_and_ends_with_the_turn(client, users, monkeypatch):
    from app.routes.push import cron_secret
    u = users()
    store.set_setup_step(u.id, 6)
    login(client, u)
    monkeypatch.setattr(agent, "run", lambda *a, **k: {"reply": "ok", "actions": []})
    r = client.post("/chat", data={"text": "hi"})
    _wait_done(client, r.text)
    import re
    tid = re.search(r"/chat/turns/(\d+)", r.text).group(1)
    client.cookies.clear()
    assert client.post(f"/cron/hold/{tid}").status_code == 403
    done = client.post(f"/cron/hold/{tid}", headers={"x-cron-secret": cron_secret()})
    assert done.json() == {"status": "done"}


def test_journal_is_gone_and_old_links_open_today(client, users):
    u = users()
    store.set_setup_step(u.id, 6)
    login(client, u)
    for old in ("/journal", "/history", "/day"):
        r = client.get(old, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/day/20"), old
    page = client.get("/").text
    assert 'href="/journal"' not in page and 'href="/day"' in page


def test_calendar_fetch_refuses_internal_addresses():
    import pytest

    from app import calendar
    for url in ["https://127.0.0.1/x.ics", "https://localhost/x.ics",
                "https://metadata.google.internal/computeMetadata/v1/", "https://10.0.0.5/a.ics"]:
        with pytest.raises(calendar.CalendarError):
            calendar.fetch(url)
