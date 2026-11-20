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


def test_b1_location_routes_touch_only_own_rows(client, users, monkeypatch):
    """B1: /location, /settings/location-auto, /settings/training-time write only B's rows."""
    from app import weather
    from app.routes.profile import prefs
    monkeypatch.setattr(weather, "reverse_name", lambda *a, **k: "Testville")
    a, b = users(), users()
    a_loc = {"name": "SECRET-A town", "lat": 50.45, "lon": 30.52, "source": "gps", "at": "x"}
    store.set_profile_field(a.id, "location", a_loc, "user")
    prefs(a.id)
    login(client, b)
    store.set_setup_step(b.id, 6)
    r = client.post("/location", data={"lat": "49.8412345", "lon": "24.0312345"})
    assert r.status_code == 200 and r.json() == {"name": "Testville"}
    assert client.post("/location", data={"lat": "91", "lon": "0"}).status_code == 400
    assert client.post("/location", data={"lat": "x", "lon": "0"}).status_code == 400
    client.post("/settings/location-auto", data={}, follow_redirects=False)
    client.post("/settings/training-time", data={"usual_training_time": "18:30",
                                                 "wake_time": "25:00", "bedtime": "23:00"},
                follow_redirects=False)
    b_loc = store.get_profile(b.id)["location"]["value"]
    assert (b_loc["lat"], b_loc["lon"], b_loc["source"]) == (49.84, 24.03, "gps")
    assert store.get_profile(a.id)["location"]["value"] == a_loc
    tb, ta = store.day_times(b.id), store.day_times(a.id)
    assert (tb["usual_training_time"], tb["wake_time"], tb["bedtime"],
            tb["location_auto"]) == ("18:30", "07:00", "23:00", False)
    assert ta == store.TIME_DEFAULTS | {"location_auto": True}
    # silent update is skipped when B turned it off
    assert client.post("/location", data={"lat": "1", "lon": "1", "auto": "1"}).json() == {
        "skipped": True}
    r = client.get("/settings")
    assert r.status_code == 200 and "SECRET-A" not in r.text and "Testville" in r.text
