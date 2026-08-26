"""Tests for GET /api/events/search and the created_at exposure.

Written connector-agnostically (in-memory DB, no network) so this file
collects and passes identically in the private repo and the public demo
repo, where the non-urbtix connectors don't exist on disk."""

import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.models import Event
from app.routers.events import router as events_router


@pytest.fixture
def db_session():
    # Not conftest's db_session: TestClient serves requests on another
    # thread, and plain in-memory sqlite objects are thread-bound. A
    # StaticPool keeps ONE connection alive across threads so both this
    # fixture and the endpoint see the same database.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    app = FastAPI()
    app.include_router(events_router)
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def _event(db, id: int, title="Test Event", title_native=None, description="", category="Music", venue=""):
    ev = Event(
        id=id,
        source="urbtix",
        source_id=str(id),
        source_url="",
        title=title,
        title_native=title_native,
        description=description,
        category=category,
        start=dt.datetime.utcnow(),
        venue_name=venue,
        location="",
    )
    db.add(ev)
    return ev


class TestSearchEndpoint:
    def test_matches_title(self, db_session, client):
        _event(db_session, 1, title="Spider-Man: Brand New Day")
        _event(db_session, 2, title="An unrelated concert")
        db_session.commit()

        res = client.get("/events/search", params={"q": "spider"})
        assert res.status_code == 200
        hits = res.json()
        assert len(hits) == 1
        assert hits[0]["title"] == "Spider-Man: Brand New Day"
        # Case-insensitive for ASCII: query lowercase, title capitalized.
        assert hits[0]["id"] == 1

    def test_matches_native_title_and_description_and_venue(self, db_session, client):
        _event(db_session, 3, title="English title", title_native="蜘蛛俠：全新一天")
        _event(db_session, 4, description="something about 蜘蛛 here")
        _event(db_session, 5, venue="香港大會堂")
        db_session.commit()

        res = client.get("/events/search", params={"q": "蜘蛛"})
        ids = {e["id"] for e in res.json()}
        assert ids == {3, 4}

        res = client.get("/events/search", params={"q": "大會堂"})
        assert {e["id"] for e in res.json()} == {5}

    def test_no_match_returns_empty_list(self, db_session, client):
        _event(db_session, 6, title="Jazz night")
        db_session.commit()
        res = client.get("/events/search", params={"q": "zeppelin"})
        assert res.status_code == 200
        assert res.json() == []

    def test_query_too_short_is_rejected(self, client):
        assert client.get("/events/search", params={"q": "s"}).status_code == 422
        assert client.get("/events/search").status_code == 422

    def test_limit_is_respected_and_results_ranked_by_score(self, db_session, client):
        for i in range(10):
            _event(db_session, 100 + i, title=f"Concert series part {i}")
        # Give event 105 an LLM score so it must rank first regardless of id order.
        db_session.get(Event, 105).llm_score = 90.0
        db_session.commit()

        res = client.get("/events/search", params={"q": "concert", "limit": 3})
        hits = res.json()
        assert len(hits) == 3
        assert hits[0]["id"] == 105


class TestCreatedAtExposed:
    def test_list_events_includes_created_at(self, db_session, client):
        _event(db_session, 20)
        db_session.commit()
        body = client.get("/events").json()
        assert len(body) == 1
        assert body[0]["created_at"]

    def test_get_event_includes_created_at(self, db_session, client):
        _event(db_session, 21)
        db_session.commit()
        body = client.get("/events/21").json()
        assert body["created_at"]
