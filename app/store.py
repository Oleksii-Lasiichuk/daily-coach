"""Every database read and write. Each function that touches personal data takes user_id first,
and every query filters by it (S2 in docs/design-guidelines.md)."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from psycopg.types.json import Jsonb

from app.db import connection


@dataclass
class User:
    id: str
    email: str
    display_name: str | None
    time_zone: str
    setup_step: int = 5
    ai_access: str = "allowed"  # 'allowed' (may use the app's key) or 'blocked'
    monthly_cap_usd: float | None = None  # None = the default cap for the role
    key_pool: str = "main"  # which app key pays: 'main' or 'family'
    tracks: list = field(default_factory=list)  # chosen at sign-up: 'training', 'weather', …
    is_new: bool = False  # set by upsert_user on the first sign-in


def _user(row: dict | None) -> User | None:
    if row is None:
        return None
    cap = row.get("monthly_cap_usd")
    return User(id=str(row["id"]), email=row["email"], display_name=row["display_name"],
                time_zone=row["time_zone"], setup_step=row.get("setup_step", 5),
                ai_access=row.get("ai_access", "allowed"),
                monthly_cap_usd=float(cap) if cap is not None else None,
                key_pool=row.get("key_pool", "main"), tracks=row.get("tracks") or [],
                is_new=bool(row.get("inserted")))


# --- users -------------------------------------------------------------------------------

def upsert_user(firebase_uid: str, email: str, display_name: str | None) -> User:
    with connection() as c:
        row = c.execute(
            """insert into users (firebase_uid, email, display_name) values (%s, %s, %s)
               on conflict (firebase_uid) do update
                 set email = excluded.email, display_name = excluded.display_name
               returning *, (xmax = 0) as inserted""",
            (firebase_uid, email.lower(), display_name),
        ).fetchone()
    return _user(row)


def get_user(user_id: str) -> User | None:
    with connection() as c:
        return _user(c.execute("select * from users where id = %s", (user_id,)).fetchone())


def set_setup_step(user_id: str, step: int) -> None:
    with connection() as c:
        c.execute("update users set setup_step = %s where id = %s", (step, user_id))


def set_tracks(user_id: str, tracks: list[str]) -> None:
    with connection() as c:
        c.execute("update users set tracks = %s where id = %s", (Jsonb(tracks), user_id))


def set_ai_access(user_id: str, *, access: str, cap: float | None, key_pool: str) -> None:
    """Admin only (checked by the route): who may use the app's key, up to which cap."""
    with connection() as c:
        c.execute("update users set ai_access = %s, monthly_cap_usd = %s, key_pool = %s "
                  "where id = %s", (access, cap, key_pool, user_id))


def all_users_with_cost() -> list[dict]:
    """Admin page: every account with this month's AI cost (no personal data beyond the
    name and email they signed in with)."""
    with connection() as c:
        return c.execute(
            """select u.id, u.email, u.display_name, u.created_at, u.ai_access,
                      u.monthly_cap_usd, u.key_pool, u.setup_step,
                      exists (select 1 from user_secrets s where s.user_id = u.id
                              and s.provider = 'openrouter') as own_key,
                      coalesce((select sum(cost_usd) from llm_usage l where l.user_id = u.id
                                and l.created_at >= date_trunc('month', now())), 0) as cost,
                      (select max(created_at) from chat_messages m where m.user_id = u.id
                       and m.role = 'user') as last_seen
               from users u order by u.created_at desc""").fetchall()


def set_time_zone(user_id: str, time_zone: str) -> None:
    with connection() as c:
        c.execute("update users set time_zone = %s where id = %s", (time_zone, user_id))


def user_lang(user_id: str) -> str:
    with connection() as c:
        r = c.execute("select lang from user_prefs where user_id = %s", (user_id,)).fetchone()
    return r["lang"] if r else "en"


def set_lang(user_id: str, lang: str) -> None:
    with connection() as c:
        c.execute("insert into user_prefs (user_id, lang) values (%s, %s) on conflict (user_id) "
                  "do update set lang = excluded.lang", (user_id, lang))


def mark_once(user_id: str, key: str, day: date) -> bool:
    """True the first time `key` is seen on `day` (nudges, hourly syncs, weekly reviews)."""
    with connection() as c:
        r = c.execute("insert into nudges_sent (user_id, nudge, day) values (%s, %s, %s) "
                      "on conflict do nothing returning 1", (user_id, key, day)).fetchone()
    return r is not None


# --- secrets -----------------------------------------------------------------------------

