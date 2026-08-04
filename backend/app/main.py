import datetime as dt
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import BACKEND_DIR, INGEST_INTERVAL_HOURS
from app.db import Base, SessionLocal, engine, ensure_schema
from app.ingest_job import run_ingest_job
from app.models import Event, IngestRun
from app.routers import ask, debug, events, feedback, ingest, insights, interests, saved

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)
ensure_schema()

scheduler = BackgroundScheduler()


_MIN_GAP_BEFORE_IMMEDIATE_RUN = dt.timedelta(minutes=5)


def _seconds_until_first_run() -> float:
    """0 for a genuine cold start (run immediately, as before). A positive
    delay if an ingest already ran recently, so the LLM rerank it includes
    isn't re-fired on every `uvicorn --reload` restart during development --
    each one used to burn a real call against the shared 200/day quota purely
    from editing files, independent of the 12h production interval."""
    db = SessionLocal()
    try:
        last = db.query(IngestRun).order_by(IngestRun.started_at.desc()).first()
    finally:
        db.close()
    if last is None:
        return 0.0
    elapsed = dt.datetime.utcnow() - last.started_at
    remaining = _MIN_GAP_BEFORE_IMMEDIATE_RUN - elapsed
    return max(0.0, remaining.total_seconds())


@asynccontextmanager
async def lifespan(app: FastAPI):
    if INGEST_INTERVAL_HOURS > 0:
        delay = _seconds_until_first_run()
        scheduler.add_job(
            run_ingest_job,
            trigger=IntervalTrigger(hours=INGEST_INTERVAL_HOURS),
            id="auto_ingest",
            max_instances=1,
            coalesce=True,
            next_run_time=dt.datetime.now() + dt.timedelta(seconds=delay),
        )
        scheduler.start()
        if delay:
            logger.info(
                "Automatic ingest scheduled every %sh (first run delayed %.0fs -- "
                "an ingest ran within the last %s, likely a dev-server reload)",
                INGEST_INTERVAL_HOURS, delay, _MIN_GAP_BEFORE_IMMEDIATE_RUN,
            )
        else:
            logger.info("Automatic ingest scheduled every %sh", INGEST_INTERVAL_HOURS)
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Event Radar", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")
api.include_router(events.router)
api.include_router(interests.router)
api.include_router(feedback.router)
api.include_router(ingest.router)
api.include_router(insights.router)
api.include_router(saved.router)
api.include_router(debug.router)
api.include_router(ask.router)
app.include_router(api)


@app.get("/api/health")
def health():
    """Deliberately touches the DB (a cheap COUNT), not just a static 200 --
    the 2026-07-30 incident this backs was a process that kept accepting
    TCP connections and answering requests fine, but every DB-backed route
    (i.e. everything real) 500'd. A static health check would have reported
    "healthy" the entire ~40h it was actually broken; this one fails the
    same way the real routes did."""
    db = SessionLocal()
    try:
        event_count = db.query(Event).count()
    finally:
        db.close()
    return {"ok": True, "event_count": event_count}


# 2026-07-30: StaticFiles sends no Cache-Control at all by default, which
# left index.html (the SPA shell) subject to browser heuristic caching --
# confirmed live, a completely fresh browser profile with no prior history
# for this origin still served a JS bundle hash from *before* a same-day
# deploy, and only a hard cache-bust broke through it. A real returning
# visitor (this app's actual daily-use pattern) would hit the identical
# problem after every future frontend deploy, not just this one. Fixed by
# explicitly forcing revalidation on the shell -- cheap, since a 304 still
# beats a full refetch -- while the hashed /assets/* files (Vite renames
# them on any content change) are safe to cache aggressively forever.
@app.middleware("http")
async def _cache_control_for_frontend(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif not path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# Production: serve the built frontend (frontend/dist) from this same process
# so a single port needs to be exposed/tunneled. In dev, the Vite dev server
# handles the frontend instead and this directory won't exist.
_frontend_dist = BACKEND_DIR.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
