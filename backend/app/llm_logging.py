import datetime as dt
import logging

import httpx
from sqlalchemy.orm import Session

from app.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
from app.models import LlmCallLog
from app import supabase_meter  # per-endpoint REST counts (memory-only unless SUPABASE_METER_FILE is set)

supabase_meter.configure(app="event-radar")

logger = logging.getLogger(__name__)

HKT = dt.timezone(dt.timedelta(hours=8))


def hkt_today_start_utc() -> dt.datetime:
    """Naive-UTC instant of the most recent HKT midnight. The shared
    chatanywhere.tech key's daily quota resets on HKT's day boundary (its
    owner is HK-based), not UTC's -- so "today" for both this ledger and the
    local llm_calls_today count needs to match that boundary, or the counter
    reads stale for up to 8h after HKT midnight. HKT has no DST, always
    UTC+8, so no zoneinfo/tzdata dependency is needed."""
    hkt_midnight = dt.datetime.now(HKT).replace(hour=0, minute=0, second=0, microsecond=0)
    return hkt_midnight.astimezone(dt.timezone.utc).replace(tzinfo=None)

# Per-MTok pricing (USD), input/output. Rough reference only, not a billing
# reconciliation: OPENAI_MODEL here is routed through a third-party proxy
# (see OPENAI_BASE_URL), whose actual billing terms may differ entirely from
# official OpenAI list prices — this just gives a relative cost trend.
PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-5-mini": (0.25, 2.00),  # unconfirmed — approximate, verify against your proxy's actual billing
    "gpt-5.4-mini": (0.25, 2.00),  # unconfirmed — same approximate rate as gpt-5-mini, no published number to go on
    "text-embedding-3-small": (0.02, 0.00),  # embeddings have no completion tokens; output price unused
}
DEFAULT_PRICING = (0.50, 1.50)


