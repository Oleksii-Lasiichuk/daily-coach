"""Plan 11 B4: spend rules, the Monobank client against a fake API (shapes hand-written from
api.monobank.ua/docs, no real data), the webhook, insights, the coach tool, isolation."""

import json
import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import agent, money, money_stats, mono, spend_rules, store
from app.db import connection
from app.pipeline import receipt
from tests.conftest import login

TOKEN = "uFAKEtokenForTestsOnly0000000000000000000000x"
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


# --- rules -------------------------------------------------------------------------------

@pytest.mark.parametrize("cat,frag", [(c, f) for c, fs in spend_rules.MERCHANTS for f in fs])
def test_every_merchant_rule_places_its_name(cat, frag):
    assert spend_rules.categorise(f"{frag.strip()} lviv", 5999, -100) == cat


@pytest.mark.parametrize("mcc,cat", sorted(spend_rules.MCC.items()) + [(3100, "travel")])
def test_every_mcc_rule(mcc, cat):
    assert spend_rules.categorise("zzqx unknown", mcc, -100) == cat


@pytest.mark.parametrize("desc,mcc,amount,cat", [
    ("Від: Іван", 4829, 50000, "income"), ("Transfer", 4829, -100, "transfers"),
    ("Transfer", 6538, -100, "transfers"), ("Card", 6012, -100, "transfers"),
    ("Банкомат", 6011, -100, "cash"), ("СІЛЬПО Київ", 5411, -100, "groceries"),
    ("Bolt Food", 5814, -100, "delivery"), ("Bolt", 4121, -100, "taxi"),
    ("Metro Kyiv", 4111, -100, "transport"), ("ATB-Market", 5411, -100, "groceries"),
    ("Невідома кав'ярня", None, -100, "coffee"), ("Zzqx", 5999, -100, None)])
def test_rule_order_and_spellings(desc, mcc, amount, cat):
    assert spend_rules.categorise(desc, mcc, amount) == cat


def test_user_rule_wins_except_for_transfers():
    rules = {"glovo": "eating_out", "transfer": "groceries"}
    assert spend_rules.categorise("Glovo", 5814, -1, user_rules=rules) == "eating_out"
    assert spend_rules.categorise("Transfer", 4829, -1, user_rules=rules) == "transfers"


def test_receipt_lines_and_meal_offer():
    rc = receipt.Receipt(store="Кафе", total=250, kind="restaurant",
                         lines=[receipt.Line(name="Капучино", price=70),
                                receipt.Line(name="Сендвіч", price=150)])
    lines = receipt.categorised_lines(rc)
    assert [x["category"] for x in lines] == ["coffee", "eating_out", "eating_out"]
    assert round(sum(x["amount"] for x in lines)) == 250  # remainder line keeps the total
    assert receipt.offer_for(rc, lines) == "meal"
    shop = receipt.Receipt(store="Сільпо", total=900, kind="grocery", lines=[
        receipt.Line(name=n, price=100) for n in ["Молоко", "Хліб", "Яйця", "Гречка", "Банани",
                                                 "Сир", "Кефір", "Рис", "Йогурт"]])
    assert receipt.offer_for(shop, receipt.categorised_lines(shop)) is None
    gels = receipt.Receipt(store="Sport", total=300, kind="sport",
                           lines=[receipt.Line(name="Енергетичний гель SiS", price=300)])
    assert receipt.offer_for(gels, receipt.categorised_lines(gels)) == "fuel"


# --- fake Monobank -----------------------------------------------------------------------

