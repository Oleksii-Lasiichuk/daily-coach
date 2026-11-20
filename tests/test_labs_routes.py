"""B3 routes: two-user isolation for every /labs route, edit, undo, delete all, upload errors."""

from datetime import date

from app.pipeline import labs
from app.pipeline.labs import LabSheet, PrintedRow
from tests.conftest import login
from tests.test_labs import _blank_pdf


def _seed(user, value="18"):
    sheet = LabSheet(lab="SECRET-A lab", taken_on=None, rows=[
        PrintedRow(name_as_printed="Ferritin", value_as_printed=value, unit_as_printed="ng/mL",
                   ref_as_printed="30 - 400"),
        PrintedRow(name_as_printed="SECRET-A marker", value_as_printed="7",
                   unit_as_printed="U", ref_as_printed="")])
    out = labs.save(user.id, sheet, labs.normalise(sheet), date(2026, 9, 12), "a.pdf", None)
    return out["upload_id"], labs.all_rows(user.id)[0]["id"]


def test_user_b_cannot_touch_user_a_labs(client, users):
    from app import store
    a, b = users(), users()
    upload, row = _seed(a)
    store.set_setup_step(b.id, 6)
    login(client, b)
    for path in ["/health", "/settings"]:
        r = client.get(path)
        assert r.status_code == 200 and "SECRET-A" not in r.text and "Ferritin" not in r.text
    assert client.get("/labs/ferritin").status_code == 404
    assert client.get("/labs/SECRET-A marker").status_code == 404
    r = client.post(f"/labs/{row}", data={"value": "999", "ref": "", "unit": ""},
                    follow_redirects=False)
    assert r.status_code == 404
    assert client.delete(f"/labs/upload/{upload}").status_code == 404
    assert client.delete("/labs").status_code == 200  # deletes only B's (none)
    rows = labs.all_rows(a.id)
    assert len(rows) == 2 and float(rows[0]["value"]) == 18 and not rows[0]["edited"]


def test_owner_edit_trend_undo_and_delete_all(client, users):
    from app import store
    a = users()
    store.set_setup_step(a.id, 6)
    login(client, a)
    upload, row = _seed(a)
    assert labs.save(a.id, LabSheet(lab=None, taken_on=None, rows=[
        PrintedRow(name_as_printed="Ferritin", value_as_printed="18", unit_as_printed="ng/mL",
                   ref_as_printed="30 - 400"),
        PrintedRow(name_as_printed="SECRET-A marker", value_as_printed="7",
                   unit_as_printed="U", ref_as_printed="")]),
        labs.normalise(LabSheet(lab=None, taken_on=None, rows=[
            PrintedRow(name_as_printed="Ferritin", value_as_printed="18",
                       unit_as_printed="ng/mL", ref_as_printed="30 - 400"),
            PrintedRow(name_as_printed="SECRET-A marker", value_as_printed="7",
                       unit_as_printed="U", ref_as_printed="")])),
        date(2026, 9, 12), "again.pdf", None) == {"duplicate": True}
    r = client.get("/health")
    assert "Ferritin" in r.text and "badge warn" in r.text
    r = client.get("/labs/ferritin")
    assert r.status_code == 200 and "18" in r.text
    r = client.post(f"/labs/{row}", data={"value": "45", "ref": "", "unit": ""},
                    follow_redirects=False)
    assert r.status_code == 303
    got = labs.get_row(a.id, row)
    assert float(got["value"]) == 45 and got["flag"] == "in" and got["edited"]
    assert client.delete(f"/labs/upload/{upload}").status_code == 200
    assert labs.all_rows(a.id) == []
    _seed(a)
    client.delete("/labs")
    assert labs.all_rows(a.id) == []


def test_upload_scan_pdf_asks_for_photo(client, users):
    from app import store
    a = users()
    store.set_setup_step(a.id, 6)
    login(client, a)
    r = client.post("/labs", files={"file": ("scan.pdf", _blank_pdf(), "application/pdf")},
                    follow_redirects=False)
    assert r.status_code == 303 and "labs=scan" in r.headers["location"]
    assert "photo of the page" in client.get(r.headers["location"]).text


def test_chat_undo_removes_upload(users):
    from app import agent
    from app.db import connection
    a = users()
    upload, _ = _seed(a)
    agent.save_actions(a.id, None, [{"tool": "read_lab_sheet", "summary": "x",
                                     "undo": {"op": "delete_labs", "upload_id": upload}}])
    with connection() as c:
        aid = c.execute("select id from agent_actions where user_id = %s",
                        (a.id,)).fetchone()["id"]
    assert agent.undo(a.id, aid) and labs.all_rows(a.id) == []


def test_context_lines_short_list(users):
    a = users()
    _seed(a)
    lines = labs.context_lines(a.id, date(2026, 11, 20))
    assert lines == ["Ferritin 18 µg/L (2026-09-12, range 30–400): low"]
    assert labs.low_flags(a.id, date(2026, 11, 20)) == ["ferritin"]
