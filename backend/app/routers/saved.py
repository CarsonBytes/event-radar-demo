from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.event_state import attach_user_state
from app.models import Event, SavedEvent
from app.schemas import EventOut

router = APIRouter(prefix="/saved", tags=["saved"])


@router.get("", response_model=list[EventOut])
def list_saved(db: Session = Depends(get_db)):
    event_ids = list(db.scalars(select(SavedEvent.event_id)))
    if not event_ids:
        return []
    events = list(db.scalars(select(Event).where(Event.id.in_(event_ids))))
    attach_user_state(events, db)
    events.sort(key=lambda e: e.start)
    return events


@router.post("/{event_id}")
def save_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(404, "event not found")
    existing = db.scalar(select(SavedEvent).where(SavedEvent.event_id == event_id))
    if existing is None:
        db.add(SavedEvent(event_id=event_id))
        db.commit()
    return {"ok": True}


@router.delete("/{event_id}")
def unsave_event(event_id: int, db: Session = Depends(get_db)):
    existing = db.scalar(select(SavedEvent).where(SavedEvent.event_id == event_id))
    if existing is not None:
        db.delete(existing)
        db.commit()
    return {"ok": True}
