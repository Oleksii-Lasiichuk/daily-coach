"""Shared Jinja setup: templates, filters (local time, light Markdown) and the shell context."""

import html
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup

from app import i18n
from app.config import get_settings

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["firebase"] = {
    "apiKey": get_settings().firebase_web_api_key,
    "authDomain": get_settings().firebase_auth_domain,
    "projectId": get_settings().firebase_project_id,
    "appId": get_settings().firebase_app_id,
}


def local_time(value: datetime, tz: str, fmt: str = "%H:%M") -> str:
    return value.astimezone(ZoneInfo(tz)).strftime(fmt)


def md(text: str) -> Markup:
    """Light Markdown for coach replies: paragraphs, **bold**, - lists, 1. lists. Escaped first."""
    out, items, kind = [], [], None

    def flush():
        nonlocal items, kind
        if items:
            out.append(f"<{kind}>" + "".join(f"<li>{i}</li>" for i in items) + f"</{kind}>")
        items, kind = [], None

    for block in re.split(r"\n\s*\n", html.escape(text or "").strip()):
        lines = block.split("\n")
        for line in lines:
            line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line.strip())
            m_ul, m_ol = re.match(r"^[-*•]\s+(.*)", line), re.match(r"^\d+[.)]\s+(.*)", line)
            if m_ul or m_ol:
                k = "ul" if m_ul else "ol"
                if kind and kind != k:
                    flush()
                kind = k
                items.append((m_ul or m_ol).group(1))
            else:
                flush()
                if line:
                    out.append(f"<p>{line}</p>")
        flush()
    return Markup("".join(out))


# One name per day type, everywhere.
DAY_NAMES = {"recover": "Recovery", "easy": "Easy", "normal": "Normal", "push": "Push"}


@pass_context
def _t(ctx, text: str) -> str:
    return i18n.t(text, ctx.get("lang", "en"))


@pass_context
def _fdate(ctx, d, style: str = "day") -> str:
    return i18n.fdate(d, style, ctx.get("lang", "en")) if d else ""


templates.env.filters["local_time"] = local_time
templates.env.filters["md"] = md
templates.env.filters["fdate"] = _fdate
templates.env.filters["prevday"] = lambda d: (d - timedelta(days=1)).isoformat()
templates.env.globals["_"] = _t
templates.env.globals["DAY_NAMES"] = DAY_NAMES


def _fuel(workout: dict, user_id: str):
    from app import nutrition_stats
    return nutrition_stats.session_fuel(workout, nutrition_stats.weight_of(user_id))


templates.env.globals["session_fuel"] = _fuel


def hr_zones(user_id: str, sport: str) -> dict[int, tuple[int | None, int]]:
    """{zone: (low bpm or None, high bpm)} for the sport, from the intervals.icu profile."""
    from app import store
    settings = (store.get_profile(user_id).get("sport_settings") or {}).get("value") or {}
    entry = next((v for v in settings.values() if sport in v.get("types", [])), None)
    entry = entry or next(iter(settings.values()), {})
    out = {}
    for k, v in (entry.get("hr_zones_bpm") or {}).items():
        try:
            if v.startswith("up to"):
                out[int(k[1:])] = (None, int(v.split()[-1]))
            else:
                lo, hi = v.split("-")
                out[int(k[1:])] = (int(lo), int(hi))
        except (ValueError, IndexError):
            continue
    return out


def zone_bpm(zones: dict, lo: int | None, hi: int | None) -> str:
    lo, hi = lo or hi, hi or lo
    if not lo or lo not in zones or hi not in zones:
        return ""
    low, high = zones[lo][0], zones[hi][1]
    return f"{low}–{high}" if low else f"<{high}"


def workout_profile(w: dict) -> list[dict]:
    """Segments for the workout bar: width = share of time, height = zone."""
    segs = []
    for b in w.get("blocks", []):
        for _ in range(b.get("repeats", 1)):
            for s in b.get("steps", []):
                mins = s.get("duration_min") or (s.get("distance_m") or 0) / 1000 * 6
                segs.append({"min": mins, "z": s.get("zone_high") or s.get("zone_low") or 1,
                             "kind": s.get("kind")})
    total = sum(x["min"] for x in segs) or 1
    for x in segs:
        x["pct"] = round(100 * x["min"] / total, 2)
    return segs


templates.env.globals.update(hr_zones=hr_zones, zone_bpm=zone_bpm,
                             workout_profile=workout_profile)


def ui(user) -> dict:
    """What any template needs to render in the user's language."""
    from app import store
    return {"user": user, "lang": store.user_lang(user.id) if user else "en"}


def is_admin(user) -> bool:
    return bool(user) and user.email.lower() in get_settings().admin_email_set


def shell(user, active: str, **extra) -> dict:
    """Context every app page needs: user, language, active nav item, unreviewed-facts count."""
    from app import sources
    return {**ui(user), "active": active, "is_admin": is_admin(user),
            "inbox_count": len(sources.proposed_facts(user.id)), **extra}
