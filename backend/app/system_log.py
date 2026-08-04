import logging

from sqlalchemy.orm import Session

from app.models import SystemEvent

logger = logging.getLogger(__name__)

_LOG_FNS = {"error": logger.error, "warning": logger.warning}


def log_event(
    db: Session | None,
    category: str,
    message: str,
    level: str = "info",
    detail: dict | None = None,
) -> None:
    """Writes to both the DB (queryable via GET /api/debug/events) and the
    normal Python logger (still shows up in deploy/logs/backend-out.log --
    this doesn't replace that, it makes the same events queryable without
    grepping a text file over SSH/RDP). Best-effort: a logging failure must
    never break the request that triggered it."""
    _LOG_FNS.get(level, logger.info)("[%s] %s %s", category, message, detail or "")

    if db is None:
        return
    try:
        db.add(SystemEvent(level=level, category=category, message=message, detail=detail))
        db.commit()
    except Exception:
        logger.exception("log_event: failed to persist system event (category=%s)", category)
        db.rollback()
