"""C10 Lab extraction: a lab sheet (photo or text PDF) → rows as printed (LLM) → canonical
markers, numbers, units, ranges and low/high flags (code).

The model only transcribes. Code maps names (app/lab_catalog.py), parses numbers, converts
units and decides the flag, using the lab's printed range first.
"""

import base64
import io
import re
import uuid
from datetime import date

from pydantic import BaseModel

from app import lab_catalog as cat
from app import llm
from app.db import connection
from app.pipeline.common import prompt, to_json

MAX_BYTES = 10 * 1024 * 1024
MAX_SIDE = 2000


class FileError(ValueError):
    """The upload can't be read; the code is shown to the person as MESSAGES[code]."""


MESSAGES = {
    "empty": "The file is empty.",
    "big": "The file is larger than 10 MB.",
    "pdf": "Couldn't read this PDF.",
    "scan": "This PDF is a scan without text. Please send a photo of the page instead.",
    "unreadable": "This file is not a photo or a PDF we can read.",
    "nothing": "No lab values found on this page.",
    "ai": "The coach couldn't read the sheet this time. Try again.",
    "duplicate": "This sheet is already saved.",
}


class PrintedRow(BaseModel):
    name_as_printed: str
    value_as_printed: str
    unit_as_printed: str
    ref_as_printed: str


class LabSheet(BaseModel):
    lab: str | None
    taken_on: str | None  # YYYY-MM-DD as the model read it; checked in code
    rows: list[PrintedRow]


# --- reading the file --------------------------------------------------------------------

def read_file(raw: bytes, filename: str = "") -> dict:
    """{"images": [jpeg bytes]} for a photo, {"text": str} for a PDF with a text layer."""
    if not raw:
        raise FileError("empty")
    if len(raw) > MAX_BYTES:
        raise FileError("big")
    if raw[:5] == b"%PDF-" or filename.lower().endswith(".pdf"):
        return {"text": pdf_text(raw)}
    return {"images": [shrink(raw)]}


def pdf_text(raw: bytes) -> str:
    from pypdf import PdfReader
    try:
        pages = PdfReader(io.BytesIO(raw)).pages[:4]
        text = "\n\n".join((p.extract_text() or "") for p in pages).strip()
    except Exception as e:  # broken or encrypted PDF
        raise FileError("pdf") from e
    if len(text) < 40:
        raise FileError("scan")
    return text[:20000]


def shrink(raw: bytes) -> bytes:
    """JPEG, longest side ≤ 2000 px."""
    from PIL import Image, ImageOps
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    except Exception as e:
        raise FileError("unreadable") from e
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


def thumb(jpeg: bytes) -> str:
    """Small data-URL thumbnail for the chat message."""
    from PIL import Image
    img = Image.open(io.BytesIO(jpeg))
    img.thumbnail((480, 480))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


# --- C10: the model transcribes ----------------------------------------------------------

def extract(content: dict, user_id: str | None = None) -> LabSheet:
    """content = read_file(...). FAST_MODEL; SMART_MODEL once if the reply doesn't parse."""
    if "text" in content:
        user: object = "Lab sheet text (from a PDF):\n\n" + content["text"]
    else:
        user = [{"type": "text", "text": "Lab sheet photo:"}] + [
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}}
            for img in content["images"][:2]]
    messages = [{"role": "system", "content": prompt("c10_labs")},
                {"role": "user", "content": user}]
    try:
        r = llm.complete(name="extract-lab-sheet", schema=LabSheet, user_id=user_id,
                         max_tokens=4000, temperature=0, messages=messages)
    except llm.BudgetExceeded:
        raise
    except llm.LLMError:
        r = llm.complete(name="extract-lab-sheet-retry", model=llm.SMART_MODEL, schema=LabSheet,
                         user_id=user_id, max_tokens=4000, temperature=0, messages=messages)
    return r.parsed


# --- code: numbers, units, ranges, flags -------------------------------------------------

