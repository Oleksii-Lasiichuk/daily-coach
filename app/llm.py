"""The one place every LLM call goes through.

OpenRouter (OpenAI-compatible API), called through Langfuse's OpenAI wrapper, so each call is
recorded as a `generation` with model, tokens and cost. Callers wrap one unit of work (one chat
turn, one eval case) in `trace()`, which sets the trace name, input/output, user, session and
tags.

Privacy: only the internal user id goes to Langfuse, never the email. Secrets never go into
prompts.

Run `uv run python -m app.llm "your message"` to send one traced call.
"""

import contextvars
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from langfuse import Langfuse, propagate_attributes
from pydantic import BaseModel, ValidationError

from app.config import get_settings

settings = get_settings()
os.environ.setdefault("OTEL_SERVICE_NAME", "daily-coach")  # shown on every trace

# Initialize the Langfuse client before importing the OpenAI wrapper, so the wrapper uses it.
langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    base_url=settings.langfuse_base_url,
    environment=settings.langfuse_tracing_environment,
)

from langfuse.openai import OpenAI  # noqa: E402

FAST_MODEL = "google/gemini-3.1-flash-lite"  # extraction tools, nutrition, safety
SMART_MODEL = "google/gemini-3.8-flash"  # coach agent, day type, planner, interviewer
DEEP_MODEL = "anthropic/claude-sonnet-5.5"  # "Think harder"
MODELS = {SMART_MODEL: "Gemini 3.8 Flash", DEEP_MODEL: "Claude Sonnet 5.5",
          FAST_MODEL: "Gemini 3.1 Flash-Lite"}

_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key,
    timeout=30,
    max_retries=2,  # retries 429 and 5xx with backoff
    default_headers={"X-Title": "Daily Coach"},
)


MONTHLY_CAP_USD = 20.0  # cap per user on the app's key; no cap with the user's own key


_user_clients: dict[str, OpenAI] = {}


def client_for(user_id: str | None) -> OpenAI:
    """The user's own OpenRouter key when they added one, else the app's key."""
    if not user_id:
        return _client
    from app import crypto, store
    row = store.get_secret(user_id, "openrouter")
    if not row:
        return _client
    if row["ciphertext"] not in _user_clients:
        _user_clients[row["ciphertext"]] = OpenAI(
            base_url="https://openrouter.ai/api/v1", api_key=crypto.decrypt(row["ciphertext"]),
            timeout=60, max_retries=2, default_headers={"X-Title": "Daily Coach"})
    return _user_clients[row["ciphertext"]]


def uses_own_key(user_id: str) -> bool:
    from app import store
    return store.get_secret(user_id, "openrouter") is not None


def chat(*, name: str, model: str, messages: list[dict], tools: list[dict] | None = None,
         user_id: str | None = None, max_tokens: int = 1500, temperature: float = 0.3):
    """One raw chat call with tools (the coach agent). Budget, usage and tracing included."""
    from app import store

    if user_id and not uses_own_key(user_id) and store.month_cost(user_id) >= MONTHLY_CAP_USD:
        raise BudgetExceeded(f"Monthly AI budget of ${MONTHLY_CAP_USD:.0f} is used up. Add your "
                             "own OpenRouter key in Profile to continue.")
    extra: dict[str, Any] = {"usage": {"include": True}}
    if model in (SMART_MODEL, DEEP_MODEL):
        extra["reasoning"] = {"effort": "low"}
        max_tokens += 2000
    kwargs: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens,
                              "temperature": temperature, "name": name, "extra_body": extra}
    if tools:
        kwargs["tools"] = tools
    try:
        r = client_for(user_id).chat.completions.create(**kwargs)
    except Exception as e:
        raise LLMError(f"{name}: model call failed: {e}") from e
    if user_id and r.usage:
        store.record_usage(user_id, name, r.model, r.usage.prompt_tokens or 0,
                           r.usage.completion_tokens or 0, float(getattr(r.usage, "cost", 0) or 0))
    return r


class LLMError(Exception):
    """The model call failed or returned output we could not use."""


