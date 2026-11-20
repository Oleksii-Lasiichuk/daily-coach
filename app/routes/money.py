"""Money page (/money), Monobank connect/disconnect, category corrections, receipts, and the
Monobank webhook (the one public route of B4: its secret token is in the URL)."""

import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app import agent, i18n, llm, money, money_stats, mono, spend_rules, store
from app.auth import current_user
from app.pipeline import receipt
from app.web import shell, templates, ui

router = APIRouter(dependencies=[Depends(current_user)])
hooks = APIRouter()  # public: Monobank calls it; the token in the path is the check
MAX_IMAGE_BYTES = 8_000_000
CAT_NAMES = {"groceries": "Groceries", "eating_out": "Eating out", "delivery": "Delivery",
             "coffee": "Coffee", "sports_nutrition": "Sports nutrition",
             "race_entries": "Race entries", "sport_gear": "Sport gear",
             "gym_classes": "Gym and classes", "medical": "Medical", "pharmacy": "Pharmacy",
             "transport": "Transport", "taxi": "Taxi", "fuel": "Fuel", "home_bills": "Home bills",
             "subscriptions": "Subscriptions", "shopping": "Shopping",
             "entertainment": "Entertainment", "travel": "Travel", "transfers": "Transfers",
             "cash": "Cash", "income": "Income", "other": "Other"}
templates.env.globals["cat_name"] = lambda c: CAT_NAMES.get(c or "other", "Other")


def _today(user: store.User) -> date:
    return datetime.now(ZoneInfo(user.time_zone)).date()


def page_context(user: store.User, month: str = "") -> dict:
    today = _today(user)
    try:
        m = date.fromisoformat(month + "-01") if month else today.replace(day=1)
    except ValueError:
        m = today.replace(day=1)
    m = min(m, today.replace(day=1))
    v = money_stats.month_view(user, m, today)
    days: dict[date, list] = {}
    tz = ZoneInfo(user.time_zone)
    for r in v["rows"]:
        days.setdefault(r["at"].astimezone(tz).date(), []).append(r)
    top = max((c["uah"] for c in v["categories"]), default=0) or 1
    prev = (m - timedelta(days=1)).replace(day=1)
    nxt = (m + timedelta(days=32)).replace(day=1)
    return {"v": v, "days": days, "bar_max": max(top, max((c["avg_3m"] or 0
                                                         for c in v["categories"]), default=0)),
            "prev": prev.strftime("%Y-%m"),
            "next": nxt.strftime("%Y-%m") if nxt <= today.replace(day=1) else None,
            "categories": spend_rules.CATEGORIES, "status": money.status(user.id),
            "secret": store.get_secret(user.id, "monobank"), "months": mono.MONTHS}


@router.get("/money", response_class=HTMLResponse)
def money_page(request: Request, month: str = "", user: store.User = Depends(current_user)):
    return templates.TemplateResponse(request, "money.html",
                                      shell(user, "/money", **page_context(user, month)))


@router.get("/money/settings", response_class=HTMLResponse)
def money_settings(request: Request, user: store.User = Depends(current_user)):
    return templates.TemplateResponse(request, "partials/money_status.html", {
        **ui(user), "status": money.status(user.id),
        "secret": store.get_secret(user.id, "monobank"), "months": mono.MONTHS})


@router.get("/setup/money/sheet", response_class=HTMLResponse)
def money_sheet(request: Request, user: store.User = Depends(current_user)):
    return templates.TemplateResponse(request, "partials/setup_money.html",
                                      {**ui(user), "months": mono.MONTHS})


def _sync_soon(user_id: str) -> None:
    """Right after connect: the first statement window in the background (not in the request)."""
    def run():
        try:
            mono.sync_step(user_id)
            money.categorise_pending(user_id)
        except Exception:  # the tick retries
            pass
    threading.Thread(target=run, daemon=True).start()


@router.post("/money/mono")
def connect(token: str = Form(""), months: int = Form(6),
            user: store.User = Depends(current_user)):
    token = token.strip()
    if not token or len(token) > 200:
        return RedirectResponse("/money?error=token", status_code=303)
    try:
        mono.connect(user.id, token, months)
    except mono.BadToken:
        return RedirectResponse("/money?error=token", status_code=303)
    except mono.RateLimited:
        return RedirectResponse("/money?error=wait", status_code=303)
    except mono.MonoError:
        return RedirectResponse("/money?error=mono", status_code=303)
    _sync_soon(user.id)
    return RedirectResponse("/money?connected=1", status_code=303)