NUM = r"[-+]?\d+(?:[.,]\d+)?"


def parse_number(s: str) -> tuple[float | None, str | None, str | None]:
    """'12,4*' → (12.4, None, None); '<0.5' → (0.5, '<', None); 'negative' → (None, None,
    'negative')."""
    t = (s or "").strip().replace(" ", "").replace(" ", "")
    m = re.match(r"^(<=?|>=?|≤|≥|менше|більше|до)?(" + NUM + r")\*?[↑↓HhLl!]*$", t)
    if not m:
        return None, None, (s or "").strip() or None
    q = m.group(1) or ""
    qualifier = "<" if q[:1] in ("<", "≤") or q in ("менше", "до") else (
        ">" if q[:1] in (">", "≥") or q == "більше" else None)
    return float(m.group(2).replace(",", ".")), qualifier, None


def parse_range(s: str) -> tuple[float | None, float | None]:
    """'30 - 100', '30–100', '< 5', 'до 15', '> 1.0', 'від 2' → (low, high)."""
    t = (s or "").strip().lower().replace(",", ".")
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums:
        return None, None
    if len(nums) >= 2 and re.search(r"\d\s*(-|–|—|\.\.\.|…)\s*\d", t):
        return nums[0], nums[1]
    if re.search(r"(<|≤|до|up to|less|менше|нижче)", t):
        return None, nums[0]
    if re.search(r"(>|≥|від|from|more|більше|вище|понад)", t):
        return nums[0], None
    return (nums[0], nums[1]) if len(nums) >= 2 else (None, None)


def parse_date(s: str | None) -> date | None:
    t = (s or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", t) or None
    try:
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})", t)
        if m:
            return date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        return None
    return None


def flag(value: float | None, qualifier: str | None, low: float | None,
         high: float | None) -> str:
    if value is None or (low is None and high is None):
        return "unknown"
    if low is not None and value < low and qualifier != ">":
        return "low"
    if high is not None and value > high and qualifier != "<":
        return "high"
    if qualifier == "<" and low is not None and value <= low:
        return "low"
    if qualifier == ">" and high is not None and value >= high:
        return "high"
    return "in"


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


def normalise(sheet: LabSheet) -> list[dict]:
    """Rows in canonical units with flags. taken_on is set by the caller."""
    rows = []
    for p in sheet.rows:
        name = p.name_as_printed.strip()[:120]
        if not name:
            continue
        marker = cat.find(name)
        value, qualifier, value_text = parse_number(p.value_as_printed)
        low, high = parse_range(p.ref_as_printed)
        unit = cat.unit(p.unit_as_printed)
        if marker:
            f = cat.factor(marker, p.unit_as_printed)
            if f is not None:
                value, low, high = (None if x is None else x * f for x in (value, low, high))
                unit = cat.MARKERS[marker][3]
            if low is None and high is None and f is not None:
                low, high = cat.MARKERS[marker][5]  # no printed range: the catalogue default
        rows.append({"marker": marker, "name_as_printed": name, "value": _r(value),
                     "qualifier": qualifier, "value_text": (value_text or "")[:80] or None,
                     "unit": unit[:30] or None, "ref_low": _r(low), "ref_high": _r(high),
                     "flag": flag(value, qualifier, low, high)})
    return rows


# --- storage -----------------------------------------------------------------------------

