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
DEFAULT_MODEL = os.getenv("AGENT_MODEL", "gemini-2.5-flash")

# Community-maintained internship feed (SimplifyJobs). A new repo is created
# each season — point LISTINGS_URL and FILTER_TERM at Summer2027-Internships
# once it exists (usually published around August-September).
LISTINGS_URL = os.getenv(
    "LISTINGS_URL",
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
)
FILTER_TERM = os.getenv("FILTER_TERM", "Summer 2026")

# Weekly schedule. Setting AGENT_INTERVAL_SECONDS switches to a fast interval
# for demos and local testing.
SCHEDULE_DAY_OF_WEEK = os.getenv("SCHEDULE_DAY_OF_WEEK", "mon")
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "9"))
_interval = os.getenv("AGENT_INTERVAL_SECONDS")
AGENT_INTERVAL_SECONDS = int(_interval) if _interval else None

# A 'running' run whose heartbeat is older than this is considered crashed
# and becomes eligible for resume by the next cycle.
STALE_RUN_MINUTES = int(os.getenv("STALE_RUN_MINUTES", "30"))
