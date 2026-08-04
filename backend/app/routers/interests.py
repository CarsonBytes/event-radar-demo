import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingest_job import schedule_rerank
from app.interests import parse_interests
from app.models import InterestProfile
from app.schemas import InterestProfileIn, InterestProfileOut
from app.system_log import log_event

router = APIRouter(prefix="/interests", tags=["interests"])


@router.get("", response_model=InterestProfileOut)
def get_interests(db: Session = Depends(get_db)):
    profile = db.get(InterestProfile, 1)
    if profile is None:
        return InterestProfileOut(
            raw_text="", categories=[], keywords=[], excluded_keywords=[], weights={}, updated_at=dt.datetime.utcnow()
        )
    return profile


@router.post("", response_model=InterestProfileOut)
def set_interests(payload: InterestProfileIn, db: Session = Depends(get_db)):
    parsed = parse_interests(payload.raw_text, db)
    # Literal, not LLM-parsed -- see models.py::InterestProfile.excluded_keywords.
    excluded = [k.strip().lower() for k in payload.excluded_keywords if k.strip()]

    profile = db.get(InterestProfile, 1)
    if profile is None:
        profile = InterestProfile(id=1, weights={})
        db.add(profile)

    profile.raw_text = payload.raw_text
    profile.categories = parsed.categories
    profile.keywords = parsed.keywords
    profile.excluded_keywords = excluded

    db.commit()
    db.refresh(profile)

    log_event(
        db,
        "interest",
        f"interests saved: {len(parsed.categories)} categories, {len(parsed.keywords)} keywords, {len(excluded)} excluded",
        detail={
            "raw_text": payload.raw_text,
            "categories": parsed.categories,
            "keywords": parsed.keywords,
            "excluded_keywords": excluded,
        },
    )

    # Interests just changed -- automatically rerank every event against the
    # new profile in the background (no more "hit Refresh to re-rank"; a
    # forgotten manual step was the main reason stale/wrong-looking scores
    # from a previous profile used to linger on screen). Debounced (see
    # schedule_rerank) so rapid edit-then-re-save bursts collapse into one
    # rerank instead of one per save.
    schedule_rerank(trigger="interest_save")
    return profile
