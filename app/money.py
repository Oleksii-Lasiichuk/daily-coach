"""Money data: transactions, receipts, categories, merchant rules. Every query is scoped by
user_id.

Receipts: a container row (source 'receipt', ext_id 'rc:…', parent_id = the matched Monobank
row or null) and its lines as children (ext_id 'rl:…'). "Leaf" rows are what totals count:
Monobank rows without a receipt, plus receipt lines, so nothing is counted twice.
"""

import logging
import math
import uuid
from datetime import UTC, date, datetime, timedelta

from app import llm, spend_rules
from app.db import connection
from app.pipeline import receipt as receipt_mod
from app.pipeline import spend

log = logging.getLogger("money")
LEAF = """t.user_id = %s and coalesce(t.ext_id, '') not like 'rc:%%'
          and not exists (select 1 from transactions r where r.parent_id = t.id
                          and r.ext_id like 'rc:%%')"""


def upsert_monobank(user_id: str, row: dict) -> None:
    with connection() as c:
        c.execute(
            """insert into transactions (user_id, source, ext_id, account_id, at, amount_minor,
                   currency, mcc, original_mcc, description, hold)
               values (%(u)s, 'monobank', %(ext_id)s, %(account_id)s, %(at)s, %(amount_minor)s,
                   %(currency)s, %(mcc)s, %(original_mcc)s, %(description)s, %(hold)s)
               on conflict (user_id, source, ext_id) do update set at = excluded.at,
                   amount_minor = excluded.amount_minor, hold = excluded.hold,
                   mcc = excluded.mcc, original_mcc = excluded.original_mcc,
                   description = excluded.description""", row | {"u": user_id})


def user_rules(user_id: str) -> dict[str, str]:
    with connection() as c:
        rows = c.execute("select merchant, category from merchant_rules where user_id = %s",
                         (user_id,)).fetchall()
    return {r["merchant"]: r["category"] for r in rows}


RACE_GENERIC = {"marathon", "half", "race", "trail", "target", "under", "about", "kyiv", "lviv",
                "odesa", "running", "maraphon", "pivmarafon", "marafon"}
RACE_WINDOW_DAYS = 120


def race_words(user_id: str) -> list[tuple[date, set[str]]]:
    """(race date, distinctive name words) per race fact with a date, e.g. 'wizz', 'gorgany'."""
    from app import store
    out = []
    for f in store.list_facts(user_id):
        if f["category"] != "race":
            continue
        d = (f.get("details") or {}).get("date")
        try:
            day = date.fromisoformat(str(d)[:10])
        except ValueError:
            continue
        text = " ".join([f["text"], str((f.get("details") or {}).get("name", "")),
                         str((f.get("details") or {}).get("organiser", ""))])
        words = {w for w in spend_rules.normalise(text).split()
                 if len(w) >= 4 and not w.isdigit() and w not in RACE_GENERIC}
        if words:
            out.append((day, words))
    return out


def is_race_payment(row: dict, races: list[tuple[date, set[str]]]) -> bool:
    """A payment within 120 days before a race to a merchant named like the race."""
    name = set(spend_rules.normalise(row["description"]).split())
    day = row["at"].date()
    return any(0 <= (rd - day).days <= RACE_WINDOW_DAYS and name & words
               for rd, words in races)


def categorise_pending(user_id: str, limit: int = 300) -> dict:
    """Rules for every uncategorised Monobank row; C11 for the merchants left (names + MCC
    only, never transfers). Runs in the tick, not in the webhook."""
    with connection() as c:
        rows = c.execute("select id, at, description, mcc, original_mcc, amount_minor from "
                         "transactions where user_id = %s and source = 'monobank' and "
                         "category is null order by at desc limit %s",
                         (user_id, limit)).fetchall()
    if not rows:
        return {"rule": 0, "llm": 0}
    rules, races = user_rules(user_id), race_words(user_id)
    placed, left = [], {}
    for r in rows:
        cat = spend_rules.categorise(r["description"], r["mcc"], r["amount_minor"],
                                     r["original_mcc"], rules)
        if cat not in ("income", "transfers", "cash") and is_race_payment(r, races):
            cat = "race_entries"
        if cat:
            placed.append((r["id"], cat, "rule"))
        else:
            left.setdefault(spend_rules.normalise(r["description"]), []).append(r)
    n_llm = 0
    if left:
        try:
            got = spend.classify([(m, rs[0]["mcc"]) for m, rs in left.items()], user_id)
        except llm.LLMError as e:
            log.warning("C11 failed: %s", e)
            got = {}
        with connection() as c:
            for m, (cat, _conf) in got.items():
                c.execute("insert into merchant_rules (user_id, merchant, category, by) values "
                          "(%s, %s, %s, 'llm') on conflict do nothing", (user_id, m, cat))
        for m, (cat, _conf) in got.items():
            placed += [(r["id"], cat, "llm") for r in left[m]]
            n_llm += len(left[m])
    with connection() as c:
        for tid, cat, by in placed:
            c.execute("update transactions set category = %s, category_by = %s where "
                      "user_id = %s and id = %s and category is null", (cat, by, user_id, tid))
    return {"rule": len(placed) - n_llm, "llm": n_llm}


