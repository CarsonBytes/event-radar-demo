"""LLM client factory. Mirrors D:\\quant\\analyst\\llm.py — same truststore SSL
workaround (this machine's antivirus, AVG, intercepts HTTPS and re-signs
certs with a root Windows trusts but certifi doesn't), and the same
chatanywhere-then-DeepSeek fallback: the free chatanywhere.tech key (200/day)
is shared with quant + study, so the fallback decision is centralized in a
Supabase Edge Function (provider-decision) rather than tracked locally --
see quant's analyst/llm.py for the full reasoning (2026-07-14 incident where
a purely local call counter said "under budget" while the real shared quota
was already exhausted elsewhere)."""
import ssl
import threading
import time
from typing import Callable, TypeVar

import httpx
import openai
import truststore
from langchain_openai import ChatOpenAI

from app.config import (
    DEEPSEEK_API_KEY, DEEPSEEK_MODEL, OPENAI_API_KEY, OPENAI_API_KEY_FALLBACK, OPENAI_BASE_URL, OPENAI_MODEL,
    SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL,
)

_SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_HTTP_CLIENT = httpx.Client(verify=_SSL_CTX, timeout=60.0)

_DECISION_CACHE_SEC = 60.0
_decision_cache: dict = {"ts": 0.0, "provider": None}

# Which provider/model the most recent get_llm() call (on THIS thread) actually
# picked -- read via last_provider_used()/last_model_used() by llm_logging.log_call()
# so usage gets attributed correctly even when the fallback kicks in. thread-local,
# not a plain global: FastAPI can run sync route handlers in a threadpool, so two
# concurrent requests' get_llm() calls could otherwise race on a shared module global.
_tls = threading.local()


def last_provider_used() -> str:
    return getattr(_tls, "provider", "chatanywhere")


def last_model_used() -> str:
    return getattr(_tls, "model", OPENAI_MODEL)


def is_quota_exhausted(exc: Exception) -> bool:
    """openai-python raises RateLimitError for HTTP 429. chatanywhere.tech's
    free tier returns this specifically for "200 requests/day" exhaustion
    (confirmed live -- see the error message it actually sends), as opposed
    to a generic transient rate limit; there's no clean way to distinguish
    those two 429 cases from the exception alone, but in practice this
    project has only ever observed the daily-cap version. Shared by every
    LLM call site (ranking, ask) that wants to tell "the app is broken"
    apart from "today's free quota ran out, try again tomorrow.\""""
    if isinstance(exc, openai.RateLimitError):
        return True
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "rate_limit" in text


# Key rotation *within* chatanywhere -- distinct from (and tried first,
# ahead of) the chatanywhere-vs-DeepSeek provider_decision() below. Two
# chatanywhere accounts each with their own free 200/day cap means ~400/day
# for this app before DeepSeek is ever needed. In-memory only (resets on
# restart, same as _decision_cache below) -- not worth persisting for what's
# a same-day operational fact; if the restart happens to land while the
# first key is still exhausted, the very next call just re-discovers that
# and rotates again, at the cost of one wasted request.
_key_lock = threading.Lock()
_active_key_index = [0]


def _chatanywhere_keys() -> list[str]:
    return [k for k in (OPENAI_API_KEY, OPENAI_API_KEY_FALLBACK) if k]


def _current_chatanywhere_key() -> str:
    keys = _chatanywhere_keys()
    if not keys:
        return OPENAI_API_KEY  # unreachable in practice -- callers already gate on OPENAI_API_KEY being set
    with _key_lock:
        idx = min(_active_key_index[0], len(keys) - 1)
        return keys[idx]


def _advance_chatanywhere_key() -> bool:
    """Moves to the next configured chatanywhere key. Returns False (no-op)
    if there isn't one -- the caller's normal exhausted-quota handling (or
    the chatanywhere-vs-DeepSeek fallback) takes over from there."""
    keys = _chatanywhere_keys()
    with _key_lock:
        if _active_key_index[0] + 1 < len(keys):
            _active_key_index[0] += 1
            return True
        return False


T = TypeVar("T")


def invoke_with_rotation(call: Callable[[], T]) -> T:
    """Wraps a single LLM call site (e.g. `lambda: get_llm().invoke(...)`) with
    one retry, specifically for "this chatanywhere key's daily quota is
    exhausted" -- rotates to the next configured key and retries exactly
    once, rather than surfacing the failure (or falling through to DeepSeek)
    immediately. `call` must build its own client via get_llm() each time it
    runs (not close over an already-built one), so the retry actually picks
    up the newly-rotated key. Any other exception, or a second failure after
    rotating, propagates to the caller unchanged -- their existing
    is_quota_exhausted()-based handling still applies."""
    try:
        return call()
    except Exception as exc:
        if last_provider_used() == "chatanywhere" and is_quota_exhausted(exc) and _advance_chatanywhere_key():
            return call()
        raise


def provider_decision(cap: int = 200, reserve: int = 10) -> str:
    """Ask the shared Edge Function which provider to use right now. Fails OPEN to
    "chatanywhere" (today's existing behaviour) on any problem -- edge function not
    yet deployed, Supabase unreachable, timeout, missing config."""
    now = time.time()
    if now - _decision_cache["ts"] < _DECISION_CACHE_SEC and _decision_cache["provider"]:
        return _decision_cache["provider"]
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return "chatanywhere"
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/functions/v1/provider-decision",
            params={"cap": cap, "reserve": reserve},
            headers={"Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"},
            timeout=3.0,
        )
        resp.raise_for_status()
        provider = resp.json().get("provider", "chatanywhere")
    except Exception:
        return "chatanywhere"
    _decision_cache["ts"] = now
    _decision_cache["provider"] = provider
    return provider


def get_llm() -> ChatOpenAI:
    """Returns a fresh client each call (not cached as a module-level singleton like
    before) -- the provider can change mid-session once the shared quota is hit, so a
    permanently-cached client would keep using chatanywhere even after the decision
    flips. Cheap to rebuild: _HTTP_CLIENT (the actual connection pool) IS still
    shared/reused across both providers, only the thin ChatOpenAI wrapper is new."""
    provider = "chatanywhere"
    if DEEPSEEK_API_KEY:
        provider = provider_decision()

    if provider == "deepseek" and DEEPSEEK_API_KEY:
        kwargs: dict = {
            "model": DEEPSEEK_MODEL, "http_client": _HTTP_CLIENT,
            "api_key": DEEPSEEK_API_KEY, "base_url": "https://api.deepseek.com",
            "temperature": 0.2,
        }
        _tls.provider, _tls.model = "deepseek", DEEPSEEK_MODEL
        return ChatOpenAI(**kwargs)

    kwargs = {"model": OPENAI_MODEL, "http_client": _HTTP_CLIENT, "api_key": _current_chatanywhere_key()}
    # gpt-5 / o-series reasoning models only accept the default temperature.
    if not any(OPENAI_MODEL.startswith(p) for p in ("gpt-5", "o1", "o3", "o4")):
        kwargs["temperature"] = 0.2
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    _tls.provider, _tls.model = "chatanywhere", OPENAI_MODEL
    return ChatOpenAI(**kwargs)
