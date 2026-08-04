from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ask import ask
from app.db import get_db
from app.models import AskLog
from app.schemas import AskHistoryOut, AskIn, AskOut
from app.system_log import log_event

router = APIRouter(prefix="/ask", tags=["ask"])

# A public, unauthenticated endpoint -- capped rather than caller-controlled
# without limit, same reasoning as every other list endpoint in this app.
_MAX_HISTORY_LIMIT = 50


@router.post("", response_model=AskOut)
def ask_question(payload: AskIn, db: Session = Depends(get_db)):
    query = payload.query.strip()
    if not query:
        return AskOut(answer="")

    answer, quota_exhausted, referenced_events = ask(db, query)
    log_event(
        db,
        "ask",
        f"asked: {query[:80]}",
        level="info" if answer else "error",
        detail={"query": query, "answered": bool(answer), "quota_exhausted": quota_exhausted},
    )
    return AskOut(answer=answer, quota_exhausted=quota_exhausted, referenced_events=referenced_events)


@router.get("/history", response_model=AskHistoryOut)
def ask_history(limit: int = Query(default=20, le=_MAX_HISTORY_LIMIT, ge=1), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(AskLog).order_by(AskLog.created_at.desc()).limit(limit)))
    return AskHistoryOut(items=rows)
