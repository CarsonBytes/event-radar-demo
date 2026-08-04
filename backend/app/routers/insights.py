from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import LLM_DAILY_CAP
from app.db import get_db
from app.llm_logging import fetch_shared_usage_today, hkt_today_start_utc
from app.models import Event, Feedback, IngestRun, LlmCallLog
from app.schemas import InsightsOut, PrecisionStat

router = APIRouter(prefix="/insights", tags=["insights"])


def _precision_stat(label: str, up: int, down: int) -> PrecisionStat:
    total = up + down
    return PrecisionStat(label=label, up=up, down=down, rate=(up / total) if total else None)


@router.get("", response_model=InsightsOut)
def get_insights(db: Session = Depends(get_db)):
    ingest_runs = list(
        db.scalars(select(IngestRun).order_by(IngestRun.started_at.desc()).limit(10))
    )
    llm_calls = list(
        db.scalars(select(LlmCallLog).order_by(LlmCallLog.created_at.desc()).limit(10))
    )

    # Single source of truth for LLM usage: every call site (interest parsing,
    # reranking — manual or scheduler-triggered) logs here via llm_logging.log_call,
    # so this one query reflects total usage regardless of what triggered it.
    all_calls = list(db.scalars(select(LlmCallLog)))
    llm_total_calls = len(all_calls)
    llm_total_cost_usd = sum(c.cost_usd for c in all_calls)
    llm_avg_latency_ms = sum(c.latency_ms for c in all_calls) / llm_total_calls if all_calls else 0.0

    today_start = hkt_today_start_utc()
    calls_today = [c for c in all_calls if c.created_at >= today_start]
    llm_calls_today = len(calls_today)
    llm_cost_today_usd = sum(c.cost_usd for c in calls_today)

    rows = db.execute(select(Feedback.signal, Event.category).join(Event, Feedback.event_id == Event.id)).all()

    overall_up = sum(1 for signal, _ in rows if signal == "up")
    overall_down = sum(1 for signal, _ in rows if signal == "down")

    by_category: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # category -> [up, down]
    for signal, category in rows:
        idx = 0 if signal == "up" else 1
        by_category[category or "Uncategorized"][idx] += 1

    precision_by_category = [
        _precision_stat(category, up, down) for category, (up, down) in sorted(by_category.items())
    ]

    shared = fetch_shared_usage_today()

    return InsightsOut(
        recent_ingest_runs=ingest_runs,
        recent_llm_calls=llm_calls,
        llm_total_calls=llm_total_calls,
        llm_total_cost_usd=llm_total_cost_usd,
        llm_avg_latency_ms=llm_avg_latency_ms,
        llm_calls_today=llm_calls_today,
        llm_cost_today_usd=llm_cost_today_usd,
        llm_daily_cap=LLM_DAILY_CAP,
        shared_calls_today=shared["calls"],
        shared_cost_today_usd=shared["cost_usd"],
        shared_calls_by_project=shared["calls_by_project"],
        overall_precision=_precision_stat("overall", overall_up, overall_down),
        precision_by_category=precision_by_category,
    )
