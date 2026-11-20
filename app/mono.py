"""Monobank personal API (read-only): connect, statement import in the tick, webhook.

Limits (api.monobank.ua/docs, spec v250818): client-info and statement are each 1 request per
60 s; a statement window is at most 31 days + 1 hour. The tick runs every 15 minutes and
`sync_step` makes at most ONE Monobank call per user per tick, so the limit always holds.

Import: the oldest not-yet-imported 31-day window of one account per tick, back to the period
the person chose (1/3/6/12 months); then a catch-up window [synced_until − 1 h, now] per account
every 6 h. The webhook delivers new items in between; the catch-up covers a webhook Monobank
switched off. Items are upserted by Monobank id, so a hold settles into the same row.

Privacy: the token is encrypted (app/crypto.py) and never logged. From client-info only the
account id, type, currency and the last 4 card digits are kept; from statement items no
comment, counterparty, balance or receipt id. P2P transfer descriptions become "Transfer".
"""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

import httpx

from app import crypto, money, spend_rules, store
from app.config import get_settings
from app.db import connection

log = logging.getLogger("mono")
BASE = "https://api.monobank.ua"
WINDOW = timedelta(seconds=2_682_000)  # 31 days + 1 hour
CATCH_UP_EVERY = timedelta(hours=6)
ROW_CAP = 500  # older API versions returned at most 500 items, newest first
MONTHS = (1, 3, 6, 12)
http: httpx.Client | None = None  # tests put an httpx.MockTransport client here


class MonoError(Exception):
    pass


class RateLimited(MonoError):
    pass


class BadToken(MonoError):
    pass


def _client() -> httpx.Client:
    global http
    if http is None:
        http = httpx.Client(base_url=BASE, timeout=20)
    return http


def _call(method: str, path: str, token: str, json: dict | None = None):
    try:
        r = _client().request(method, path, headers={"X-Token": token}, json=json)
    except httpx.HTTPError as e:
        raise MonoError(f"network: {type(e).__name__}") from e
    if r.status_code == 429:
        raise RateLimited("too many requests")
    if r.status_code in (401, 403):
        raise BadToken("token rejected")
    if r.status_code != 200:
        raise MonoError(f"HTTP {r.status_code}")
    return r.json() if r.content else {}


def client_info(token: str) -> dict:
    return _call("GET", "/personal/client-info", token)


def statement(token: str, account: str, frm: datetime, to: datetime) -> list[dict]:
    return _call("GET", f"/personal/statement/{account}/{int(frm.timestamp())}/"
                 f"{int(to.timestamp())}", token)


def set_webhook(token: str, url: str) -> None:
    _call("POST", "/personal/webhook", token, json={"webHookUrl": url})


def token_of(user_id: str) -> str | None:
    row = store.get_secret(user_id, "monobank")
    return crypto.decrypt(row["ciphertext"]) if row else None


def hook_hash(hook_token: str) -> str:
    return hashlib.sha256(hook_token.encode()).hexdigest()


# --- connect / disconnect ----------------------------------------------------------------

def connect(user_id: str, token: str, months: int = 6, now: datetime | None = None) -> int:
    """Checks the token with one client-info call, saves the accounts and the encrypted token,
    sets the webhook (prod only: needs a public SELF_URL). Returns the number of accounts."""
    now = now or datetime.now(UTC)
    months = months if months in MONTHS else 6
    info = client_info(token)
    accounts = [a for a in info.get("accounts", []) if a.get("id")]
    since = now - timedelta(days=round(30.44 * months))
    with connection(atomic=True) as c:
        for a in accounts:
            pan = (a.get("maskedPan") or [""])[0]
            c.execute(
                """insert into money_accounts (user_id, account_id, kind, currency, last4,
                       import_since) values (%s, %s, %s, %s, %s, %s)
                   on conflict (user_id, account_id) do update set kind = excluded.kind,
                       currency = excluded.currency, last4 = excluded.last4,
                       import_since = least(money_accounts.import_since, excluded.import_since),
                       next_at = now()""",
                (user_id, a["id"], a.get("type") or "card", a.get("currencyCode") or 980,
                 pan[-4:] or None, since))
    store.save_secret(user_id, "monobank", crypto.encrypt(token), crypto.last4(token), None)
    _ensure_webhook(user_id, token)
    return len(accounts)


def _ensure_webhook(user_id: str, token: str) -> None:
    base = get_settings().self_url.rstrip("/")
    if not base.startswith("https://"):
        return  # local dev: Monobank can't reach us; the 6-hourly catch-up does the work
    hook = secrets.token_urlsafe(32)
    with connection() as c:
        c.execute("insert into money_hooks (hook_hash, user_id) values (%s, %s) on conflict "
                  "(user_id) do update set hook_hash = excluded.hook_hash",
                  (hook_hash(hook), user_id))
    try:
        set_webhook(token, f"{base}/hooks/mono/{hook}")
    except MonoError as e:
        log.warning("webhook not set: %s", e)