class FakeMono:
    """Records every request; statement answers come from `items` filtered by the window."""

    def __init__(self, items=None, status=200):
        self.calls, self.items, self.status = [], items or [], status
        self.webhook = ""

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        assert req.headers["X-Token"] == TOKEN
        if self.status != 200:
            return httpx.Response(self.status, json={"errorDescription": "Too many requests"})
        p = req.url.path
        if p == "/personal/client-info":
            return httpx.Response(200, json={
                "clientId": "3MSaMMtczs", "name": "Тест Тестович", "webHookUrl": self.webhook,
                "permissions": "psfj", "jars": [],
                "accounts": [{"id": "acc-black", "sendId": "x", "balance": 1000000,
                              "creditLimit": 0, "type": "black", "currencyCode": 980,
                              "cashbackType": "UAH", "maskedPan": ["537541******1234"],
                              "iban": "UA733220010000026201234567890"}]})
        if p.startswith("/personal/statement/"):
            _, _, _, acc, frm, to = p.split("/")
            rows = [i for i in self.items if int(frm) <= i["time"] <= int(to)]
            return httpx.Response(200, json=sorted(rows, key=lambda i: -i["time"])[:500])
        if p == "/personal/webhook":
            self.webhook = json.loads(req.content)["webHookUrl"]
            return httpx.Response(200)
        return httpx.Response(404)


def item(i: int, t: datetime, amount=-12000, mcc=5411, desc="Сільпо", hold=False):
    return {"id": f"tx{i}", "time": int(t.timestamp()), "description": desc, "mcc": mcc,
            "originalMcc": mcc, "hold": hold, "amount": amount, "operationAmount": amount,
            "currencyCode": 980, "commissionRate": 0, "cashbackAmount": 0, "balance": 99999,
            "comment": "SECRET comment", "receiptId": "XXXX-1", "counterIban": "UA00SECRET",
            "counterName": "SECRET Person"}


@pytest.fixture
def fake(monkeypatch):
    def make(**kw):
        f = FakeMono(**kw)
        monkeypatch.setattr(mono, "http", httpx.Client(base_url=mono.BASE,
                                                       transport=httpx.MockTransport(f)))
        return f
    return make


def _windows(f):
    out = []
    for r in f.calls:
        if "/statement/" in r.url.path:
            _, _, _, _, frm, to = r.url.path.split("/")
            out.append((int(frm), int(to)))
    return out


def test_connect_saves_only_what_we_keep_and_token_encrypted(users, fake, caplog):
    u = users()
    f = fake()
    caplog.set_level(logging.DEBUG)
    assert mono.connect(u.id, TOKEN, 3, now=NOW) == 1
    sec = store.get_secret(u.id, "monobank")
    assert sec["ciphertext"] != TOKEN and sec["last4"] == TOKEN[-4:]
    with connection() as c:
        acc = c.execute("select * from money_accounts where user_id = %s", (u.id,)).fetchone()
    assert acc["last4"] == "1234" and "UA73" not in json.dumps(acc, default=str)
    assert len(f.calls) == 1  # client-info only (no webhook: dev has no public https URL)
    assert TOKEN not in caplog.text


def test_import_one_call_per_tick_31_day_windows_and_privacy(users, fake):
    u = users()
    items = [item(i, NOW - timedelta(days=i * 3, hours=1)) for i in range(60)]  # ~6 months
    f = fake(items=items)
    mono.connect(u.id, TOKEN, 6, now=NOW)
    f.calls.clear()
    t = NOW
    for _ in range(12):  # each tick: one call at most
        before = len(f.calls)
        mono.sync_step(u.id, now=t)
        assert len(f.calls) - before <= 1
        t += timedelta(minutes=15)
    w = _windows(f)
    assert all(to - frm <= 2_682_000 for frm, to in w)
    assert w[0][1] == int(NOW.timestamp())  # newest window first, then older ones
    assert all(w[i + 1][1] == w[i][0] for i in range(len(w) - 2) if w[i + 1][1] < w[i][1])
    with connection() as c:
        acc = c.execute("select * from money_accounts where user_id = %s", (u.id,)).fetchone()
        rows = c.execute("select * from transactions where user_id = %s", (u.id,)).fetchall()
    assert acc["imported_from"] <= acc["import_since"]
    assert acc["next_at"] > t  # steady state: catch-up in 6 h
    assert len(rows) == 60
    assert "SECRET" not in json.dumps(rows, default=str) and "99999" not in json.dumps(
        [r["amount_minor"] for r in rows])