def save_secret(user_id: str, provider: str, ciphertext: str, last4: str,
                external_id: str | None) -> None:
    with connection() as c:
        c.execute(
            """insert into user_secrets (user_id, provider, ciphertext, last4, external_id)
               values (%s, %s, %s, %s, %s)
               on conflict (user_id, provider) do update set ciphertext = excluded.ciphertext,
                 last4 = excluded.last4, external_id = excluded.external_id, created_at = now()""",
            (user_id, provider, ciphertext, last4, external_id),
        )


def get_secret(user_id: str, provider: str) -> dict | None:
    with connection() as c:
        return c.execute("select * from user_secrets where user_id = %s and provider = %s",
                         (user_id, provider)).fetchone()


def delete_secret(user_id: str, provider: str) -> None:
    with connection() as c:
        c.execute("delete from user_secrets where user_id = %s and provider = %s",
                  (user_id, provider))


# --- profile -----------------------------------------------------------------------------

def get_profile(user_id: str) -> dict[str, dict]:
    """key -> {value, source, updated_at}"""
    with connection() as c:
        rows = c.execute("select key, value, source, updated_at from profile_fields "
                         "where user_id = %s order by key", (user_id,)).fetchall()
    return {r["key"]: {"value": r["value"], "source": r["source"], "updated_at": r["updated_at"]}
            for r in rows}


def set_profile_field(user_id: str, key: str, value: Any, source: str,
                      actor: str = "system", overwrite_user: bool = True) -> None:
    """Writes one field and an audit row. With overwrite_user=False, a value the user typed
    is kept (used by the intervals.icu prefill)."""
    with connection() as c:
        old = c.execute("select value, source from profile_fields where user_id = %s and key = %s",
                        (user_id, key)).fetchone()
        if old and old["source"] == "user" and not overwrite_user:
            return
        if old and old["value"] == value:
            return
        c.execute(
            """insert into profile_fields (user_id, key, value, source) values (%s, %s, %s, %s)
               on conflict (user_id, key) do update set value = excluded.value,
                 source = excluded.source, updated_at = now()""",
            (user_id, key, Jsonb(value), source),
        )
        _audit(c, user_id, actor, "set", "profile_field", key,
               old["value"] if old else None, value)


def delete_profile_field(user_id: str, key: str) -> None:
    with connection() as c:
        old = c.execute("delete from profile_fields where user_id = %s and key = %s "
                        "returning value", (user_id, key)).fetchone()
        if old:
            _audit(c, user_id, "user", "delete", "profile_field", key, old["value"], None)


# --- chat --------------------------------------------------------------------------------

def add_message(user_id: str, role: str, content: str, trace_id: str | None = None) -> int:
    with connection() as c:
        return c.execute("insert into chat_messages (user_id, role, content, trace_id) "
                         "values (%s, %s, %s, %s) returning id",
                         (user_id, role, content, trace_id)).fetchone()["id"]


def recent_messages(user_id: str, limit: int = 20) -> list[dict]:
    with connection() as c:
        rows = c.execute("select id, role, content, attachments, created_at from chat_messages "
                         "where user_id = %s order by id desc limit %s",
                         (user_id, limit)).fetchall()
    return list(reversed(rows))


# --- chat turns (a reply runs in the background, so leaving the page loses nothing) -----

TURN_TIMEOUT_MIN = 3


def start_turn(user_id: str, message_id: int) -> int:
    with connection() as c:
        return c.execute("insert into chat_turns (user_id, message_id) values (%s, %s) "
                         "returning id", (user_id, message_id)).fetchone()["id"]


def finish_turn(user_id: str, turn_id: int, reply_id: int | None, error: str | None) -> None:
    with connection() as c:
        c.execute("update chat_turns set status = %s, reply_id = %s, error = %s, "
                  "finished_at = now() where id = %s and user_id = %s",
                  ("done" if reply_id else "failed", reply_id, error, turn_id, user_id))


def get_turn(user_id: str, turn_id: int) -> dict | None:
    """A turn running longer than TURN_TIMEOUT_MIN is treated as failed (the server restarted
    or the model hung)."""
    with connection() as c:
        c.execute("update chat_turns set status = 'failed', error = 'timeout', finished_at = "
                  "now() where user_id = %s and status = 'running' and started_at < now() - "
                  "make_interval(mins => %s)", (user_id, TURN_TIMEOUT_MIN))
        return c.execute("select * from chat_turns where id = %s and user_id = %s",
                         (turn_id, user_id)).fetchone()


def running_turn(user_id: str) -> dict | None:
    with connection() as c:
        r = c.execute("select id from chat_turns where user_id = %s and status = 'running' "
                      "order by id desc limit 1", (user_id,)).fetchone()
    return get_turn(user_id, r["id"]) if r else None


