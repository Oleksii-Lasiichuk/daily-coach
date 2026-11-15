"""Memory: what the coach remembers that isn't training or health. Instructions (free text),
food and training preferences (with the diet type), life and notes, and your files with the
inbox of facts found in them.

Items have one home each: goals, races and gear on Training; conditions, injuries, medication
and lab results on Health; the rest here. The item routes below serve all three pages."""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from psycopg.types.json import Jsonb

from app import llm, sources, store, tidy
from app.auth import current_user
from app.db import connection
from app.web import shell, templates

router = APIRouter(dependencies=[Depends(current_user)])
HOMES = {"goal": "/training", "race": "/training", "gear": "/training", "injury": "/health",
         "health": "/health", "medication": "/health", "lab": "/health",
         "preference": "/memory", "life": "/memory", "note": "/memory"}
CATEGORIES = list(HOMES)
DIETS = ["Omnivore", "Vegetarian", "Vegan", "Pescatarian", "Other"]
DETAIL_KEYS = ("date", "distance", "target_time", "target_pace", "km_start", "retire_km",
               "type", "value", "unit")
GROUPS = {"/training": ["race", "goal", "gear"], "/health": ["injury", "health", "medication",
                                                               "lab"],
          "/memory": ["preference", "life", "note"]}


def _item(user_id: str, fid: int) -> dict | None:
    with connection() as c:
        return c.execute(
            """select f.*, s.filename, m.created_at as said_at from facts f
               left join sources s on s.id = f.source_id
               left join chat_messages m on m.id = f.message_id
               where f.user_id = %s and f.id = %s""", (user_id, fid)).fetchone()


@router.get("/items/new/sheet", response_class=HTMLResponse)
def new_item_sheet(request: Request, home: str = "/memory", category: str = "",
                   user: store.User = Depends(current_user)):
    cats = GROUPS.get(home, GROUPS["/memory"])
    f = {"id": None, "category": category if category in cats else cats[0], "text": "",
         "term": "long", "until": None, "details": {}, "status": "active", "source": "user"}
    return templates.TemplateResponse(request, "partials/item_sheet.html", shell(
        user, home, f=f, cats=cats, next=home))


@router.get("/items/{fid}/sheet", response_class=HTMLResponse)
def item_sheet(request: Request, fid: int, user: store.User = Depends(current_user)):
    f = _item(user.id, fid)
    if not f:
        return HTMLResponse("", status_code=404)
    home = HOMES[f["category"]]
    return templates.TemplateResponse(request, "partials/item_sheet.html", shell(
        user, home, f=f, cats=GROUPS[home], next=home))


@router.post("/items/tidy", response_class=HTMLResponse)
def tidy_sheet(request: Request, next: str = Form("/memory"),
               user: store.User = Depends(current_user)):
    error = None
    try:
        groups = tidy.find_groups(user.id)
    except llm.LLMError:
        groups, error = [], "Couldn't check right now. Try again."
    return templates.TemplateResponse(request, "partials/tidy_sheet.html", shell(
        user, next, groups=groups, error=error, next=next))


@router.post("/items/tidy/apply")
async def tidy_apply(request: Request, user: store.User = Depends(current_user)):
    form = await request.form()
    for raw in form.getlist("group"):
        keep, _, dups = str(raw).partition(":")
        try:
            ids = [int(x) for x in dups.split(",") if x]
            text = str(form.get(f"text_{keep}", "")).strip()
            if text:
                tidy.merge(user.id, int(keep), ids, text)
        except ValueError:
            continue
    return _back(user.id, None, str(form.get("next", "")))


@router.get("/knowledge")
def old_knowledge():
    return RedirectResponse("/memory", status_code=301)


