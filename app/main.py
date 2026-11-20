"""FastAPI app: middleware, routers, error handling."""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from app import db
from app.auth import SESSION_MAX_AGE, NotAuthenticated, not_authenticated_response, origin_ok
from app.config import get_settings
from app.crypto import derived_key
from app.routes import admin, auth, data_pages, files, knowledge, pages, profile, push, welcome
from app.routes import calendar as calendar_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_settings()  # fail fast on missing configuration
    yield
    db.close_pool()


app = FastAPI(title="Daily Coach", lifespan=lifespan, docs_url=None, redoc_url=None,
              openapi_url=None)


@app.middleware("http")
async def request_guard(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:12]
    if not origin_ok(request):
        return PlainTextResponse("Bad origin", status_code=403)
    acc, t0 = [0, 0.0], time.perf_counter()
    token = db.timing.set(acc)
    try:
        response = await call_next(request)
        response.headers["Server-Timing"] = (
            f"db;desc=\"{acc[0]} checkouts\";dur={acc[1] * 1000:.0f}, "
            f"total;dur={(time.perf_counter() - t0) * 1000:.0f}")
        return response
    except Exception:
        log.exception("request %s failed: %s %s", request.state.request_id, request.method,
                      request.url.path)
        return PlainTextResponse(
            f"Something went wrong on our side (ref {request.state.request_id}). Try again.",
            status_code=500)
    finally:
        db.timing.reset(token)


# Added after the guard so it runs first and the session is available everywhere.
app.add_middleware(
    SessionMiddleware,
    secret_key=derived_key("session-cookie"),
    session_cookie="__session",  # the only cookie Firebase Hosting forwards
    max_age=SESSION_MAX_AGE,
    same_site="lax",
    https_only=get_settings().env == "prod",
)


@app.exception_handler(NotAuthenticated)
async def handle_not_authenticated(request: Request, _exc: NotAuthenticated) -> Response:
    return not_authenticated_response(request)


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(data_pages.router)
app.include_router(knowledge.router)
app.include_router(profile.router)
app.include_router(welcome.router)
app.include_router(files.router)
app.include_router(push.router)
app.include_router(admin.router)
app.include_router(calendar_routes.router)


@app.exception_handler(admin.NotFound)
async def handle_not_found(_request: Request, _exc: admin.NotFound) -> Response:
    return PlainTextResponse("Not found", status_code=404)


@app.get("/status", response_class=PlainTextResponse)
def status() -> str:
    return "ok"