# --- facts -------------------------------------------------------------------------------

def add_fact(user_id: str, category: str, text: str, source: str,
             valid_from: date | None = None, message_id: int | None = None) -> int:
    with connection() as c:
        fid = c.execute(
            "insert into facts (user_id, category, text, source, valid_from, message_id) "
            "values (%s, %s, %s, %s, %s, %s) returning id",
            (user_id, category, text, source, valid_from, message_id)).fetchone()["id"]
        _audit(c, user_id, "ai" if source == "ai" else "user", "add", "fact", str(fid), None,
               {"category": category, "text": text})
    return fid


def list_facts(user_id: str, status: str | None = "active") -> list[dict]:
    """status=None: active and resolved (never facts still waiting for review)."""
    with connection() as c:
        if status:
            return c.execute("select * from facts where user_id = %s and status = %s "
                             "order by category, id", (user_id, status)).fetchall()
        return c.execute(
            """select f.*, s.filename from facts f left join sources s on s.id = f.source_id
               where f.user_id = %s and f.status <> 'proposed'
               order by f.status, f.category, f.id""", (user_id,)).fetchall()


def update_fact(user_id: str, fact_id: int, *, text: str | None = None,
                status: str | None = None) -> bool:
    with connection() as c:
        old = c.execute("select text, status from facts where user_id = %s and id = %s",
                        (user_id, fact_id)).fetchone()
        if not old:
            return False
        new = {"text": text or old["text"], "status": status or old["status"]}
        c.execute("update facts set text = %s, status = %s, valid_to = case when %s = 'resolved' "
                  "then current_date else valid_to end where user_id = %s and id = %s",
                  (new["text"], new["status"], new["status"], user_id, fact_id))
        _audit(c, user_id, "user", "update", "fact", str(fact_id), dict(old), new)
    return True


def delete_fact(user_id: str, fact_id: int) -> bool:
    with connection() as c:
        old = c.execute("delete from facts where user_id = %s and id = %s returning text",
                        (user_id, fact_id)).fetchone()
        if old:
            _audit(c, user_id, "user", "delete", "fact", str(fact_id), dict(old), None)
    return old is not None


# --- logs --------------------------------------------------------------------------------

def add_log(user_id: str, kind: str, day: date, data: dict, occurred_at: datetime | None = None,
            message_id: int | None = None) -> int:
    with connection() as c:
        return c.execute(
            "insert into logs (user_id, kind, day, occurred_at, data, message_id) "
            "values (%s, %s, %s, %s, %s, %s) returning id",
            (user_id, kind, day, occurred_at, Jsonb(data), message_id)).fetchone()["id"]


def logs_between(user_id: str, first: date, last: date) -> list[dict]:
    with connection() as c:
        return c.execute("select * from logs where user_id = %s and day between %s and %s "
                         "order by day, coalesce(occurred_at, created_at)",
                         (user_id, first, last)).fetchall()


def delete_log(user_id: str, log_id: int) -> bool:
    with connection() as c:
        old = c.execute("delete from logs where user_id = %s and id = %s returning kind, data",
                        (user_id, log_id)).fetchone()
        if old:
            _audit(c, user_id, "user", "delete", "log", str(log_id), dict(old), None)
    return old is not None


def get_log(user_id: str, log_id: int) -> dict | None:
    with connection() as c:
        return c.execute("select * from logs where user_id = %s and id = %s",
                         (user_id, log_id)).fetchone()


def update_log_data(user_id: str, log_id: int, data: dict) -> None:
    with connection() as c:
        old = c.execute("update logs set data = %s where user_id = %s and id = %s "
                        "returning id", (Jsonb(data), user_id, log_id)).fetchone()
        if old:
            _audit(c, user_id, "user", "update", "log", str(log_id), None, data)


# --- habits ------------------------------------------------------------------------------

def habits_for_day(user_id: str, day: date) -> list[dict]:
    with connection() as c:
        return c.execute(
            "select h.id, h.name, (hc.day is not null) as done from habits h left join "
            "habit_checks hc on hc.habit_id = h.id and hc.day = %s where h.user_id = %s and "
            "h.active order by h.id", (day, user_id)).fetchall()


def add_habit(user_id: str, name: str) -> None:
    with connection() as c:
        c.execute("insert into habits (user_id, name) values (%s, %s)", (user_id, name[:60]))


def remove_habit(user_id: str, habit_id: int) -> None:
    with connection() as c:
        c.execute("update habits set active = false where user_id = %s and id = %s",
                  (user_id, habit_id))