def test_rate_limit_waits_for_the_next_tick(users, fake):
    u = users()
    fake()
    mono.connect(u.id, TOKEN, 1, now=NOW)
    f = fake(status=429)
    assert mono.sync_step(u.id, now=NOW) == 0
    assert mono.sync_step(u.id, now=NOW + timedelta(seconds=30)) == 0
    assert len(f.calls) == 1  # backed off: next_at moved past this tick


def test_500_rows_continue_from_the_oldest_item(users, fake):
    u = users()
    items = [item(i, NOW - timedelta(minutes=10 * i + 5)) for i in range(700)]  # ~4.9 days
    f = fake(items=items)
    mono.connect(u.id, TOKEN, 1, now=NOW)
    f.calls.clear()
    mono.sync_step(u.id, now=NOW)
    mono.sync_step(u.id, now=NOW + timedelta(minutes=15))
    w = _windows(f)
    oldest_first = min(i["time"] for i in sorted(items, key=lambda i: -i["time"])[:500])
    assert w[1][1] == oldest_first
    with connection() as c:
        n = c.execute("select count(*) as n from transactions where user_id = %s",
                      (u.id,)).fetchone()["n"]
    assert n == 700


def test_hold_settles_into_the_same_row(users):
    u = users()
    mono.save_item(u.id, "acc", item(1, NOW, amount=-5000, hold=True))
    mono.save_item(u.id, "acc", item(1, NOW, amount=-5200, hold=False))
    with connection() as c:
        rows = c.execute("select * from transactions where user_id = %s", (u.id,)).fetchall()
    assert len(rows) == 1 and rows[0]["amount_minor"] == -5200 and not rows[0]["hold"]


def test_transfer_description_is_replaced(users):
    u = users()
    mono.save_item(u.id, "acc", item(2, NOW, mcc=4829, desc="Переказ: Марія SECRET"))
    with connection() as c:
        r = c.execute("select description from transactions where user_id = %s",
                      (u.id,)).fetchone()
    assert r["description"] == "Transfer"


def test_tick_without_monobank_makes_no_call(users, fake):
    from app import push
    u = users()
    f = fake()
    assert push.money_tick(u.id, NOW) == 0 and f.calls == []


# --- webhook -----------------------------------------------------------------------------

def _hook(user, hook="hook-" + "a" * 40, account="acc-a"):
    with connection() as c:
        c.execute("insert into money_hooks (hook_hash, user_id) values (%s, %s)",
                  (mono.hook_hash(hook), user.id))
        c.execute("insert into money_accounts (user_id, account_id, kind, currency, "
                  "import_since) values (%s, %s, 'black', 980, now())", (user.id, account))
    return hook


def _post(client, hook, account, it):
    return client.post(f"/hooks/mono/{hook}", headers={"Origin": ""},
                       json={"type": "StatementItem",
                             "data": {"account": account, "statementItem": it}})


def test_webhook_saves_own_items_only(client, users):
    a, b = users(), users()
    hook_a = _hook(a, account="acc-a")
    _hook(b, hook="hook-" + "b" * 40, account="acc-b")
    assert client.get(f"/hooks/mono/{hook_a}").status_code == 200
    assert client.get("/hooks/mono/unknown").status_code == 404
    assert _post(client, "unknown", "acc-a", item(1, NOW)).status_code == 404
    r = _post(client, hook_a, "acc-b", item(2, NOW))  # B's account through A's hook
    assert r.status_code == 200 and r.json() == {"ok": False}
    r = _post(client, hook_a, "acc-a", item(3, NOW))
    assert r.status_code == 200 and r.json() == {"ok": True}
    with connection() as c:
        rows_a = c.execute("select ext_id from transactions where user_id = %s", (a.id,)).fetchall()
        rows_b = c.execute("select ext_id from transactions where user_id = %s", (b.id,)).fetchall()
    assert [r["ext_id"] for r in rows_a] == ["tx3"] and rows_b == []


# --- insights and the coach tool ---------------------------------------------------------