def set_category(user_id: str, tx_id: int, category: str, always: bool) -> bool:
    if category not in spend_rules.CATEGORIES:
        return False
    with connection(atomic=True) as c:
        r = c.execute("update transactions set category = %s, category_by = 'user' where "
                      "user_id = %s and id = %s returning description, source",
                      (category, user_id, tx_id)).fetchone()
        if not r:
            return False
        if always and r["source"] == "monobank" and r["description"] != "Transfer":
            m = spend_rules.normalise(r["description"])
            c.execute("insert into merchant_rules (user_id, merchant, category, by) values "
                      "(%s, %s, %s, 'user') on conflict (user_id, merchant) do update set "
                      "category = excluded.category, by = 'user'", (user_id, m, category))
            c.execute("update transactions set category = %s, category_by = 'user' where "
                      "user_id = %s and source = 'monobank' and category_by is distinct from "
                      "'user' and description = %s", (category, user_id, r["description"]))
    return True


def leaf_rows(user_id: str, first: datetime, last: datetime) -> list[dict]:
    """Spending/income rows in [first, last) that totals count (UAH only)."""
    with connection() as c:
        return c.execute(f"""select t.id, t.at, t.amount_minor, t.category, t.description,
                                    t.category_by, t.source, t.parent_id, t.hold
                             from transactions t where {LEAF} and t.currency = 980
                             and t.at >= %s and t.at < %s order by t.at desc""",
                         (user_id, first, last)).fetchall()


# --- receipts ----------------------------------------------------------------------------

def match_transaction(user_id: str, day: date, total_minor: int) -> int | None:
    """A Monobank spending row on the same day ±1 with the total within 1 ₴, without a receipt."""
    with connection() as c:
        r = c.execute(
            """select t.id from transactions t where t.user_id = %s and t.source = 'monobank'
                 and t.amount_minor < 0 and abs(-t.amount_minor - %s) <= 100
                 and (t.at at time zone 'UTC')::date between %s and %s
                 and not exists (select 1 from transactions r where r.parent_id = t.id)
               order by abs(-t.amount_minor - %s), t.at limit 1""",
            (user_id, total_minor, day - timedelta(days=1), day + timedelta(days=1),
             total_minor)).fetchone()
    return r["id"] if r else None


def save_receipt(user_id: str, rc: "receipt_mod.Receipt", now: datetime) -> dict:
    """Saves the receipt and its lines; splits the matched Monobank row. Returns
    {id, matched, lines, offer}."""
    lines = receipt_mod.categorised_lines(rc)
    try:
        day = date.fromisoformat(rc.date) if rc.date else now.date()
    except ValueError:
        day = now.date()
    at = now if day == now.date() else datetime.combine(day, now.timetz())
    total_minor = round(rc.total * 100)
    matched = match_transaction(user_id, day, total_minor)
    key = uuid.uuid4().hex[:16]
    with connection(atomic=True) as c:
        rid = c.execute(
            """insert into transactions (user_id, source, ext_id, at, amount_minor, description,
                   category, category_by, parent_id) values (%s, 'receipt', %s, %s, %s, %s,
                   null, 'receipt', %s) returning id""",
            (user_id, f"rc:{key}", at, -total_minor, rc.store[:120] or "Receipt",
             matched)).fetchone()["id"]
        for i, ln in enumerate(lines):
            c.execute(
                """insert into transactions (user_id, source, ext_id, at, amount_minor,
                       description, category, category_by, parent_id)
                   values (%s, 'receipt', %s, %s, %s, %s, %s, 'receipt', %s)""",
                (user_id, f"rl:{key}:{i}", at, -round(ln["amount"] * 100), ln["name"],
                 ln["category"], rid))
    return {"id": rid, "matched": matched is not None, "lines": lines,
            "offer": receipt_mod.offer_for(rc, lines), "store": rc.store, "total": rc.total,
            "kind": rc.kind}


def receipt_food_text(user_id: str, receipt_id: int) -> str | None:
    """The food lines of a saved receipt as a meal description for C3."""
    with connection() as c:
        head = c.execute("select description from transactions where user_id = %s and id = %s "
                         "and ext_id like 'rc:%%'", (user_id, receipt_id)).fetchone()
        if not head:
            return None
        lines = c.execute("select description, category from transactions where user_id = %s "
                          "and parent_id = %s and ext_id like 'rl:%%' order by id",
                          (user_id, receipt_id)).fetchall()
    food = [ln["description"] for ln in lines if ln["category"] in spend_rules.FOOD]
    return f"{', '.join(food)} (from a receipt at {head['description']})" if food else None


def delete_receipt(user_id: str, receipt_id: int) -> bool:
    with connection() as c:
        r = c.execute("delete from transactions where user_id = %s and id = %s and ext_id like "
                      "'rc:%%' returning id", (user_id, receipt_id)).fetchone()
    return r is not None


def delete_all(user_id: str) -> None:
    with connection(atomic=True) as c:
        c.execute("delete from transactions where user_id = %s", (user_id,))
        c.execute("delete from merchant_rules where user_id = %s", (user_id,))


def status(user_id: str) -> dict:
    """For Settings and the Money page header: accounts, import progress, last import."""
    with connection() as c:
        accs = c.execute("select * from money_accounts where user_id = %s order by account_id",
                         (user_id,)).fetchall()
        n = c.execute("select count(*) as n from transactions where user_id = %s",
                      (user_id,)).fetchone()["n"]
    from app import mono
    now = datetime.now(UTC)
    total = done = 0
    for a in accs:
        windows = max(1, math.ceil((now - a["import_since"]) / mono.WINDOW))
        total += windows
        if a["imported_from"] is not None:
            done += min(windows, math.ceil((a["synced_until"] - a["imported_from"]) / mono.WINDOW))
    last = max((a["synced_until"] for a in accs if a["synced_until"]), default=None)
    return {"accounts": accs, "last4": [a["last4"] for a in accs if a["last4"]],
            "windows_total": total, "windows_done": done, "importing": bool(accs) and done < total,
            "eta_min": (total - done) * 15, "last_import": last, "n_rows": n}
