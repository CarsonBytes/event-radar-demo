import datetime as dt
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingest_job import _fetch_and_upsert, end_ingest, schedule_rerank, try_begin_ingest
from app.models import IngestRun
from app.schemas import IngestSummary
from app.system_log import log_event

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("", response_model=IngestSummary)
def trigger_ingest(db: Session = Depends(get_db)):
    """Fetches/upserts synchronously (fast, no LLM cost) and returns right
    away. Reranking runs afterward via schedule_rerank's debounced timer --
    a full-catalog rerank is several sequential LLM calls and can take over
    a minute, too long to hold this HTTP request (and Cloudflare's proxy)
    open for. `ranked` in the response is always 0 here; check back after a
    bit (or the Insights tab) to see it land.

    409 if another ingest (the scheduled run, or another concurrent
    Refresh click) is still mid-flight -- serialized rather than allowed to
    overlap, since SQLite only permits one writer and an overlapping run
    used to die on `database is locked`."""
    if not try_begin_ingest():
        raise HTTPException(status_code=409, detail="An ingest is already running -- try again shortly.")
    try:
        started_at = dt.datetime.utcnow()
        start_perf = time.perf_counter()
        fetched, new, updated, duplicates = _fetch_and_upsert(db)
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        db.add(
            IngestRun(started_at=started_at, duration_ms=duration_ms, fetched=fetched, new=new, updated=updated, ranked=0)
        )
        db.commit()
        log_event(
            db,
            "ingest",
            f"refresh triggered: fetched={fetched} new={new} updated={updated} duplicates_skipped={duplicates}",
            detail={
                "trigger": "refresh", "fetched": fetched, "new": new, "updated": updated, "duplicates_skipped": duplicates,
            },
        )
    finally:
        end_ingest()

    schedule_rerank(trigger="refresh")
    return IngestSummary(fetched=fetched, new=new, updated=updated, ranked=0)