def _tx(user, at, uah, cat, desc="Glovo"):
    with connection() as c:
        c.execute("insert into transactions (user_id, source, ext_id, at, amount_minor, "
                  "description, category, category_by) values (%s, 'monobank', %s, %s, %s, %s, "
                  "%s, 'rule')", (user.id, f"t{at.timestamp()}{uah}{cat}", at,
                                  -round(uah * 100), desc, cat))


def test_insight_flags_ratio_threshold_and_empty_months(users):
    u = users()
    today = date(2026, 11, 20)
    assert money_stats.month_view(u, today.replace(day=1), today)["categories"] == []
    tz = ZoneInfo(u.time_zone)
    for m in (8, 9, 10):
        _tx(u, datetime(2026, m, 10, 12, tzinfo=tz), 600, "delivery")
        _tx(u, datetime(2026, m, 25, 12, tzinfo=tz), 5000, "delivery")  # after day 20: ignored
        _tx(u, datetime(2026, m, 11, 12, tzinfo=tz), 1000, "groceries", "Silpo")
    for d in (3, 8, 15):
        _tx(u, datetime(2026, 11, d, 12, tzinfo=tz), 500, "delivery")
    _tx(u, datetime(2026, 11, 4, 12, tzinfo=tz), 1300, "groceries", "Silpo")  # 1.3×: no flag
    v = money_stats.month_view(u, date(2026, 11, 1), today)
    by = {c["category"]: c for c in v["categories"]}
    assert by["delivery"]["avg_3m"] == 600 and by["delivery"]["ratio"] == 2.5
    assert by["delivery"]["flag"] == "up" and by["groceries"]["flag"] is None
    assert v["top"]["delivery"][0] == {"name": "Glovo", "n": 3, "uah": 1500}


def test_small_difference_is_not_flagged(users):
    u = users()
    tz = ZoneInfo(u.time_zone)
    _tx(u, datetime(2026, 10, 5, tzinfo=tz), 100, "coffee", "Aroma")
    _tx(u, datetime(2026, 11, 5, tzinfo=tz), 400, "coffee", "Aroma")  # 4× but only +300 ₴
    v = money_stats.month_view(u, date(2026, 11, 1), date(2026, 11, 20))
    assert v["categories"][0]["flag"] is None


def test_race_cost_counts_since_the_race_was_added(users):
    u = users()
    store.add_fact(u.id, "race", "Gorgany Trail 2027", "user")
    _tx(u, datetime.now(UTC) - timedelta(days=400), 3000, "race_entries", "Old race")
    _tx(u, datetime.now(UTC), 900, "race_entries", "Gorgany")
    _tx(u, datetime.now(UTC), 2500, "sport_gear", "Decathlon")
    _tx(u, datetime.now(UTC), 700, "groceries", "Silpo")
    assert money_stats.race_cost(u)["uah"] == 3400


def test_race_payment_matched_by_name_within_120_days(users):
    u = users()
    fid = store.add_fact(u.id, "race", "Gorgany Ultra Trail", "user")
    with connection() as c:
        c.execute("update facts set details = jsonb_build_object('date', %s::text) where id = %s",
                  ((date.today() + timedelta(days=60)).isoformat(), fid))
    mono.save_item(u.id, "acc", item(9, datetime.now(UTC), mcc=7999, desc="GORGANY ULTRA LIQPAY"))
    money.categorise_pending(u.id)
    with connection() as c:
        r = c.execute("select category from transactions where user_id = %s", (u.id,)).fetchone()
    assert r["category"] == "race_entries"


def test_money_tool_returns_aggregates_only(users):
    u = users()
    _tx(u, datetime.now(UTC), 500, "delivery", "Glovo")
    out = agent.Turn(u, None, False).money_summary()
    text = json.dumps(out, ensure_ascii=False)
    assert set(out) == {"month", "days_counted", "spent_uah", "categories", "top_merchants",
                        "flags", "race_cost", "note"}
    for c in out["categories"]:
        assert set(c) == {"category", "uah", "n", "avg_3m", "ratio", "flag"}
    for ms in out["top_merchants"].values():
        for m in ms:
            assert set(m) == {"name", "n", "uah"}
    for bad in ("ext_id", "account", "balance", "description", "iban", '"at"'):
        assert bad not in text


