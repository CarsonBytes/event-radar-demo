from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.event_state import attach_user_state
from app.models import Event
from app.schemas import EventOut

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventOut])
def list_events(
    status: str | None = Query(None, pattern="^(upcoming|ongoing|past|far_future)$"),
    db: Session = Depends(get_db),
):
    events = list(db.scalars(select(Event)).all())
    if status:
        events = [e for e in events if e.status == status]

    attach_user_state(events, db)
    events.sort(key=lambda e: (-(e.llm_score if e.llm_score is not None else -1), -e.raw_score, e.start))
    return events


# Lets a caller that only has an event id -- the Ask feature's referenced
# events, in particular, which don't come from any already-loaded list on
# the frontend -- fetch that one event's full card data on demand, without
# needing to know which status/tab it'd otherwise show up under.
@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    attach_user_state([event], db)
    return event
