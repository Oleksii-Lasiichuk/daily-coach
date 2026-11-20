"""End-to-end agent eval: a real chat turn on the synthetic Demo Athlete, checked in the database.

Each case sends one message through `agent.run` (safety gate + coach + tools, real models) and
checks what was written: log kinds and dates, items, reminders, proposals, the red flag, and
that nothing reached the watch (no proposal is applied without the user pressing Send).

Needs ENV=dev (the demo athlete and its fake intervals.icu exist only there). It re-seeds the
demo athlete first. Run: uv run python -m evals.run_e2e
"""

from datetime import datetime

from app import agent, demo, store
from app.db import connection
from evals.common import DATA, load, save


def state(uid: str) -> dict:
    with connection() as c:
        q = lambda sql: c.execute(sql, (uid,)).fetchone()["m"] or 0  # noqa: E731
        return {"log": q("select max(id) as m from logs where user_id = %s"),
                "fact": q("select max(id) as m from facts where user_id = %s"),
                "rem": q("select max(id) as m from reminders where user_id = %s"),
                "prop": q("select max(id) as m from proposals where user_id = %s"),
                "undone": c.execute("select count(*) as m from agent_actions where user_id = %s "
                                    "and tool = 'log_entries' and undone",
                                    (uid,)).fetchone()["m"]}


def new_rows(uid: str, before: dict) -> dict:
    with connection() as c:
        logs = c.execute("select kind, day, data from logs where user_id = %s and id > %s",
                         (uid, before["log"])).fetchall()
        facts = c.execute("select category from facts where user_id = %s and id > %s",
                          (uid, before["fact"])).fetchall()
        rems = c.execute("select id from reminders where user_id = %s and id > %s",
                         (uid, before["rem"])).fetchall()
        props = c.execute("select status from proposals where user_id = %s and id > %s",
                          (uid, before["prop"])).fetchall()
        undone = c.execute("select count(*) as m from agent_actions where user_id = %s and "
                           "tool = 'log_entries' and undone", (uid,)).fetchone()["m"]
    return {"logs": logs, "facts": [f["category"] for f in facts], "reminders": len(rems),
            "proposals": [p["status"] for p in props], "replaced": undone > before["undone"]}


def check(case: dict, out: dict, rows: dict, today) -> dict[str, bool]:
    e, got = case["expect"], {}
    kinds_days = {(lg["kind"], (lg["day"] - today).days) for lg in rows["logs"]}
    for kind, offset in e.get("logs", []):
        got[f"log {kind} day{offset:+d}"] = (kind, offset) in kinds_days
    for kind in e.get("no_logs", []):
        got[f"no {kind} log"] = not any(lg["kind"] == kind for lg in rows["logs"])
    if "pain_score" in e:
        got["pain score"] = any(lg["data"].get("pain_score") == e["pain_score"]
                                for lg in rows["logs"])
    for cat in e.get("facts", []):
        got[f"item {cat}"] = cat in rows["facts"]
    if "reminder" in e:
        got["reminder"] = rows["reminders"] > 0
    if "proposal" in e:
        got["proposal" if e["proposal"] else "no proposal"] = bool(rows["proposals"]) == \
            e["proposal"]
    if e.get("no_writes"):
        got["no writes"] = not (rows["logs"] or rows["facts"] or rows["reminders"]
                                or rows["proposals"])
    if "replaced" in e:
        got["replaced last log"] = rows["replaced"] == e["replaced"]
    if e.get("no_question"):  # logged at once, not "Right?"
        got["no confirmation asked"] = bool(rows["logs"])
    if "red_flag" in e:
        got["red flag"] = out["red_flag"] == e["red_flag"]
    if "reply_any" in e:
        got["reply mentions"] = any(w.lower() in (out["reply"] or "").lower()
                                    for w in e["reply_any"])
    # always: nothing is applied to the watch without the user's tap
    got["nothing sent to watch"] = "applied" not in rows["proposals"] and not demo._calendar
    return got


def main():
    uid = demo.seed()
    user = store.get_user(uid)
    today = datetime.now(demo.TZ).date()
    results, n_ok, checks_ok, checks_n = [], 0, 0, 0
    for case in load("e2e_agent.jsonl"):
        before = state(uid)
        images = [(DATA / case["image"]).read_bytes()] if case.get("image") else []
        mid = store.add_message(uid, "user", case["text"] or "(photo)") if case.get("chat") \
            else None
        try:
            out = agent.run(user, case["text"], images, message_id=mid)
            if case.get("chat"):  # kept in the chat history, as the app does, for the next case
                aid = store.add_message(uid, "assistant", out["reply"])
                agent.save_actions(uid, aid, out["actions"])
        except Exception as ex:  # one failure is a failed case, not a stopped run
            out = {"reply": "", "red_flag": None, "error": f"{type(ex).__name__}: {ex}"}
        rows = new_rows(uid, before)
        got = check(case, out, rows, today)
        ok = all(got.values())
        n_ok += ok
        checks_ok += sum(got.values())
        checks_n += len(got)
        results.append({"id": case["id"], "ok": ok, "checks": got, "reply": out["reply"][:300],
                        "logs": sorted(f"{lg['kind']} {lg['day']}" for lg in rows["logs"]),
                        "facts": rows["facts"], "proposals": rows["proposals"],
                        **({"error": out["error"]} if "error" in out else {})})
        print(("PASS " if ok else "FAIL ") + case["id"], {k: v for k, v in got.items() if not v})
    n = len(results)
    metrics = {"n": n, "case_pass_rate": round(n_ok / n, 3),
               "check_accuracy": round(checks_ok / checks_n, 3), "checks": checks_n,
               "nothing_sent_without_tap": all(r["checks"]["nothing sent to watch"]
                                               for r in results),
               "run_date": str(today)}
    save("e2e_agent", metrics, [r for r in results if not r["ok"]], {"cases": results})


if __name__ == "__main__":
    main()
