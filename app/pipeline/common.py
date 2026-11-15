"""Shared helpers for pipeline components: prompt loading and the context block."""

import json
from datetime import date, datetime
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


def clock(now: datetime) -> str:
    return f"Local now: {now:%Y-%m-%d %A %H:%M}"


def to_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=_default)


def _default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)
