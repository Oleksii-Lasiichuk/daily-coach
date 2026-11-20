"""Push subscription (signed in), the service worker file, and the cron tick (secret header)."""

import hmac
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from app import push, store
from app.auth import current_user
from app.config import get_settings
from app.crypto import derived_key
from app.db import connection

router = APIRouter()

SW = """self.addEventListener("push", (e) => {
  const d = e.data ? e.data.json() : {};
  e.waitUntil(self.registration.showNotification(d.title || "Daily Coach", {
    body: d.body || "", icon: "/static/icon.svg", badge: "/static/icon.svg",
    actions: d.actions || [], data: { url: d.url || "/", q: d.q } }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const q = e.notification.data.q;
  if (e.action && q) {  // a one-tap answer: log it without opening the app
    e.waitUntil(fetch("/push/answer", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ q, a: e.action }) })
      .then((r) => self.registration.showNotification(r.ok ? "Saved" : "Couldn't save",
        { body: r.ok ? "Added to today's log." : "Open the app and tell the coach.",
          icon: "/static/icon.svg" })));
    return;
  }
  e.waitUntil(clients.matchAll({ type: "window" }).then((list) => {
    for (const c of list) {
      if ("focus" in c) { c.navigate(e.notification.data.url); return c.focus(); }
    }
    return clients.openWindow(e.notification.data.url);
  }));
});
self.addEventListener("fetch", () => {});"""


@router.get("/sw.js")
def service_worker():
    return Response(SW, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@router.post("/push/subscribe")
async def subscribe(request: Request, user: store.User = Depends(current_user)):
    sub = await request.json()
    keys = sub.get("keys") or {}
    if not sub.get("endpoint", "").startswith("https://") or not keys.get("p256dh"):
        return JSONResponse({"error": "bad subscription"}, status_code=400)
    with connection() as c:
        c.execute("insert into push_subscriptions (user_id, endpoint, p256dh, auth) values "
                  "(%s, %s, %s, %s) on conflict (endpoint) do update "
                  "set user_id = excluded.user_id",
                  (user.id, sub["endpoint"], keys["p256dh"], keys.get("auth", "")))
    push.send(user.id, "Notifications are on", "You'll get your plan, meal and evening reminders.")
    return {"ok": True}


@router.post("/push/answer")
async def push_answer(request: Request, user: store.User = Depends(current_user)):
    body = await request.json()
    ok = push.answer(user.id, str(body.get("q", "")), str(body.get("a", "")))
    return JSONResponse({"ok": ok}, status_code=200 if ok else 400)


def cron_secret() -> str:
    return get_settings().cron_secret or derived_key("cron")


@router.post("/cron/hold/{turn_id}")
def hold_cpu(request: Request, turn_id: int):
    """Stays open while a chat turn runs (at most 3 min). Called by the instance itself (see
    pages._keep_cpu): with request-based billing Cloud Run gives CPU only during requests, so
    without it a reply would stop when the person leaves the app. Returns no personal data."""
    given = request.headers.get("x-cron-secret", "")
    if not cron_secret() or not hmac.compare_digest(given, cron_secret()):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    deadline = time.monotonic() + 180
    status = "running"
    while status == "running" and time.monotonic() < deadline:
        time.sleep(1)
        with connection() as c:
            r = c.execute("select status from chat_turns where id = %s", (turn_id,)).fetchone()
        status = r["status"] if r else "missing"
    return {"status": status}


@router.post("/cron/tick")
def cron_tick(request: Request):
    given = request.headers.get("x-cron-secret", "")
    if not hmac.compare_digest(given, cron_secret()):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return push.tick()
