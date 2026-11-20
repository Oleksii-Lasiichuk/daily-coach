"""/admin: who signed up, what they spent this month, and their AI access and cap. Only for
ADMIN_EMAILS; everyone else gets 404 (the page does not exist for them)."""

import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import llm, store
from app.auth import current_user
from app.config import get_settings
from app.web import is_admin, shell, templates

router = APIRouter(dependencies=[Depends(current_user)])


def _admin(user: store.User = Depends(current_user)) -> store.User:
    if not is_admin(user):
        raise NotFound()
    return user


class NotFound(Exception):
    pass


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user: store.User = Depends(_admin)):
    people = []
    for r in store.all_users_with_cost():
        uid = str(r["id"])
        people.append(r | {"id": uid, "cap": llm.cap_for(uid), "member": llm.is_member(uid),
                           "cost": float(r["cost"])})
    return templates.TemplateResponse(request, "admin.html", shell(
        user, "/admin", people=people, has_family_key=bool(
            get_settings().openrouter_api_key_family), starter=llm.STARTER_CAP_USD,
        member_cap=llm.MEMBER_CAP_USD, saved=request.query_params.get("saved")))


@router.post("/admin/users/{user_id}")
def save_access(user_id: str, access: str = Form("allowed"), cap: str = Form(""),
                key_pool: str = Form("main"), _user: store.User = Depends(_admin)):
    try:
        uuid.UUID(user_id)
    except ValueError:
        raise NotFound() from None
    if store.get_user(user_id) is None:
        raise NotFound()
    try:
        cap_usd = round(max(0.0, min(500.0, float(cap.replace(",", ".")))), 2) if cap.strip() \
            else None
    except ValueError:
        cap_usd = None
    store.set_ai_access(user_id, access="blocked" if access == "blocked" else "allowed",
                        cap=cap_usd, key_pool="family" if key_pool == "family" else "main")
    return RedirectResponse(f"/admin?saved={user_id}#u-{user_id}", status_code=303)
