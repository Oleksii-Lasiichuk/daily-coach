"""B2 calendar routes: connect an ICS link (setup sheet and Settings), the titles toggle, remove.
The link is checked once here (fetch + parse) because the person just pressed Connect; after that
syncs run only in the tick, plus one background sync right after setup."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app import calendar, store
from app.auth import current_user
from app.web import templates, ui

router = APIRouter(dependencies=[Depends(current_user)])


def calendar_context(user: store.User, **extra) -> dict:
    f = calendar.feed(user.id)
    ago = None
    if f and f["last_ok_at"]:
        ago = int((datetime.now(UTC) - f["last_ok_at"]).total_seconds() // 60)
    return {**ui(user), "cal_secret": store.get_secret(user.id, "ical"), "cal_feed": f,
            "cal_ago": ago, **extra}


def _partial(request: Request, user: store.User, trigger: bool = False, **extra):
    return templates.TemplateResponse(request, "partials/calendar.html",
                                      calendar_context(user, **extra),
                                      headers={"HX-Trigger": "calendarChanged"} if trigger else {})


@router.get("/setup/calendar/sheet", response_class=HTMLResponse)
def calendar_sheet(request: Request, user: store.User = Depends(current_user)):
    return templates.TemplateResponse(request, "partials/setup_calendar.html",
                                      calendar_context(user))


@router.post("/calendar", response_class=HTMLResponse)
def connect(request: Request, url: str = Form(""), user: store.User = Depends(current_user)):
    tz = ZoneInfo(user.time_zone)
    try:
        start, end = calendar.window(datetime.now(tz))
        found = calendar.parse(calendar.fetch(url), tz, start, end)
    except calendar.CalendarError as e:
        return _partial(request, user, error=str(e))
    calendar.save_url(user.id, url)
    calendar.sync_soon(user.id)
    return _partial(request, user, trigger=True, found=sum(b.busy for b in found))


@router.post("/calendar/titles", response_class=HTMLResponse)
def titles(request: Request, on: str = Form(""), user: store.User = Depends(current_user)):
    calendar.set_titles(user.id, on == "1")
    return _partial(request, user)


@router.delete("/calendar", response_class=HTMLResponse)
def remove(request: Request, user: store.User = Depends(current_user)):
    calendar.remove(user.id)
    return _partial(request, user, trigger=True)