def save(user_id: str, sheet: LabSheet, rows: list[dict], taken_on: date, source_name: str,
         message_id: int | None) -> dict:
    """{"upload_id": uuid} or {"duplicate": True} when the same date + values are saved."""
    sig = sorted((r["marker"] or r["name_as_printed"], r["value"]) for r in rows)
    with connection() as c:
        old = c.execute("select upload_id, marker, name_as_printed, value from lab_results "
                        "where user_id = %s and taken_on = %s", (user_id, taken_on)).fetchall()
        by: dict = {}
        for o in old:
            by.setdefault(o["upload_id"], []).append(
                (o["marker"] or o["name_as_printed"], _r(float(o["value"]))
                 if o["value"] is not None else None))
        if any(sorted(v) == sig for v in by.values()):
            return {"duplicate": True}
        upload = uuid.uuid4()
        for r in rows:
            c.execute(
                "insert into lab_results (user_id, upload_id, taken_on, lab, marker, "
                "name_as_printed, value, qualifier, value_text, unit, ref_low, ref_high, flag, "
                "source_name, source_message_id) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s)",
                (user_id, upload, taken_on, (sheet.lab or "")[:80] or None, r["marker"],
                 r["name_as_printed"], r["value"], r["qualifier"], r["value_text"], r["unit"],
                 r["ref_low"], r["ref_high"], r["flag"], source_name[:120] or None,
                 message_id))
    return {"upload_id": str(upload)}


def ingest(user_id: str, raw: bytes, filename: str, message_id: int | None,
           today: date) -> dict:
    """File → C10 → rows saved. Returns {upload_id | duplicate, rows, taken_on, lab}."""
    content = read_file(raw, filename)
    with llm.trace("extract-lab-sheet", input={"file": filename, "kind": "pdf" if "text" in
                                                content else "photo"},
                   user_id=user_id, tags=["labs"]) as root:
        sheet = extract(content, user_id)
        rows = normalise(sheet)
        root.update(output={"lab": sheet.lab, "taken_on": sheet.taken_on, "rows": rows})
    if not rows:
        raise FileError("nothing")
    taken = parse_date(sheet.taken_on)
    taken = taken if taken and taken <= today else today
    out = save(user_id, sheet, rows, taken, filename, message_id)
    return out | {"rows": rows, "taken_on": taken, "lab": sheet.lab}


def all_rows(user_id: str) -> list[dict]:
    with connection() as c:
        return c.execute("select * from lab_results where user_id = %s order by taken_on, id",
                         (user_id,)).fetchall()


def get_row(user_id: str, row_id: int) -> dict | None:
    with connection() as c:
        return c.execute("select * from lab_results where user_id = %s and id = %s",
                         (user_id, row_id)).fetchone()


def edit_row(user_id: str, row_id: int, value: str, ref: str, unit: str) -> bool:
    """The person corrects a value, range or unit; the flag is recomputed in code."""
    row = get_row(user_id, row_id)
    if not row:
        return False
    v, q, text = parse_number(value)
    low, high = parse_range(ref) if ref.strip() else (row["ref_low"], row["ref_high"])
    low = None if low is None else float(low)
    high = None if high is None else float(high)
    with connection() as c:
        c.execute("update lab_results set value = %s, qualifier = %s, value_text = %s, "
                  "unit = %s, ref_low = %s, ref_high = %s, flag = %s, edited = true "
                  "where user_id = %s and id = %s",
                  (v, q, text, unit.strip()[:30] or row["unit"], low, high,
                   flag(v, q, low, high), user_id, row_id))
    return True


def delete_upload(user_id: str, upload_id: str) -> int:
    try:
        uuid.UUID(upload_id)
    except ValueError:
        return 0
    with connection() as c:
        return c.execute("delete from lab_results where user_id = %s and upload_id = %s",
                         (user_id, upload_id)).rowcount


def delete_all(user_id: str) -> int:
    with connection() as c:
        return c.execute("delete from lab_results where user_id = %s", (user_id,)).rowcount


def has_any(user_id: str) -> bool:
    with connection() as c:
        return c.execute("select 1 from lab_results where user_id = %s limit 1",
                         (user_id,)).fetchone() is not None


# --- trends and what the coach sees ------------------------------------------------------

def _f(x) -> float | None:
    return None if x is None else float(x)