def log_call(
    db: Session | None,
    kind: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    provider: str = "chatanywhere",
) -> None:
    in_price, out_price = PRICING.get(model, DEFAULT_PRICING)
    cost_usd = (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price

    if db is not None:
        db.add(
            LlmCallLog(
                created_at=dt.datetime.utcnow(),
                kind=kind,
                model=model,
                provider=provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
            )
        )
        db.commit()

    _log_to_shared_ledger(
        kind=kind,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        provider=provider,
    )


def _log_to_shared_ledger(
    kind: str, model: str, input_tokens: int, output_tokens: int, latency_ms: int, cost_usd: float,
    provider: str = "chatanywhere",
) -> None:
    """Best-effort write to the shared cross-project Supabase `llm_calls` table
    — the same one D:\\adaptive_study_platform already logs to, so usage
    against the shared LLM key is visible in one place across quant/study/events.
    Never raises: a telemetry hiccup must never break interest parsing or ranking.

    RESTORED 2026-07-28: project/call_type/provider were dropped 2026-07-18
    because they 400'd against the live table at the time (the migration
    adding them hadn't been run yet). It has since landed — confirmed live
    via direct PostgREST query 2026-07-28 — so readers that key off the real
    columns (rather than parsing the `purpose` prefix) now see this project's
    rows again. No obvious `environment` value exists for this project (no
    paper/live-style distinction), so it's left unset.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return
    try:
        resp = httpx.post(
            f"{SUPABASE_URL}/rest/v1/llm_calls",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={
                "purpose": f"events:{kind}",
                "project": "events",
                "call_type": kind,
                "provider": provider,
                "model": model,
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "cost_usd": round(cost_usd, 6),
                "latency_ms": latency_ms,
            },
            timeout=5,
        )
        supabase_meter.record("POST", "llm_calls", supabase_meter.response_bytes(resp))
    except Exception:
        logger.warning("failed to log to shared llm_calls ledger", exc_info=True)


def _project_of(purpose: str) -> str:
    """Rows are tagged '{project}:{kind}'. Legacy/unprefixed rows predate this
    convention and were all written by study (the table's original owner)."""
    if purpose.startswith("events:"):
        return "events"
    if purpose.startswith("quant:"):
        return "quant"
    return "study"


def fetch_shared_usage_today() -> dict:
    """Cross-project usage for today (HKT), from the shared Supabase ledger.

    ADDED 2026-09-12: reads the one-row `llm_daily_summary` (kept current by
    a trigger on every llm_calls insert -- see
    D:\\llm-usage-dashboard\\migrations\\001_llm_daily_summary.sql) instead of
    fetching every raw row created today and summing them here. Found live:
    this function is polled from the frontend's status bar, and on the
    public demo instance (no auth, so tabs linger far longer than on the
    private one) that added up to ~7,400 calls/day against the OLD query --
    whose cost scaled with how many calls had happened today, paid on every
    single poll regardless. The new query returns one small row no matter
    how big today's row count is. FALLS BACK to the old raw-row method (via
    _fetch_shared_usage_today_from_raw_rows) if llm_daily_summary doesn't
    exist yet (PostgREST 404s an unknown table the same as it would an
    inaccessible one), so this keeps working correctly before that migration
    has been run -- rolling it out is not a breaking, ordered dependency.

    Best-effort: returns zeros if Supabase isn't configured or unreachable."""
    empty = {"calls": 0, "cost_usd": 0.0, "calls_by_project": {}}
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return empty

    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }
    # NOT hkt_today_start_utc().date() -- that instant is expressed in naive
    # UTC (HKT midnight is 16:00 the PREVIOUS UTC calendar day), so its own
    # .date() is one day behind the HKT calendar day it actually anchors.
    # Confirmed live: querying that value returned yesterday's summary row.
    # The HKT calendar date needs computing in the HKT zone directly, same
    # as the migration's trigger does in SQL (`AT TIME ZONE 'Asia/Hong_Kong'`).
    today = dt.datetime.now(HKT).date().isoformat()
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/llm_daily_summary",
            headers=headers,
            params={"select": "total_calls,total_cost_usd,calls_by_project", "day": f"eq.{today}"},
            timeout=10,
        )
        supabase_meter.record("GET", "llm_daily_summary", supabase_meter.response_bytes(resp))
        if resp.status_code == 404:
            return _fetch_shared_usage_today_from_raw_rows(headers)
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        logger.warning("failed to fetch llm_daily_summary", exc_info=True)
        return empty

    if not rows:
        return empty
    row = rows[0]
    return {
        "calls": row.get("total_calls") or 0,
        "cost_usd": row.get("total_cost_usd") or 0.0,
        "calls_by_project": row.get("calls_by_project") or {},
    }


def _fetch_shared_usage_today_from_raw_rows(headers: dict) -> dict:
    """Pre-migration fallback: the original approach, summing every row
    created today client-side -- real cost scales with today's row count,
    which is exactly what llm_daily_summary's trigger exists to replace.
    Kept only so fetch_shared_usage_today() doesn't break for a deployment
    that hasn't run 001_llm_daily_summary.sql yet."""
    empty = {"calls": 0, "cost_usd": 0.0, "calls_by_project": {}}
    today_start = hkt_today_start_utc().isoformat() + "Z"
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/llm_calls",
            headers=headers,
            params={"select": "purpose,cost_usd,created_at", "created_at": f"gte.{today_start}"},
            timeout=10,
        )
        supabase_meter.record("GET", "llm_calls", supabase_meter.response_bytes(resp))
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        logger.warning("failed to fetch shared llm_calls ledger", exc_info=True)
        return empty

    calls_by_project: dict[str, int] = {}
    total_cost = 0.0
    for row in rows:
        project = _project_of(row.get("purpose") or "")
        calls_by_project[project] = calls_by_project.get(project, 0) + 1
        total_cost += row.get("cost_usd") or 0.0

    return {"calls": len(rows), "cost_usd": total_cost, "calls_by_project": calls_by_project}