def disconnect(user_id: str, delete_data: bool) -> None:
    token = token_of(user_id)
    if token:
        try:
            set_webhook(token, "")  # stop Monobank calling us
        except MonoError as e:
            log.info("webhook unset failed: %s", e)
    store.delete_secret(user_id, "monobank")
    with connection(atomic=True) as c:
        c.execute("delete from money_hooks where user_id = %s", (user_id,))
        c.execute("delete from money_accounts where user_id = %s", (user_id,))
        if delete_data:
            c.execute("delete from transactions where user_id = %s and source = 'monobank'",
                      (user_id,))


# --- import (tick) -----------------------------------------------------------------------

def next_window(acc: dict, now: datetime) -> tuple[datetime, datetime, str]:
    """(from, to, kind) of the next statement call for an account: 'first', 'older', 'catch_up'."""
    since = acc["import_since"]
    if acc["imported_from"] is None:
        return max(since, now - WINDOW), now, "first"
    if acc["imported_from"] > since:
        return max(since, acc["imported_from"] - WINDOW), acc["imported_from"], "older"
    frm = max(acc["synced_until"] - timedelta(hours=1), now - WINDOW)
    return frm, now, "catch_up"


def sync_step(user_id: str, now: datetime | None = None) -> int:
    """At most one Monobank call: the due account with the oldest next_at. Returns rows saved."""
    now = now or datetime.now(UTC)
    with connection() as c:
        acc = c.execute("select * from money_accounts where user_id = %s and next_at <= %s "
                        "order by next_at, account_id limit 1", (user_id, now)).fetchone()
    token = acc and token_of(user_id)
    if not acc or not token:
        return 0
    frm, to, kind = next_window(acc, now)
    try:
        items = statement(token, acc["account_id"], frm, to)
    except RateLimited:
        _set(user_id, acc["account_id"], next_at=now + timedelta(minutes=2))
        return 0
    except BadToken:
        log.warning("monobank token rejected for a user; pausing their import for a day")
        _set(user_id, acc["account_id"], next_at=now + timedelta(days=1))
        return 0
    except MonoError as e:
        log.warning("monobank statement failed: %s", e)
        _set(user_id, acc["account_id"], next_at=now + timedelta(minutes=10))
        return 0
    saved = sum(save_item(user_id, acc["account_id"], it) for it in items)
    covered_from = frm
    if len(items) >= ROW_CAP:  # maybe cut: continue from the oldest item next tick
        covered_from = datetime.fromtimestamp(min(it["time"] for it in items), UTC)
    if kind == "first":
        _set(user_id, acc["account_id"], imported_from=covered_from, synced_until=to,
             next_at=now)
    elif kind == "older":
        _set(user_id, acc["account_id"], imported_from=covered_from, next_at=now)
    else:
        if covered_from > frm:
            log.warning("catch-up window hit the row cap; older part left to the next call")
            _set(user_id, acc["account_id"], next_at=now)
        else:
            _set(user_id, acc["account_id"], synced_until=to, next_at=now + CATCH_UP_EVERY)
    return saved


def _set(user_id: str, account_id: str, **cols) -> None:
    sets = ", ".join(f"{k} = %s" for k in cols)
    with connection() as c:
        c.execute(f"update money_accounts set {sets} where user_id = %s and account_id = %s",
                  (*cols.values(), user_id, account_id))


def check_webhook(user_id: str) -> None:
    """Once a day (tick): if Monobank switched our webhook off, set it again."""
    token = token_of(user_id)
    if not token or not get_settings().self_url.startswith("https://"):
        return
    try:
        if not client_info(token).get("webHookUrl"):
            _ensure_webhook(user_id, token)
    except MonoError as e:
        log.info("webhook check failed: %s", e)


# --- items -------------------------------------------------------------------------------

def save_item(user_id: str, account_id: str, it: dict) -> int:
    """Upserts one statement item (only the fields we keep). Returns 1 if saved."""
    if not it.get("id") or "time" not in it or "amount" not in it:
        return 0
    mcc, omcc = it.get("mcc"), it.get("originalMcc")
    desc = "Transfer" if spend_rules.is_transfer(mcc, omcc) else (it.get("description") or "")
    money.upsert_monobank(user_id, {
        "ext_id": str(it["id"]), "account_id": account_id,
        "at": datetime.fromtimestamp(int(it["time"]), UTC), "amount_minor": int(it["amount"]),
        "currency": it.get("currencyCode") or 980, "mcc": mcc, "original_mcc": omcc,
        "description": desc[:200], "hold": bool(it.get("hold"))})
    return 1


def webhook_user(hook_token: str) -> str | None:
    with connection() as c:
        r = c.execute("select user_id from money_hooks where hook_hash = %s",
                      (hook_hash(hook_token),)).fetchone()
    return str(r["user_id"]) if r else None


def handle_webhook(hook_token: str, body: dict) -> bool | None:
    """None = unknown token; False = ignored (not a statement item, or a foreign account);
    True = saved. One lookup and one insert, nothing else (Monobank waits only 5 s)."""
    user_id = webhook_user(hook_token)
    if not user_id:
        return None
    data = body.get("data") or {}
    if body.get("type") != "StatementItem" or not isinstance(data.get("statementItem"), dict):
        return False
    with connection() as c:
        ok = c.execute("select 1 from money_accounts where user_id = %s and account_id = %s",
                       (user_id, str(data.get("account")))).fetchone()
    if not ok:
        return False
    return bool(save_item(user_id, str(data["account"]), data["statementItem"]))
