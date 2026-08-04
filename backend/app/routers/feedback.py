from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Event, Feedback, InterestProfile
from app.ranking import apply_feedback, persist_feedback_weights
from app.schemas import FeedbackIn
from app.system_log import log_event

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("")
def submit_feedback(payload: FeedbackIn, db: Session = Depends(get_db)):
    # "none" un-votes (clicking an already-active thumb again) -- it's
    # still logged, just excluded from up/down tallies (see events.py's
    # latest-signal lookup and insights.py's precision stats), so the
    # feedback history stays a complete append-only record either way.
    if payload.signal not in ("up", "down", "none"):
        raise HTTPException(400, "signal must be 'up', 'down', or 'none'")

    event = db.get(Event, payload.event_id)
    if event is None:
        raise HTTPException(404, "event not found")

    db.add(Feedback(event_id=event.id, signal=payload.signal))

    if payload.signal in ("up", "down"):
        profile = db.get(InterestProfile, 1)
        if profile is not None:
            # apply_feedback runs against a transient (never db.add'ed)
            # copy, not the session-tracked `profile` object -- see
            # persist_feedback_weights for why the actual write needs to
            # bypass the ORM's normal attribute-assignment path.
            scratch = InterestProfile(weights=dict(profile.weights or {}))
            apply_feedback(scratch, event, payload.signal)
            persist_feedback_weights(db, profile.id, scratch.weights)

    db.commit()
    log_event(db, "feedback", f"{payload.signal} on event {event.id} ({event.title[:60]})", detail={"event_id": event.id, "signal": payload.signal})
    return {"ok": True}