def test_receipt_splits_the_matched_payment(users):
    u = users()
    now = datetime.now(ZoneInfo(u.time_zone))
    _tx(u, now, 250, "eating_out", "Cafe Lviv")
    rc = receipt.Receipt(store="Cafe Lviv", total=250, kind="restaurant", date=None,
                         lines=[receipt.Line(name="Капучино", price=70),
                                receipt.Line(name="Сендвіч", price=180)])
    r = money.save_receipt(u.id, rc, now)
    assert r["matched"] and r["offer"] == "meal"
    v = money_stats.month_view(u, now.date().replace(day=1), now.date())
    by = {c["category"]: c["uah"] for c in v["categories"]}
    assert by == {"coffee": 70, "eating_out": 180}  # not 250 + 250
    assert "Капучино" in money.receipt_food_text(u.id, r["id"])


# --- routes and isolation ----------------------------------------------------------------

def test_money_routes_isolation(client, users):
    a, b = users(), users()
    store.set_tracks(a.id, ["money"])
    store.set_tracks(b.id, ["money"])
    store.set_setup_step(b.id, 6)
    _tx(a, datetime.now(UTC), 321, "delivery", "SECRET-A Glovo")
    with connection() as c:
        tx = c.execute("select id from transactions where user_id = %s", (a.id,)).fetchone()["id"]
    now = datetime.now(ZoneInfo(a.time_zone))
    rid = money.save_receipt(a.id, receipt.Receipt(store="SECRET-A Cafe", total=99,
                                                   kind="restaurant", lines=[receipt.Line(
                                                       name="Борщ", price=99)]), now)["id"]
    login(client, b)
    for path in ["/money", "/money/settings", "/setup/money/sheet", "/settings", "/"]:
        r = client.get(path)
        assert r.status_code == 200 and "SECRET-A" not in r.text, path
    assert client.post(f"/money/tx/{tx}/category", data={"category": "other"}).status_code == 404
    assert client.post(f"/money/receipt/{rid}/meal").status_code == 404
    assert client.post(f"/money/receipt/{rid}/delete").status_code == 404
    for path in ["/money/delete", "/money/mono/delete"]:
        assert client.post(path, data={"keep": "delete"}, follow_redirects=False).status_code == 303
    with connection() as c:
        n = c.execute("select count(*) as n from transactions where user_id = %s",
                      (a.id,)).fetchone()["n"]
        cat = c.execute("select category from transactions where id = %s", (tx,)).fetchone()
    assert n == 3 and cat["category"] == "delivery"  # payment + receipt + 1 line, untouched


def test_category_correction_and_merchant_rule(client, users):
    a = users()
    store.set_setup_step(a.id, 6)
    mono.save_item(a.id, "acc", item(1, NOW, mcc=5814, desc="Kebab House"))
    mono.save_item(a.id, "acc", item(2, NOW, mcc=5814, desc="Kebab House"))
    money.categorise_pending(a.id)
    with connection() as c:
        tid = c.execute("select id from transactions where user_id = %s limit 1",
                        (a.id,)).fetchone()["id"]
    login(client, a)
    r = client.post(f"/money/tx/{tid}/category", data={"category": "delivery", "always": "1"})
    assert r.status_code == 204
    with connection() as c:
        cats = {r["category"] for r in c.execute(
            "select category from transactions where user_id = %s", (a.id,)).fetchall()}
    assert cats == {"delivery"} and money.user_rules(a.id) == {"kebab house": "delivery"}


def test_bad_token_shows_an_error(client, users, fake):
    a = users()
    store.set_setup_step(a.id, 6)
    fake(status=401)
    login(client, a)
    r = client.post("/money/mono", data={"token": TOKEN, "months": "6"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/money?error=token"
    assert store.get_secret(a.id, "monobank") is None
