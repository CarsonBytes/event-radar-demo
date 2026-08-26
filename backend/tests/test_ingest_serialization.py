"""Tests for ingest-run serialization (the _ingest_lock).

SQLite allows one writer at a time -- a manual POST /api/ingest landing
while a scheduled run is mid-flight used to die on
sqlite3.OperationalError: database is locked. Both entry points now
acquire the same non-blocking lock; these tests pin that behavior.
Connector-agnostic, so it collects in the public demo repo too."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.ingest_job as ingest_job
from app.db import get_db
from app.routers.ingest import router as ingest_router


class TestIngestLockPrimitive:
    def test_acquire_then_release(self):
        assert ingest_job.try_begin_ingest() is True
        # A second acquire while held must fail fast (non-blocking).
        assert ingest_job.try_begin_ingest() is False
        ingest_job.end_ingest()
        # Released -- acquirable again.
        assert ingest_job.try_begin_ingest() is True
        ingest_job.end_ingest()

    def test_reentrant_acquire_is_refused(self):
        """Same-thread double-acquire must also be refused: the point is
        'only one ingest anywhere', not 'one per thread'."""
        assert ingest_job.try_begin_ingest() is True
        assert ingest_job.try_begin_ingest() is False
        ingest_job.end_ingest()


class TestTriggerEndpoint409:
    def test_second_concurrent_refresh_gets_409(self, db_session):
        app = FastAPI()
        app.include_router(ingest_router)
        app.dependency_overrides[get_db] = lambda: db_session
        client = TestClient(app)

        # Simulate another run (e.g. the scheduled job) already holding
        # the lock -- the endpoint must reject with 409 before touching
        # any connector or writing anything.
        assert ingest_job.try_begin_ingest() is True
        try:
            res = client.post("/ingest")
            assert res.status_code == 409
            assert "already running" in res.json()["detail"]
        finally:
            ingest_job.end_ingest()