def trend(user_id: str, marker: str) -> dict | None:
    """Points, last value, change vs the previous test, and how often it was out of range."""
    with connection() as c:
        rows = c.execute("select * from lab_results where user_id = %s and (marker = %s or "
                         "(marker is null and name_as_printed = %s)) order by taken_on, id",
                         (user_id, marker, marker)).fetchall()
    if not rows:
        return None
    last = rows[-1]
    prev = next((r for r in reversed(rows[:-1]) if r["value"] is not None), None)
    change = (round(float(last["value"]) - float(prev["value"]), 2)
              if prev and last["value"] is not None else None)
    return {"marker": marker, "name": cat.name(marker) if marker in cat.MARKERS
            else last["name_as_printed"], "unit": last["unit"],
            "points": [{"date": r["taken_on"], "value": _f(r["value"]),
                        "qualifier": r["qualifier"], "text": r["value_text"],
                        "ref_low": _f(r["ref_low"]), "ref_high": _f(r["ref_high"]),
                        "flag": r["flag"], "id": r["id"], "lab": r["lab"],
                        "upload_id": str(r["upload_id"])} for r in rows],
            "last": _f(last["value"]), "last_date": last["taken_on"], "last_flag": last["flag"],
            "change_vs_previous": change,
            "times_out_of_range": sum(r["flag"] in ("low", "high") for r in rows)}


def summaries(user_id: str) -> list[dict]:
    """One per marker: the latest row, for the Health page."""
    latest: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for r in all_rows(user_id):
        k = r["marker"] or r["name_as_printed"]
        latest[k] = r
        counts[k] = counts.get(k, 0) + 1
    return [{"key": k, "row": r, "n": counts[k]} for k, r in latest.items()]


KEY_MARKERS = ("ferritin", "vitamin_d", "hgb")


def context_lines(user_id: str, today: date) -> list[str]:
    """For the coach and C6: latest out-of-range markers of the last 12 months, plus the latest
    ferritin, vitamin D and haemoglobin. Short text lines, nothing else from the sheet."""
    out = []
    for s in summaries(user_id):
        r = s["row"]
        if not r["marker"] or (today - r["taken_on"]).days > 366:
            continue
        if r["flag"] in ("low", "high") or r["marker"] in KEY_MARKERS:
            out.append(line(r))
    return out


def num(x) -> str:
    """Display: 1 decimal from 10 up, 2 below ("94.8", "2.1", "0.03", "145")."""
    x = float(x)
    return f"{round(x, 1 if abs(x) >= 10 else 2):g}"


def show_range(low, high) -> str:
    if low is None and high is None:
        return ""
    if low is None:
        return f"< {num(high)}"
    if high is None:
        return f"> {num(low)}"
    return f"{num(low)}–{num(high)}"


def show_value(r: dict) -> str:
    return (f"{r['qualifier'] or ''}{num(r['value'])}" if r["value"] is not None
            else r.get("value_text") or r.get("text") or "–")


def line(r: dict) -> str:
    rng = show_range(r["ref_low"], r["ref_high"]) or "no range"
    value = show_value(r)
    name = cat.name(r["marker"]) if r["marker"] in cat.MARKERS else r["name_as_printed"]
    return f"{name} {value} {r['unit'] or ''} ({r['taken_on']}, range {rng}): {r['flag']}"


def low_flags(user_id: str, today: date) -> list[str]:
    """For C9: low ferritin / haemoglobin in the last 12 months (iron-rich food tip)."""
    return [s["key"] for s in summaries(user_id) if s["key"] in ("ferritin", "hgb")
            and s["row"]["flag"] == "low" and (today - s["row"]["taken_on"]).days <= 366]


def tool_result(user_id: str, marker: str | None, today: date) -> dict:
    """Agent tool `lab_results`: one marker's trend, or the short list of all."""
    if marker:
        m = cat.find(marker) or marker
        t = trend(user_id, m)
        return to_json_safe(t) if t else {"error": f"no results for {marker}"}
    return {"markers": [line(s["row"]) for s in summaries(user_id)],
            "flagged_last_12_months": context_lines(user_id, today)}


def to_json_safe(d: dict) -> dict:
    import json
    return json.loads(to_json(d))
