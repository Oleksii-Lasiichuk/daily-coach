"""UI language: English (default) or Ukrainian. Only the app's own words are translated; chat
messages and the athlete's data stay as they are. The dictionary is keyed by the English text
(app/i18n_uk.json); a missing entry falls back to English."""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

LANGS = {"en": "English", "uk": "Українська"}
_UK_DAYS = ["понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя"]
_UK_DAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
_UK_MONTHS = ["січень", "лютий", "березень", "квітень", "травень", "червень", "липень",
              "серпень", "вересень", "жовтень", "листопад", "грудень"]
_UK_MONTHS_GEN = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня",
                  "серпня", "вересня", "жовтня", "листопада", "грудня"]


@lru_cache
def _uk() -> dict[str, str]:
    return json.loads((Path(__file__).parent / "i18n_uk.json").read_text(encoding="utf-8"))


def t(text: str, lang: str) -> str:
    return _uk().get(text, text) if lang == "uk" else text


def fdate(d: date, style: str, lang: str) -> str:
    """Styles: day ("Sunday 15 November"), full (+ year), short ("Sun 15"), dm ("15 Nov"),
    month ("November 2026"), wd ("Sun")."""
    if lang != "uk":
        return d.strftime({"day": "%A %-d %B", "full": "%A, %-d %B %Y", "short": "%a %-d",
                           "dm": "%-d %b", "month": "%B %Y", "wd": "%a"}[style])
    wd, m = d.weekday(), d.month - 1
    return {"day": f"{_UK_DAYS[wd].capitalize()}, {d.day} {_UK_MONTHS_GEN[m]}",
            "full": f"{_UK_DAYS[wd].capitalize()}, {d.day} {_UK_MONTHS_GEN[m]} {d.year}",
            "short": f"{_UK_DAYS_SHORT[wd]} {d.day}", "dm": f"{d.day} {_UK_MONTHS_GEN[m][:4]}.",
            "month": f"{_UK_MONTHS[m].capitalize()} {d.year}", "wd": _UK_DAYS_SHORT[wd]}[style]
