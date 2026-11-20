"""Lab results (B3): upload a sheet, see trends, edit a value, undo an upload, delete all.

Every upload is also a chat message (the photo thumbnail or the PDF's name) with the coach's
reply showing the table, so the original lives only in the chat. Nothing else keeps the file.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import agent, i18n, llm, store
from app import lab_catalog as cat
from app.auth import current_user
from app.db import connection
from app.pipeline import labs
from app.pipeline.common import to_json
from app.web import shell, templates

router = APIRouter(dependencies=[Depends(current_user)])
templates.env.globals.update(lab_value=labs.show_value, lab_range=labs.show_range,
                             lab_num=labs.num)


def _today(user: store.User):
    return datetime.now(ZoneInfo(user.time_zone)).date()


def label(marker: str | None, printed: str, lang: str) -> str:
    return cat.name(marker, lang) if marker in cat.MARKERS else printed


def band_spark(points: list[dict], w: int = 200, h: int = 44) -> dict:
    """Sparkline path plus the reference band (y of top and bottom), one scale for both."""
    vals = [p["value"] for p in points if p["value"] is not None]
    if not vals:
        return {}
    last = points[-1]
    lo_ref, hi_ref = last["ref_low"], last["ref_high"]
    # The band can be much wider than the values (ferritin 30–400): zoom on the values and
    # let the band run off the top, so a change from 18 to 34 is visible.
    top_ref = None if hi_ref is None else min(hi_ref, max(vals) * 1.6)
    scale = vals + [x for x in (lo_ref, top_ref) if x is not None]
    lo, hi = min(scale), max(scale)
    pad = ((hi - lo) or abs(hi) or 1) * 0.1
    lo, hi = lo - pad, hi + pad

    def y(v):
        return round(h - (v - lo) / (hi - lo) * h, 1)

    n = max(1, len(points) - 1)
    pts = [(round(i * w / n, 1) if len(points) > 1 else w / 2, y(p["value"]))
           for i, p in enumerate(points) if p["value"] is not None]
    path = "M" + " L".join(f"{x},{yy}" for x, yy in pts) if len(pts) > 1 else ""
    top = max(0, y(hi_ref)) if hi_ref is not None else 0
    bottom = y(lo_ref) if lo_ref is not None else h
    return {"path": path, "dots": pts[-1:], "band": (top, max(0, bottom - top))}


def cards(user_id: str, lang: str) -> list[dict]:
    """One per marker for the Health page: out of range first, then by name."""
    out = []
    for s in labs.summaries(user_id):
        t = labs.trend(user_id, s["key"])
        r = s["row"]
        out.append({"key": s["key"], "name": label(r["marker"], r["name_as_printed"], lang),
                    "row": r, "n": s["n"], **band_spark(t["points"])})
    return sorted(out, key=lambda c: (c["row"]["flag"] not in ("low", "high"), c["name"]))


def table_md(rows: list[dict], lang: str) -> str:
    """The coach's reply after an upload: one line per value, out of range first (bold).
    A list, because the chat's light Markdown has no tables."""
    t = i18n.t
    lines = []
    for r in sorted(rows, key=lambda r: r["flag"] not in ("low", "high")):
        v = labs.show_value(r) + (f" {t(r['unit'], lang)}" if r["value"] is not None
                                  and r["unit"] else "")
        rng = labs.show_range(r["ref_low"], r["ref_high"])
        name = label(r["marker"], r["name_as_printed"], lang)
        if r["flag"] in ("low", "high"):
            lines.append(f"- **{name} {v}: {t(r['flag'], lang)}** ({t('range', lang)} {rng})")
        else:
            lines.append(f"- {name} {v}" + (f" ({t('range', lang)} {rng})" if rng else ""))
    return "\n".join(lines)


def ingest_upload(user: store.User, raw: bytes, filename: str) -> str:
    """Posts the upload to the chat, runs C10, saves the rows, posts the table. Returns a
    status code from labs.MESSAGES, or "saved"."""
    lang = store.user_lang(user.id)
    try:
        content = labs.read_file(raw, filename)
    except labs.FileError as e:
        return str(e)
    attach = ([{"type": "image", "thumb": labs.thumb(content["images"][0])}]
              if "images" in content else [{"type": "file", "name": filename[:80]}])
    with connection() as c:
        mid = c.execute("insert into chat_messages (user_id, role, content, attachments) values "
                        "(%s, 'user', %s, %s::jsonb) returning id",
                        (user.id, i18n.t("Lab results", lang) + ("" if "text" in content
                                                              else f": {filename[:80]}"),
                         to_json(attach))).fetchone()["id"]
    try:
        out = labs.ingest(user.id, raw, filename, mid, _today(user))
    except labs.FileError as e:
        return str(e)
    except llm.LLMError:
        return "ai"
    if out.get("duplicate"):
        store.add_message(user.id, "assistant", i18n.t(labs.MESSAGES["duplicate"], lang))
        return "duplicate"
    n_out = sum(r["flag"] in ("low", "high") for r in out["rows"])
    reply = (i18n.t("Saved {n} lab results from {date}.", lang).format(
        n=len(out["rows"]), date=out["taken_on"]) + " " + (i18n.t(
            "{k} out of the lab's range: talk them over with your doctor.", lang).format(k=n_out)
        if n_out else i18n.t("All within the lab's ranges.", lang))
        + "\n\n" + table_md(out["rows"], lang))
    aid = store.add_message(user.id, "assistant", reply)
    agent.save_actions(user.id, aid, [{"tool": "lab_results", "summary": i18n.t(
        "Lab results saved: {n}", lang).format(n=len(out["rows"])), "undo": {
            "op": "delete_labs", "upload_id": out["upload_id"]}}])
    return "saved"


@router.post("/labs")
def upload(file: UploadFile, user: store.User = Depends(current_user)):
    raw = file.file.read(labs.MAX_BYTES + 1)
    status = ingest_upload(user, raw, file.filename or "lab")
    return RedirectResponse(f"/health?labs={status}#labs", status_code=303)


@router.get("/labs/{marker}", response_class=HTMLResponse)
def trend_sheet(request: Request, marker: str, user: store.User = Depends(current_user)):
    t = labs.trend(user.id, marker)
    if not t:
        return HTMLResponse("", status_code=404)
    lang = store.user_lang(user.id)
    t["name"] = label(marker if marker in cat.MARKERS else None, t["name"], lang)
    return templates.TemplateResponse(request, "partials/lab_sheet.html", shell(
        user, "/health", t=t, **band_spark(t["points"], w=320, h=80)))


@router.post("/labs/{row_id}")
def edit(row_id: int, value: str = Form(""), ref: str = Form(""), unit: str = Form(""),
         user: store.User = Depends(current_user)):
    if not labs.edit_row(user.id, row_id, value[:40], ref[:40], unit):
        return HTMLResponse("", status_code=404)
    return RedirectResponse("/health#labs", status_code=303)


@router.delete("/labs/upload/{upload_id}")
def delete_upload(upload_id: str, user: store.User = Depends(current_user)):
    n = labs.delete_upload(user.id, upload_id)
    return HTMLResponse("", status_code=200 if n else 404, headers={"HX-Redirect": "/health"}
                        if n else {})


@router.delete("/labs")
def delete_all(user: store.User = Depends(current_user)):
    labs.delete_all(user.id)
    return HTMLResponse("", headers={"HX-Redirect": "/settings#data"})