def toggle_habit(user_id: str, habit_id: int, day: date) -> None:
    with connection() as c:
        if not c.execute("select 1 from habits where user_id = %s and id = %s",
                         (user_id, habit_id)).fetchone():
            return
        gone = c.execute("delete from habit_checks where habit_id = %s and day = %s returning 1",
                         (habit_id, day)).fetchone()
        if not gone:
            c.execute("insert into habit_checks (user_id, habit_id, day) values (%s, %s, %s)",
                      (user_id, habit_id, day))


# --- day assessments ---------------------------------------------------------------------

def save_assessment(user_id: str, day: date, day_type: str, confidence: float,
                    reasons: list, inputs: dict, trace_id: str | None) -> None:
    with connection() as c:
        c.execute(
            """insert into day_assessments (user_id, day, day_type, confidence, reasons, inputs,
                 trace_id) values (%s, %s, %s, %s, %s, %s, %s)
               on conflict (user_id, day) do update set day_type = excluded.day_type,
                 confidence = excluded.confidence, reasons = excluded.reasons,
                 inputs = excluded.inputs, trace_id = excluded.trace_id, created_at = now()""",
            (user_id, day, day_type, confidence, Jsonb(reasons), Jsonb(inputs), trace_id))


def get_assessment(user_id: str, day: date) -> dict | None:
    with connection() as c:
        return c.execute("select * from day_assessments where user_id = %s and day = %s",
                         (user_id, day)).fetchone()


# --- proposals ---------------------------------------------------------------------------

def add_proposal(user_id: str, day: date, workout: dict, rationale: str, evidence: list) -> int:
    with connection() as c:
        c.execute("update proposals set status = 'dismissed' where user_id = %s and day = %s "
                  "and status = 'proposed'", (user_id, day))
        return c.execute(
            "insert into proposals (user_id, day, workout, rationale, evidence) "
            "values (%s, %s, %s, %s, %s) returning id",
            (user_id, day, Jsonb(workout), rationale, Jsonb(evidence))).fetchone()["id"]


def get_proposal(user_id: str, proposal_id: int) -> dict | None:
    with connection() as c:
        return c.execute("select * from proposals where user_id = %s and id = %s",
                         (user_id, proposal_id)).fetchone()


def proposals_for_day(user_id: str, day: date) -> list[dict]:
    with connection() as c:
        return c.execute("select * from proposals where user_id = %s and day = %s "
                         "and status in ('proposed', 'applied', 'undone') order by id desc",
                         (user_id, day)).fetchall()


def set_proposal_status(user_id: str, proposal_id: int, status: str,
                        intervals_event_id: str | None = None) -> None:
    with connection() as c:
        old = c.execute("select status from proposals where user_id = %s and id = %s",
                        (user_id, proposal_id)).fetchone()
        c.execute(
            "update proposals set status = %s, intervals_event_id = coalesce(%s, "
            "intervals_event_id), applied_at = case when %s = 'applied' then now() "
            "else applied_at end where user_id = %s and id = %s",
            (status, intervals_event_id, status, user_id, proposal_id))
        _audit(c, user_id, "user", status, "proposal", str(proposal_id),
               {"status": old["status"]} if old else None, {"status": status})


# --- usage -------------------------------------------------------------------------------

def record_usage(user_id: str | None, component: str, model: str, input_tokens: int,
                 output_tokens: int, cost_usd: float) -> None:
    with connection() as c:
        c.execute("insert into llm_usage (user_id, component, model, input_tokens, "
                  "output_tokens, cost_usd) values (%s, %s, %s, %s, %s, %s)",
                  (user_id, component, model, input_tokens, output_tokens, cost_usd))


def month_cost(user_id: str) -> float:
    with connection() as c:
        row = c.execute("select coalesce(sum(cost_usd), 0) as s from llm_usage "
                        "where user_id = %s and created_at >= date_trunc('month', now())",
                        (user_id,)).fetchone()
    return float(row["s"])


# --- audit -------------------------------------------------------------------------------

def _audit(c, user_id: str, actor: str, action: str, entity: str, entity_id: str | None,
           before: Any, after: Any) -> None:
    c.execute("insert into audit_log (user_id, actor, action, entity, entity_id, before, after) "
              "values (%s, %s, %s, %s, %s, %s, %s)",
              (user_id, actor, action, entity, entity_id,
               Jsonb(json.loads(json.dumps(before, default=str))) if before is not None else None,
               Jsonb(json.loads(json.dumps(after, default=str))) if after is not None else None))
