"""Files (C4 sources): upload, step-wise reading, fact review, delete. Used by setup and You."""

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app import sources, store
from app.auth import current_user
from app.db import connection
from app.web import templates, ui

GUEST_MAX_FILES = 5
router = APIRouter(dependencies=[Depends(current_user)])


def files_context(user: store.User, **extra) -> dict:
    return {**ui(user), "files": sources.list_sources(user.id),
            "proposed": sources.proposed_facts(user.id), **extra}


def _ctx(request: Request, user: store.User, **extra) -> dict:
    """Keep setup-specific behaviour when the block is re-rendered from the setup page."""
    in_setup = "/welcome" in request.headers.get("HX-Current-URL", "")
    return files_context(user, setup=in_setup,
                         next_url="/welcome/4/done" if in_setup else "/memory#files", **extra)


@router.post("/files/upload", response_class=HTMLResponse)
async def upload(request: Request, files: list[UploadFile],
                 user: store.User = Depends(current_user)):
    errors = []
    from app import i18n, llm
    lang = store.user_lang(user.id)
    if not llm.is_member(user.id):  # newcomers: a few files, so open sign-up can't fill the DB
        with connection() as c:
            have = c.execute("select count(*) as n from sources where user_id = %s",
                             (user.id,)).fetchone()["n"]
        if have + len(files) > GUEST_MAX_FILES:
            errors.append(i18n.t("You can keep up to 5 files. Delete one first.", lang))
            files = []
    for f in files:
        raw = await f.read(sources.MAX_BYTES + 1)
        try:
            await run_in_threadpool(sources.add_source, user.id, f.filename or "file.txt", raw)
        except sources.SourceError as e:
            text = i18n.t(e.text, lang)
            errors.append(f"{e.name}: {text}" if e.name else text)
    return templates.TemplateResponse(request, "partials/files.html",
                                      _ctx(request, user, errors=errors))


@router.post("/files/{source_id}/step", response_class=HTMLResponse)
def step(request: Request, source_id: int, user: store.User = Depends(current_user)):
    src = sources.step(user.id, source_id)
    if src is None:
        return HTMLResponse("")
    if src["status"] == "reading":
        return templates.TemplateResponse(request, "partials/file_row.html",
                                          {**ui(user), "f": src})
    # finished: refresh the whole block so the facts to review appear
    return templates.TemplateResponse(request, "partials/files.html", _ctx(request, user),
                                      headers={"HX-Retarget": "#files", "HX-Reswap": "outerHTML"})


@router.post("/files/{source_id}/delete", response_class=HTMLResponse)
def delete(request: Request, source_id: int, user: store.User = Depends(current_user)):
    sources.delete_source(user.id, source_id)
    return templates.TemplateResponse(request, "partials/files.html", _ctx(request, user))


@router.post("/facts/review")
async def review(request: Request, next_url: str = Form("/knowledge"),
                 user: store.User = Depends(current_user)):
    form = await request.form()
    keep = {int(v) for v in form.getlist("keep") if str(v).isdigit()}
    sources.review_facts(user.id, keep)
    safe = next_url.startswith("/") and not next_url.startswith("//")
    target = next_url if safe else "/knowledge"
    return RedirectResponse(target, status_code=303)
