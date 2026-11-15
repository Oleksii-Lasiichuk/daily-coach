"""Shared Jinja setup: templates, filters (local time, light Markdown) and the shell context."""

import html
import re
from datetime import datetime
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
templates.env.globals["_"] = _t
templates.env.globals["DAY_NAMES"] = DAY_NAMES


def _fuel(workout: dict, user_id: str):
    from app import nutrition_stats
    return nutrition_stats.session_fuel(workout, nutrition_stats.weight_of(user_id))


templates.env.globals["session_fuel"] = _fuel


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
