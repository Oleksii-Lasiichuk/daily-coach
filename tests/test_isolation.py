"""User B must never see or change user A's data through any endpoint (S2)."""

import json
from datetime import date

from app import sources, store
from tests.conftest import login


def _seed(user):
    fact = store.add_fact(user.id, "injury", "SECRET-A knee pain", "user")
    log = store.add_log(user.id, "meal", date.today(), {"description": "SECRET-A borscht"})
    prop = store.add_proposal(user.id, date.today(), {"action": "add", "sport": "Run",
                              "name": "SECRET-A run", "blocks": [], "minutes": 30,
                              "text": "- 30m Z2 HR"}, "SECRET-A why", [])
    store.set_profile_field(user.id, "main_goal", "SECRET-A goal", "user")
    store.add_message(user.id, "user", "SECRET-A message")
    src = sources.add_source(user.id, "secret-a.md", b"SECRET-A file text about the left knee.")
    from app.db import connection
    with connection() as c:
        proposed = c.execute("insert into facts (user_id, category, text, source, status, "
                             "source_id, quote) values (%s, 'injury', 'SECRET-A proposed', "
                             "'file', 'proposed', %s, 'q') returning id",
                             (user.id, src)).fetchone()["id"]
    return fact, log, prop, src, proposed


def test_user_b_cannot_read_or_change_user_a(client, users):
    a, b = users(), users()
    fact, log, prop, src, proposed = _seed(a)
    login(client, b)
    store.set_setup_step(b.id, 6)
    from app.db import connection
    with connection() as c:
        act = c.execute("insert into agent_actions (user_id, tool, summary, undo) values "
                        "(%s, 'save_item', 'SECRET-A', %s::jsonb) returning id",
                        (a.id, json.dumps({"op": "delete_fact", "id": fact}))).fetchone()["id"]
        c.execute("insert into reminders (user_id, text, times) values (%s, 'SECRET-A pill', "
                  "'{08:00}')", (a.id,))

        habit = c.execute("insert into habits (user_id, name) values (%s, 'SECRET-A habit') "
                          "returning id", (a.id,)).fetchone()["id"]

    for path in ["/", "/memory", "/settings", "/nutrition?days=30", "/health", "/training",
                 "/journal", f"/day/{date.today().isoformat()}"]:
        r = client.get(path)
        assert r.status_code == 200 and "SECRET-A" not in r.text, path
    for path in [f"/items/{fact}/sheet", f"/logs/{log}/sheet"]:
        r = client.get(path)
        assert r.status_code == 404 and "SECRET-A" not in r.text, path

    for path in [f"/items/{fact}/delete", f"/items/{fact}/end", f"/items/{fact}",
                 f"/actions/{act}/undo", "/reminders/1/delete", f"/logs/{log}/edit",
                 f"/quick/undo/{log}", f"/habits/{habit}/toggle", f"/habits/{habit}/remove",
                 f"/logs/{log}/delete", f"/proposals/{prop}/apply",
                 f"/proposals/{prop}/undo", f"/proposals/{prop}/dismiss",
                 f"/files/{src}/step", f"/files/{src}/delete"]:
        r = client.post(path, data={"text": "B was here", "factor": "2"}, follow_redirects=False)
        assert r.status_code in (200, 303, 404), path
        assert "SECRET-A" not in r.text, path

    r = client.post("/facts/review", data={"keep": str(proposed)}, follow_redirects=False)
    assert r.status_code == 303

    assert [f["text"] for f in store.list_facts(a.id)] == ["SECRET-A knee pain"]
    assert store.logs_between(a.id, date.today(), date.today())[0]["data"] == {
        "description": "SECRET-A borscht"}
    assert store.habits_for_day(a.id, date.today())[0]["done"] is False
    assert [f["id"] for f in sources.proposed_facts(a.id)] == [proposed]  # untouched by B
    assert [s["id"] for s in sources.list_sources(a.id)] == [src]
    assert sources.list_sources(b.id) == [] and sources.search(b.id, "knee") == []
    assert store.list_facts(a.id)[0]["status"] == "active"
    assert len(store.logs_between(a.id, date.today(), date.today())) == 1
    assert store.get_proposal(a.id, prop)["status"] == "proposed"
    assert store.get_proposal(b.id, prop) is None


def test_calendar_routes_are_per_user(client, users):
    """B2: user B's connect / titles / remove never touch user A's link or busy blocks."""
    from datetime import UTC, datetime, timedelta

    from app import calendar, demo
    from app.db import connection
    a, b = users(), users()
    calendar.save_url(a.id, f"https://{demo.DEMO_CALENDAR_HOST}/google.ics")
    now = datetime.now(UTC)
    with connection() as c:
        c.execute("insert into calendar_blocks (user_id, starts_at, ends_at, title) values "
                  "(%s, %s, %s, 'SECRET-A meeting')", (a.id, now, now + timedelta(hours=1)))
    calendar.set_titles(a.id, True)
    login(client, b)
    store.set_setup_step(b.id, 6)
    for path in ["/", "/rail", "/settings", "/training", "/setup/calendar/sheet"]:
        r = client.get(path)
        assert r.status_code == 200 and "SECRET-A" not in r.text, path
    assert client.post("/calendar/titles", data={"on": ""}).status_code == 200
    assert client.delete("/calendar").status_code == 200
    r = client.post("/calendar", data={"url": "http://not-https.test/x.ics"})
    assert "SECRET-A" not in r.text and "a calendar" in r.text
    assert store.get_secret(a.id, "ical") is not None
    assert calendar.feed(a.id)["show_titles"] is True
    assert [x["title"] for x in calendar.blocks_between(a.id, now - timedelta(days=1),
                                                       now + timedelta(days=1))] == [
        "SECRET-A meeting"]
    assert store.get_secret(b.id, "ical") is None and calendar.feed(b.id) is None


def test_calendar_connect_sync_titles_remove(client, users, caplog):
    """B2 end to end on the synthetic calendar: titles only with the toggle; URL never logged."""
    from app import calendar, demo
    u = users()
    login(client, u)
    store.set_setup_step(u.id, 6)
    url = f"https://{demo.DEMO_CALENDAR_HOST}/icloud.ics"
    with caplog.at_level("DEBUG"):
        r = client.post("/calendar", data={"url": url})
        assert r.status_code == 200 and "Found" in r.text
        calendar.sync(u.id)
    assert url not in caplog.text
    sec = store.get_secret(u.id, "ical")
    assert sec["ciphertext"] != url and url not in str(sec)
    f = calendar.feed(u.id)
    assert f["event_count"] > 0 and f["last_error"] is None
    from datetime import UTC, datetime, timedelta
    now = datetime.now(UTC)
    rows = calendar.blocks_between(u.id, now - timedelta(days=2), now + timedelta(days=15))
    assert rows and all(x["title"] is None for x in rows)  # titles off by default
    client.post("/calendar/titles", data={"on": "1"})
    calendar.sync(u.id)
    rows = calendar.blocks_between(u.id, now - timedelta(days=2), now + timedelta(days=15))
    assert any(x["title"] for x in rows)
    client.post("/calendar/titles", data={"on": ""})
    assert all(x["title"] is None for x in calendar.blocks_between(
        u.id, now - timedelta(days=2), now + timedelta(days=15)))
    assert "dayline" in client.get("/rail").text
    client.delete("/calendar")
    assert store.get_secret(u.id, "ical") is None and calendar.feed(u.id) is None
    assert calendar.blocks_between(u.id, now - timedelta(days=2), now + timedelta(days=15)) == []
