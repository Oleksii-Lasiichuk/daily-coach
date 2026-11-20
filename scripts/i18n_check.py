"""Finds UI text without a Ukrainian translation in app/i18n_uk.json.

Collects:
- `_("…")` in templates, and string literals in `{% for %}` / `{% set %}` lists of templates
  (labels shown through `_(var)`);
- `i18n.t("…", …)` / `t("…", …)` and `_t("…")` in Python, messages of IntervalsError and
  SourceError, and `error = "…"` in routes (templates show these through `_(error)`);
- the label constants in dynamic_keys() (shown through `_(var)` from Python).

Run: uv run python scripts/i18n_check.py   (exit 1 and a list when something is missing).
`--add` writes the missing keys to app/i18n_uk.json with an empty value, ready to fill.
"""

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
DICT = APP / "i18n_uk.json"

TEMPLATE_CALL = re.compile(r"""_\(\s*(["'])((?:\\.|(?!\1).)+)\1\s*\)""", re.S)
TAG = re.compile(r"{%-?\s*(?:for|set)\b(.*?)-?%}", re.S)
LITERAL = re.compile(r"""(["'])((?:\\.|(?!\1).)*)\1""")
# A list literal in a template tag holds code values too (paths, icon names, keys); only text
# that reads like a label is a key: starts with a capital letter, no slash, not ALL CAPS.
LABEL = re.compile(r"^[A-Z][^/<>{}]*$")
NOT_TEXT = {"HRV", "UTC", "VO2max", "OK", "API"}


def template_keys() -> set[str]:
    keys = set()
    for path in (APP / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        keys |= {m.group(2).replace("\\'", "'").replace('\\"', '"')
                 for m in TEMPLATE_CALL.finditer(text)}
        for tag in TAG.finditer(text):
            for m in LITERAL.finditer(tag.group(1)):
                s = m.group(2)
                if LABEL.match(s) and s not in NOT_TEXT and not s.isupper() and len(s) > 1:
                    keys.add(s)
    return keys


def python_keys() -> set[str]:
    keys = set()
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            first = node.args[0]
            if name in ("t", "_t", "IntervalsError", "SourceError") and \
                    isinstance(first, ast.Constant) and isinstance(first.value, str):
                keys.add(first.value)
            if name in ("send", "notify_admins"):  # push titles and bodies
                pos = node.args[1:3] if name == "send" else node.args[0:2]
                keys |= {a.value for a in pos
                         if isinstance(a, ast.Constant) and isinstance(a.value, str)}
        for node in ast.walk(tree):  # error = "…" / groups, error = [], "…"
            if isinstance(node, ast.Assign) and any(
                    getattr(t, "id", "") == "error" or any(getattr(e, "id", "") == "error"
                                                          for e in getattr(t, "elts", []))
                    for t in node.targets):
                vals = node.value.elts if isinstance(node.value, ast.Tuple) else [node.value]
                keys |= {v.value for v in vals if isinstance(v, ast.Constant)
                         and isinstance(v.value, str)}
    return keys


def dynamic_keys() -> set[str]:
    """Labels kept in Python and shown with `_(var)` in a template."""
    from app.routes import welcome
    keys = set()
    for _key, _icon, label, sub in welcome.TRACKS:
        keys |= {label, sub}
    keys |= set(welcome.NAMES.values())
    from app import push
    for title, body in push.NUDGE_TEXT.values():
        keys |= {title, body}
    for _q, buttons in push.QUESTIONS.values():
        keys |= {b["title"] for b in buttons}
    # item labels on the coach's action lines (agent.save_item)
    keys |= {"Gear", "Race", "Goal", "Medication", "Injury", "Health", "Preference", "Life",
             "Note", "Lab"}
    keys |= {"sent to watch", "suggested"}  # history.day_chips session status
    from app import nutrition_stats
    keys |= {p for p, *_ in nutrition_stats.MEAL_PARTS} | {"Snacks", "Drinks"}
    keys |= set(nutrition_stats.UNITS.values()) - {"kcal"} | {"kcal"}
    return keys


def missing() -> list[str]:
    known = json.loads(DICT.read_text(encoding="utf-8"))
    keys = template_keys() | python_keys() | dynamic_keys()
    return sorted(k for k in keys if not known.get(k))


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    gaps = missing()
    if "--add" in sys.argv and gaps:
        known = json.loads(DICT.read_text(encoding="utf-8"))
        known.update({k: "" for k in gaps if k not in known})
        DICT.write_text(json.dumps(dict(sorted(known.items())), ensure_ascii=False, indent=0)
                        + "\n", encoding="utf-8")
    for k in gaps:
        print(k)
    print(f"{len(gaps)} missing", file=sys.stderr)
    sys.exit(1 if gaps else 0)
