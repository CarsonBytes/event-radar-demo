from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Feedback, SavedEvent


def attach_user_state(events: list[Event], db: Session) -> None:
    """Sets .user_signal and .saved on each Event in place -- both are
    request-scoped (not real columns; see EventOut.user_signal/.saved),
    computed here so both /api/events and /api/saved return the same shape.
    """
    event_ids = [e.id for e in events]

    # Feedback is an append-only log (Insights' precision stats read every
    # row ever cast) -- "your current vote" is just the *latest* row per
    # event. "none" rows (an un-vote) are kept in the log too but don't
    # count as up/down here.
    latest_signal: dict[int, str] = {}
    if event_ids:
        rows = db.scalars(
            select(Feedback).where(Feedback.event_id.in_(event_ids)).order_by(Feedback.created_at)
        )
        for fb in rows:
            latest_signal[fb.event_id] = fb.signal

    saved_ids: set[int] = set()
    if event_ids:
        saved_ids = set(
            db.scalars(select(SavedEvent.event_id).where(SavedEvent.event_id.in_(event_ids)))
        )

    for e in events:
        sig = latest_signal.get(e.id)
        e.user_signal = sig if sig in ("up", "down") else None
        e.saved = e.id in saved_ids
