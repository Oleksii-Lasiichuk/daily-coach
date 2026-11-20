"""Spending insights (code, plan 11 B4). Numbers only; the coach puts them into words.

Per category: this month so far, the same days of the previous 3 months on average, the ratio
and the count. A flag when ratio ≥ 1.5 and the difference ≥ 500 ₴ ("up") or ratio ≤ 0.5 and the
difference ≥ 500 ₴ ("down"). Race cost = race entries + sport gear + sports nutrition since the
race was added. Only UAH rows count (other currencies are listed, not summed).
"""

import calendar
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app import money, spend_rules, store

NOT_SPENDING = {"transfers", "income", "cash"}
RACE_COST = {"race_entries", "sport_gear", "sports_nutrition"}
FLAG_RATIO_UP, FLAG_RATIO_DOWN, FLAG_MIN_UAH = 1.5, 0.5, 500


def _bounds(first: date, days: int, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(first, time(), tz)
    return start.astimezone(UTC), (start + timedelta(days=days)).astimezone(UTC)


def _shift(first: date, months: int) -> date:
    y, m = divmod(first.year * 12 + first.month - 1 - months, 12)
    return date(y, m + 1, 1)


def _spend(rows: list[dict]) -> dict[str, dict]:
    """category -> {uah, n} for spending rows (UAH, positive numbers)."""
    out: dict[str, dict] = defaultdict(lambda: {"uah": 0.0, "n": 0})
    for r in rows:
        cat = r["category"] or "other"
        if r["amount_minor"] >= 0 or cat in NOT_SPENDING:
            continue
        out[cat]["uah"] += -r["amount_minor"] / 100
        out[cat]["n"] += 1
    return out


def top_merchants(rows: list[dict], k: int = 3) -> dict[str, list[dict]]:
    by: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        cat = r["category"] or "other"
        if r["amount_minor"] >= 0 or cat in NOT_SPENDING or not r["description"]:
            continue
        m = by[cat].setdefault(spend_rules.normalise(r["description"]),
                               {"name": r["description"][:40], "n": 0, "uah": 0.0})
        m["n"] += 1
        m["uah"] += -r["amount_minor"] / 100
    return {c: [{"name": m["name"], "n": m["n"], "uah": round(m["uah"])}
                for m in sorted(ms.values(), key=lambda m: (-m["n"], -m["uah"]))[:k]]
            for c, ms in by.items()}


def compare(cur: dict[str, dict], prev: list[dict[str, dict]]) -> list[dict]:
    """Rows per category with the average of the previous months that have data."""
    cats = set(cur) | {c for p in prev for c in p}
    out = []
    for c in cats:
        now_uah = round(cur.get(c, {}).get("uah", 0.0))
        avg = round(sum(p.get(c, {}).get("uah", 0.0) for p in prev) / len(prev)) if prev else None
        ratio = round(now_uah / avg, 2) if avg else None
        flag = None
        if avg is not None and ratio is not None:
            if ratio >= FLAG_RATIO_UP and now_uah - avg >= FLAG_MIN_UAH:
                flag = "up"
            elif ratio <= FLAG_RATIO_DOWN and avg - now_uah >= FLAG_MIN_UAH:
                flag = "down"
        out.append({"category": c, "uah": now_uah, "n": cur.get(c, {}).get("n", 0),
                    "avg_3m": avg, "ratio": ratio, "flag": flag})
    return sorted(out, key=lambda r: -r["uah"])


def month_view(user: store.User, month: date, today: date) -> dict:
    """Everything the Money page and the coach tool need for one month (first day given)."""
    tz = ZoneInfo(user.time_zone)
    month = month.replace(day=1)
    length = calendar.monthrange(month.year, month.month)[1]
    days = today.day if (month.year, month.month) == (today.year, today.month) else length
    first, last = _bounds(month, days, tz)
    rows = money.leaf_rows(user.id, first, last)
    prev = []
    for k in (1, 2, 3):
        p = _shift(month, k)
        n = min(days, calendar.monthrange(p.year, p.month)[1])
        f, la = _bounds(p, n, tz)
        p_rows = money.leaf_rows(user.id, f, la)
        if p_rows:
            prev.append(_spend(p_rows))
    cats = compare(_spend(rows), prev)
    return {"month": month, "days": days, "rows": rows,
            "spent": sum(c["uah"] for c in cats), "categories": cats,
            "flags": [c for c in cats if c["flag"]], "top": top_merchants(rows),
            "race": race_cost(user), "has_history": bool(prev)}


def race_cost(user: store.User) -> dict | None:
    """Race entries + gear + sports nutrition since the next race was added."""
    races = [f for f in store.list_facts(user.id) if f["category"] == "race"]
    if not races:
        return None
    race = max(races, key=lambda f: f["created_at"])
    rows = money.leaf_rows(user.id, race["created_at"], datetime.now(UTC) + timedelta(days=1))
    spent = _spend(rows)
    parts = {c: round(spent[c]["uah"]) for c in RACE_COST if c in spent}
    return {"race": race["text"][:80], "since": race["created_at"].date(),
            "uah": sum(parts.values()), "parts": parts}


def summary(user: store.User, today: date, month: str | None = None) -> dict:
    """The coach's money_summary tool: aggregates only (no single transactions, dates of
    single purchases, account ids, balances or transfer descriptions)."""
    try:
        m = date.fromisoformat(month + "-01") if month and len(month) == 7 else today
    except ValueError:
        m = today
    v = month_view(user, m.replace(day=1), today)
    return {"month": v["month"].strftime("%Y-%m"), "days_counted": v["days"],
            "spent_uah": v["spent"],
            "categories": [{k: c[k] for k in ("category", "uah", "n", "avg_3m", "ratio", "flag")}
                           for c in v["categories"]],
            "top_merchants": v["top"],
            "flags": [f"{c['category']}: {c['ratio']}x the 3-month usual "
                      f"({c['uah']} vs {c['avg_3m']} UAH, {c['n']} payments)"
                      for c in v["flags"]],
            "race_cost": v["race"] and {k: v["race"][k] for k in ("race", "uah", "parts")},
            "note": "UAH only; same days of the month compared with the previous 3 months."}


def context_flags(user: store.User, today: date) -> list[str]:
    """At most 2 short facts for the coach context (only for people who track money)."""
    if "money" not in (user.tracks or []):
        return []
    v = month_view(user, today.replace(day=1), today)
    return [f"{c['category']} this month: {c['uah']} UAH, {c['ratio']}x the usual "
            f"({c['n']} payments)" for c in v["flags"][:2]]


def week_food(user: store.User, today: date) -> tuple[int, int] | None:
    """Sunday push: (food, delivery) UAH of the last 7 days, or None."""
    if "money" not in (user.tracks or []):
        return None
    tz = ZoneInfo(user.time_zone)
    first, last = _bounds(today - timedelta(days=6), 7, tz)
    s = _spend(money.leaf_rows(user.id, first, last))
    food = round(sum(s[c]["uah"] for c in spend_rules.FOOD if c in s))
    if not food:
        return None
    return food, round(s["delivery"]["uah"]) if "delivery" in s else 0