@router.get("/memory", response_class=HTMLResponse)
def memory(request: Request, user: store.User = Depends(current_user)):
    facts = store.list_facts(user.id, status=None)
    prof = store.get_profile(user.id)
    return templates.TemplateResponse(request, "memory.html", shell(
        user, "/memory",
        known=[f for f in facts if f["category"] in ("preference", "life", "note")],
        instructions=(prof.get("instructions") or {}).get("value", ""),
        diet=(prof.get("diet") or {}).get("value", ""), diets=DIETS,
        files=sources.list_sources(user.id), proposed=sources.proposed_facts(user.id),
        next_url="/memory#files"))


@router.post("/memory/instructions")
def save_instructions(text: str = Form(""), user: store.User = Depends(current_user)):
    text = text.strip()[:4000]
    if text:
        store.set_profile_field(user.id, "instructions", text, "user", actor="user")
    else:
        store.delete_profile_field(user.id, "instructions")
    return RedirectResponse("/memory", status_code=303)


@router.post("/memory/diet")
def save_diet(diet: str = Form(""), user: store.User = Depends(current_user)):
    if diet in DIETS:
        store.set_profile_field(user.id, "diet", diet, "user", actor="user")
    return RedirectResponse("/memory#prefs", status_code=303)


def _back(user_id: str, fid: int | None, next: str) -> RedirectResponse:
    if next.startswith("/") and not next.startswith("//"):
        return RedirectResponse(next, status_code=303)
    return RedirectResponse("/memory", status_code=303)


def _save_extra(user_id: str, fid: int, term: str, until: str, form: dict) -> None:
    try:
        u = date.fromisoformat(until) if until else None
    except ValueError:
        u = None
    with connection() as c:
        old = c.execute("select details from facts where user_id = %s and id = %s",
                        (user_id, fid)).fetchone()
        if not old:
            return
        details = dict(old["details"] or {})
        for k in DETAIL_KEYS:
            if k in form:
                v = str(form[k]).strip()[:40]
                if v:
                    details[k] = v
                else:
                    details.pop(k, None)
        c.execute("update facts set term = %s, until = %s, details = %s where user_id = %s and "
                  "id = %s", (term if term in ("long", "current") else "long", u, Jsonb(details),
                              user_id, fid))


@router.post("/items")
async def add_item(request: Request, user: store.User = Depends(current_user)):
    form = dict(await request.form())
    category, text = str(form.get("category", "")), str(form.get("text", "")).strip()
    if category in CATEGORIES and text:
        fid = store.add_fact(user.id, category, text[:300], "user")
        _save_extra(user.id, fid, str(form.get("term", "long")), str(form.get("until", "")),
                    form)
    return _back(user.id, None, str(form.get("next", "")))


@router.post("/items/{fid}")
async def edit_item(request: Request, fid: int, user: store.User = Depends(current_user)):
    form = dict(await request.form())
    text = str(form.get("text", "")).strip()
    if text:
        store.update_fact(user.id, fid, text=text[:300])
        _save_extra(user.id, fid, str(form.get("term", "long")), str(form.get("until", "")),
                    form)
    return _back(user.id, fid, str(form.get("next", "")))


@router.post("/items/{fid}/end")
def end_item(fid: int, next: str = Form(""), user: store.User = Depends(current_user)):
    store.update_fact(user.id, fid, status="resolved")
    return _back(user.id, fid, next)


@router.post("/items/{fid}/restore")
def restore_item(fid: int, next: str = Form(""), user: store.User = Depends(current_user)):
    store.update_fact(user.id, fid, status="active")
    return _back(user.id, fid, next)


@router.post("/items/{fid}/delete")
def delete_item(fid: int, next: str = Form(""), user: store.User = Depends(current_user)):
    store.delete_fact(user.id, fid)
    return _back(user.id, fid, next)


def set_term(user_id: str, fid: int, term: str, until: str) -> None:
    _save_extra(user_id, fid, term, until, {})


@router.post("/reminders/{rid}/delete", response_class=HTMLResponse)
def delete_reminder(rid: int, user: store.User = Depends(current_user)):
    with connection() as c:
        c.execute("update reminders set active = false where user_id = %s and id = %s",
                  (user.id, rid))
    return HTMLResponse("")
