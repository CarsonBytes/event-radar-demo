import os
from pathlib import Path

from dotenv import load_dotenv

# Anchored to backend/.env, not the process cwd -- python-dotenv's default
# load_dotenv() searches upward from cwd, which silently finds nothing (and
# leaves every key below empty, no error) when uvicorn is launched from a
# different directory, e.g. a dev-server tool invoking it from its own cwd
# rather than --app-dir.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# Second chatanywhere.tech key, tried automatically once OPENAI_API_KEY's
# daily quota is exhausted -- see app/llm_client.py's key-rotation logic.
# Optional: blank disables rotation, same behavior as before it existed.
OPENAI_API_KEY_FALLBACK = os.environ.get("OPENAI_API_KEY_FALLBACK", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "")

# DeepSeek fallback -- used once the shared chatanywhere.tech quota (200/day,
# shared with quant + study) is exhausted. See app/llm_client.py's
# provider_decision(). Optional: without a key set, this project just stays
# on chatanywhere/OpenAI regardless of what the shared decision says.
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

TICKETMASTER_API_KEY = os.environ.get("TICKETMASTER_API_KEY", "")
PREDICTHQ_API_KEY = os.environ.get("PREDICTHQ_API_KEY", "")
EVENTBRITE_TOKEN = os.environ.get("EVENTBRITE_TOKEN", "")

# Automatic background ingest — 0 disables the scheduler (manual "Refresh" only).
INGEST_INTERVAL_HOURS = float(os.environ.get("INGEST_INTERVAL_HOURS", "12"))

# Runs a second, independent deployment of this same app restricted to
# urbtix only (data.gov.hk's open-data feed, explicitly licensed for reuse
# -- confirmed directly against data.gov.hk's own Terms of Use, unlike
# hktdc.com/art-mate.net/expoking.com.hk which have no such license). Set
# as a real process environment variable by the demo instance's launch
# script, not backend/.env -- python-dotenv's load_dotenv() (below) doesn't
# override an already-set env var by default, so the same shared .env file
# (API keys, Supabase creds) works unmodified for both deployments; only
# what actually needs to differ (this flag, DATABASE_URL) is set per-launch.
DEMO_MODE = os.environ.get("DEMO_MODE", "") == "1"

# Optional: known daily request cap of the configured LLM key, purely for
# the "X / cap" display in Insights — not enforced, just visibility.
LLM_DAILY_CAP = int(os.environ["LLM_DAILY_CAP"]) if os.environ.get("LLM_DAILY_CAP") else None

# Shared cross-project LLM usage ledger (Supabase `llm_calls` table, same one
# D:\adaptive_study_platform already logs to). Optional — if unset, usage is
# only tracked locally for this project. See app/llm_logging.py.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# Anchored to the backend/ directory (not the process cwd) so the db file
# lands in the same place regardless of how/where uvicorn is launched from.
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'event_radar.db'}")
