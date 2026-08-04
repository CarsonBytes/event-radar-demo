from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import DEMO_MODE
from app.db import get_db
from app.ingest_job import get_rerank_status
from app.models import IngestRun, InterestProfile, SystemEvent
from app.system_log import log_event

# Matches only the terminal outcome of a rerank *attempt* -- not "rerank
# started" or a per-batch failure log line -- so /status's `last_rerank`
# reflects a persisted, DB-backed "what actually happened last time" fact
# that survives a backend restart, unlike get_rerank_status()'s in-memory
# (and therefore reset-on-restart) live state.
_TERMINAL_RERANK_PREFIXES = ("rerank finished", "rerank skipped", "rerank failed")

router = APIRouter(prefix="/debug", tags=["debug"])

"""Built to close a real gap hit repeatedly while debugging this app:
LlmCallLog/IngestRun/Feedback each track their own slice of what happened,
so answering "did the rerank triggered by that save actually finish, and
did anything fail along the way" meant manually cross-referencing three or
four endpoints by timestamp. These endpoints are the single place meant to
be read chronologically, plus a live "is a rerank running right now" flag
that previously had to be inferred by polling and counting rows by hand.

Note: like /api/insights, this is unauthenticated on the public site (see
the project's pending Cloudflare Access item) -- it returns operational
detail (error messages, stack traces from client-error reports) but no
secrets/credentials, consistent with the existing exposure, not a new
category of risk."""


class ClientErrorIn(BaseModel):
    message: str
    stack: str | None = None
    url: str | None = None
    context: dict | None = None


@router.get("/status")
def debug_status(db: Session = Depends(get_db)):
    profile = db.get(InterestProfile, 1)
    last_rerank_event = db.scalar(
        select(SystemEvent)
        .where(
            SystemEvent.category == "rerank",
            or_(*(SystemEvent.message.like(f"{prefix}%") for prefix in _TERMINAL_RERANK_PREFIXES)),
        )
        .order_by(SystemEvent.created_at.desc())
        .limit(1)
    )
    # Already polled every 10s by the frontend regardless of which tab is
    # open (see App.tsx) -- reusing this endpoint for the footer's "last
    # updated" timestamp means no separate fetch needed just for that.
    last_ingest_run = db.scalar(select(IngestRun).order_by(IngestRun.started_at.desc()).limit(1))
    return {
        "demo_mode": DEMO_MODE,
        "rerank": get_rerank_status(),
        "last_rerank": (
            {
                "at": last_rerank_event.created_at.isoformat(),
                "level": last_rerank_event.level,
                "message": last_rerank_event.message,
                "detail": last_rerank_event.detail,
            }
            if last_rerank_event is not None
            else None
        ),
        "last_ingest": (
            {"at": last_ingest_run.started_at.isoformat(), "fetched": last_ingest_run.fetched}
            if last_ingest_run is not None
            else None
        ),
        "profile": {
            "updated_at": profile.updated_at.isoformat() if profile else None,
            "category_count": len(profile.categories) if profile else 0,
            "keyword_count": len(profile.keywords) if profile else 0,
        },
    }


@router.get("/events")
def debug_events(
    category: str | None = None,
    level: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = select(SystemEvent).order_by(SystemEvent.created_at.desc())
    if category:
        q = q.where(SystemEvent.category == category)
    if level:
        q = q.where(SystemEvent.level == level)
    rows = db.scalars(q.limit(min(limit, 200))).all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "level": r.level,
            "category": r.category,
            "message": r.message,
            "detail": r.detail,
        }
        for r in rows
    ]


@router.post("/client-error")
def report_client_error(payload: ClientErrorIn, db: Session = Depends(get_db)):
    log_event(
        db,
        "frontend",
        payload.message,
        level="error",
        detail={"stack": payload.stack, "url": payload.url, **(payload.context or {})},
    )
    return {"ok": True}
