import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "agent_state.db"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

DEFAULT_MODEL_PROVIDER = os.getenv("AGENT_PROVIDER", "gemini").lower()
DEFAULT_MODEL = os.getenv("AGENT_MODEL", "gemini-1.5-flash")

# Schedule settings (e.g. cron string or interval in seconds)
# For demo/test purposes, default to running every 60 seconds
AGENT_INTERVAL_SECONDS = int(os.getenv("AGENT_INTERVAL_SECONDS", "60"))