@router.post("/money/mono/delete")
def disconnect(keep: str = Form("keep"), user: store.User = Depends(current_user)):
    mono.disconnect(user.id, delete_data=keep == "delete")
    return RedirectResponse("/money", status_code=303)


@router.post("/money/delete")
def delete_all(user: store.User = Depends(current_user)):
    money.delete_all(user.id)
    return RedirectResponse("/money", status_code=303)


@router.post("/money/tx/{tx_id}/category", response_class=HTMLResponse)
def set_category(tx_id: int, category: str = Form(""), always: str = Form(""),
                 user: store.User = Depends(current_user)):
    if not money.set_category(user.id, tx_id, category, bool(always)):
        return Response("Not found", status_code=404)
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.post("/money/receipt", response_class=HTMLResponse)
def add_receipt(request: Request, image: UploadFile | None = None,
                user: store.User = Depends(current_user)):
    raw = image.file.read(MAX_IMAGE_BYTES + 1) if image else b""
    lang = store.user_lang(user.id)
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        return HTMLResponse(f'<p class="notice error small">'
                            f'{i18n.t("Choose a photo of the receipt (up to 8 MB).", lang)}</p>')
    try:
        with llm.trace("read-receipt", input="(receipt photo)", user_id=user.id,
                       tags=["money"]):
            rc = receipt.extract(raw, user.id)
        llm.langfuse.flush()
    except llm.LLMError as e:
        return HTMLResponse(f'<p class="notice error small">{i18n.t("Couldn’t read the receipt.", lang)} '
                            f'{e if isinstance(e, llm.BudgetExceeded) else ""}</p>')
    if not rc.total or not rc.lines:
        return HTMLResponse(f'<p class="notice error small">'
                            f'{i18n.t("This doesn’t look like a receipt. Try a sharper photo.", lang)}</p>')
    tz = ZoneInfo(user.time_zone)
    saved = money.save_receipt(user.id, rc, datetime.now(tz))
    return templates.TemplateResponse(request, "partials/receipt_result.html",
                                      {**ui(user), "r": saved})


@router.post("/money/receipt/{receipt_id}/meal", response_class=HTMLResponse)
def receipt_meal(receipt_id: int, user: store.User = Depends(current_user)):
    """One tap: log the receipt's food lines as a meal through the coach's logger (C2/C3)."""
    text = money.receipt_food_text(user.id, receipt_id)
    lang = store.user_lang(user.id)
    if not text:
        return Response("Not found", status_code=404)
    try:
        with llm.trace("log-receipt-meal", input=text, user_id=user.id, tags=["money"]):
            agent.Turn(user, None, False).log_entries("I ate: " + text)
        llm.langfuse.flush()
    except llm.LLMError:
        return HTMLResponse(f'<span class="small">{i18n.t("Couldn’t log it. Tell the coach in the chat.", lang)}</span>')
    return HTMLResponse(f'<span class="small">{i18n.t("Logged as a meal", lang)}</span>')


@router.post("/money/receipt/{receipt_id}/delete")
def receipt_delete(receipt_id: int, user: store.User = Depends(current_user)):
    if not money.delete_receipt(user.id, receipt_id):
        return Response("Not found", status_code=404)
    return RedirectResponse("/money", status_code=303)


# --- webhook (public) --------------------------------------------------------------------

@hooks.get("/hooks/mono/{hook_token}")
def hook_check(hook_token: str):
    """Monobank checks the URL with a GET and needs exactly 200."""
    if not mono.webhook_user(hook_token):
        return Response(status_code=404)
    return Response(status_code=200)


@hooks.post("/hooks/mono/{hook_token}")
async def hook(hook_token: str, request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = {}
    from starlette.concurrency import run_in_threadpool
    ok = await run_in_threadpool(mono.handle_webhook, hook_token,
                                 body if isinstance(body, dict) else {})
    if ok is None:
        return Response(status_code=404)
    return JSONResponse({"ok": ok})  # 200 even when ignored, so Monobank keeps the webhook
