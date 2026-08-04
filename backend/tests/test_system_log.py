from app.models import SystemEvent
from app.system_log import log_event


def test_log_event_persists_a_row(db_session):
    log_event(db_session, "rerank", "rerank started", detail={"trigger": "refresh"})

    rows = db_session.query(SystemEvent).all()
    assert len(rows) == 1
    assert rows[0].category == "rerank"
    assert rows[0].level == "info"
    assert rows[0].message == "rerank started"
    assert rows[0].detail == {"trigger": "refresh"}


def test_log_event_defaults_to_info_level(db_session):
    log_event(db_session, "ingest", "ingest finished")

    assert db_session.query(SystemEvent).one().level == "info"


def test_log_event_respects_explicit_level(db_session):
    log_event(db_session, "rerank", "rerank failed", level="error")

    assert db_session.query(SystemEvent).one().level == "error"


def test_log_event_with_no_db_does_not_raise():
    # The scheduled-job / background-task entry points sometimes call this
    # before a session exists -- must degrade to logger-only, not crash the
    # caller.
    log_event(None, "ingest", "no db available")