class BudgetExceeded(LLMError):
    pass


@dataclass
class LLMResult:
    text: str
    parsed: BaseModel | None
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@contextmanager
def trace(name: str, *, input: Any, user_id: str | None, session_id: str | None = None,
          tags: list[str] | None = None, metadata: dict[str, str] | None = None):
    """One trace = one unit of work. Use a stable, verb-first name, e.g. `handle-chat-turn`.

    Yields the root observation; call `root.update(output=...)` with what a reviewer should see.
    """
    with langfuse.start_as_current_observation(as_type="span", name=name, input=input) as root:
        with propagate_attributes(user_id=user_id or "eval", session_id=session_id, tags=tags or [],
                                  metadata=metadata or {}):
            yield root


def current_trace_id() -> str | None:
    return langfuse.get_current_trace_id()


def call_in_context(fn, *args, **kwargs):
    """Wraps fn so it runs in a copy of the current context (keeps the Langfuse trace when
    run in a thread pool)."""
    ctx = contextvars.copy_context()
    return lambda: ctx.run(fn, *args, **kwargs)


def complete(*, name: str, messages: list[dict[str, str]], model: str = FAST_MODEL,
             schema: type[BaseModel] | None = None, max_tokens: int = 800,
             temperature: float = 0.2, user_id: str | None = None) -> LLMResult:
    """One model call. With `schema`, the reply must be JSON matching it (one retry if not).
    With `user_id`, the monthly cap is checked first and the cost is recorded in llm_usage."""
    from app import store  # local import: store needs the DB, evals may run without users

    if user_id and not uses_own_key(user_id) and store.month_cost(user_id) >= MONTHLY_CAP_USD:
        raise BudgetExceeded(f"Monthly AI budget of ${MONTHLY_CAP_USD:.0f} is used up.")
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "name": name,  # observation name in Langfuse, e.g. `classify-intent`
        # OpenRouter returns the real cost; reasoning tokens count toward max_tokens, so the
        # reasoning models think briefly and get extra room for it.
        "extra_body": {"usage": {"include": True}},
    }
    if model == SMART_MODEL:
        kwargs["extra_body"]["reasoning"] = {"effort": "low"}
        kwargs["max_tokens"] = max_tokens + 2000
    if schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
        }

    last_error: Exception | None = None
    for _attempt in range(2 if schema else 1):
        try:
            response = client_for(user_id).chat.completions.create(**kwargs)
        except Exception as e:  # network, auth, rate limit after SDK retries
            raise LLMError(f"{name}: model call failed: {e}") from e
        choice = response.choices[0]
        usage = response.usage
        result = LLMResult(
            text=choice.message.content or "",
            parsed=None,
            model=response.model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cost_usd=float(getattr(usage, "cost", 0) or 0),
        )
        if user_id:
            store.record_usage(user_id, name, result.model, result.input_tokens,
                               result.output_tokens, result.cost_usd)
        if schema is None:
            return result
        if choice.finish_reason == "length":
            last_error = ValueError("reply cut off at max_tokens")
            kwargs["max_tokens"] += 1500
            continue
        try:
            result.parsed = schema.model_validate_json(result.text)
            return result
        except ValidationError as e:
            last_error = e
    raise LLMError(f"{name}: reply did not match {schema.__name__}: {last_error}")


if __name__ == "__main__":
    import sys

    message = " ".join(sys.argv[1:]) or "Привіт! Яка ідеальна каденс для бігу? One sentence."
    with trace("run-smoke-test", input=message, user_id="dev-smoke",
               session_id="dev-smoke-session", tags=["smoke"]) as root:
        result = complete(
            name="generate-reply",
            messages=[
                {"role": "system",
                 "content": "You are a concise running coach. Reply in the user's language."},
                {"role": "user", "content": message},
            ],
        )
        root.update(output=result.text)
    langfuse.flush()
    print(result.text)
    print(json.dumps({"model": result.model, "in": result.input_tokens,
                      "out": result.output_tokens, "cost_usd": result.cost_usd}))
