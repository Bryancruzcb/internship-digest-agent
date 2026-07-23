import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "agent_state.db"
REPORTS_DIR = BASE_DIR / "reports"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

DEFAULT_MODEL_PROVIDER = os.getenv("AGENT_PROVIDER", "gemini").lower()
# The -latest alias tracks whatever Google's current flash-lite model is, so
# the default can never rot into a retired model id (the original scaffold
# shipped with exactly that bug).
DEFAULT_MODEL = os.getenv("AGENT_MODEL", "gemini-flash-lite-latest")

# Community-maintained internship feed (SimplifyJobs). A new repo is created
# each season — point LISTINGS_URL and FILTER_TERM at Summer2027-Internships
# once it exists (usually published around August-September).
LISTINGS_URL = os.getenv(
    "LISTINGS_URL",
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
)
# Comma-separated term tags to keep. FILTER_TERM (singular) is honored for
# backward compatibility. The one SimplifyJobs repo carries all seasons, so
# rolling to a new cycle is just an edit here — no repo switch needed.
_terms = (os.getenv("FILTER_TERMS") or os.getenv("FILTER_TERM")
          or "Summer 2026,Fall 2026,Summer 2027")
FILTER_TERMS = [t.strip() for t in _terms.split(",") if t.strip()]

# Company watchlist: per-company ATS endpoints polled directly (see sources.py).
WATCHLIST_PATH = Path(os.getenv("WATCHLIST_PATH", BASE_DIR / "watchlist.json"))

# Handshake saved-search alert emails via IMAP (disabled until both are set).
HANDSHAKE_IMAP_USER = os.getenv("HANDSHAKE_IMAP_USER")
HANDSHAKE_IMAP_PASSWORD = os.getenv("HANDSHAKE_IMAP_PASSWORD")
HANDSHAKE_IMAP_HOST = os.getenv("HANDSHAKE_IMAP_HOST", "imap.gmail.com")
HANDSHAKE_IMAP_FOLDER = os.getenv("HANDSHAKE_IMAP_FOLDER", "INBOX")

# Weekly schedule. Setting AGENT_INTERVAL_SECONDS switches to a fast interval
# for demos and local testing.
SCHEDULE_DAY_OF_WEEK = os.getenv("SCHEDULE_DAY_OF_WEEK", "mon")
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "9"))
_interval = os.getenv("AGENT_INTERVAL_SECONDS")
AGENT_INTERVAL_SECONDS = int(_interval) if _interval else None

# A 'running' run whose heartbeat is older than this is considered crashed
# and becomes eligible for resume by the next cycle.
STALE_RUN_MINUTES = int(os.getenv("STALE_RUN_MINUTES", "30"))
