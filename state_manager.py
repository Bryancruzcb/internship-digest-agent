import sqlite3
import json
import uuid
import logging
from datetime import datetime, timedelta
import config

logger = logging.getLogger("StatefulAgent.StateManager")

TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _now() -> str:
    return datetime.now().strftime(TIME_FMT)


def _stale_cutoff() -> str:
    return (datetime.now() - timedelta(minutes=config.STALE_RUN_MINUTES)).strftime(TIME_FMT)


def _connect():
    return sqlite3.connect(config.DB_PATH)


def init_db():
    """Initializes the database schema if it doesn't exist."""
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            run_id TEXT PRIMARY KEY,
            created_at TEXT,
            updated_at TEXT,
            status TEXT,
            current_step TEXT,
            state_data TEXT,
            retry_count INTEGER,
            last_error TEXT
        )
    """)

    # Audit trail / step logs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS step_logs (
            log_id TEXT PRIMARY KEY,
            run_id TEXT,
            step_name TEXT,
            timestamp TEXT,
            status TEXT,
            details TEXT,
            FOREIGN KEY (run_id) REFERENCES agent_runs(run_id)
        )
    """)

    # Postings that have already appeared in a published digest
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seen_postings (
            posting_id TEXT PRIMARY KEY,
            first_seen_at TEXT,
            company TEXT,
            title TEXT,
            url TEXT
        )
    """)

    conn.commit()
    conn.close()


def create_run() -> str:
    """Creates a new execution run checkpoint and returns its run_id."""
    init_db()
    run_id = str(uuid.uuid4())
    now = _now()

    conn = _connect()
    conn.execute(
        "INSERT INTO agent_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, now, now, "pending", "START", json.dumps({}), 0, "")
    )
    conn.commit()
    conn.close()
    return run_id


def load_run(run_id: str):
    """Loads the status and data checkpoint of a specific run."""
    conn = _connect()
    row = conn.execute(
        "SELECT run_id, created_at, updated_at, status, current_step, state_data, retry_count, last_error "
        "FROM agent_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    conn.close()

    if not row:
        return None

    return {
        "run_id": row[0],
        "created_at": row[1],
        "updated_at": row[2],
        "status": row[3],
        "current_step": row[4],
        "state_data": json.loads(row[5]),
        "retry_count": row[6],
        "last_error": row[7],
    }


def update_run(run_id: str, status: str, current_step: str, state_data: dict,
               retry_count: int, last_error: str = ""):
    """Updates the checkpoint. current_step always names the NEXT step to
    execute (or the one in progress), never a step that already finished."""
    conn = _connect()
    conn.execute(
        """
        UPDATE agent_runs
        SET status = ?, current_step = ?, state_data = ?, retry_count = ?, last_error = ?, updated_at = ?
        WHERE run_id = ?
        """,
        (status, current_step, json.dumps(state_data), retry_count, last_error, _now(), run_id)
    )
    conn.commit()
    conn.close()


def claim_run(run_id: str) -> bool:
    """Atomically takes ownership of a run before executing it. Fails if the
    run is terminal or a live process already owns it (fresh heartbeat)."""
    init_db()
    conn = _connect()
    cursor = conn.execute(
        """
        UPDATE agent_runs SET status = 'running', updated_at = ?
        WHERE run_id = ?
          AND (status IN ('pending', 'failed_retry')
               OR (status = 'running' AND updated_at < ?))
        """,
        (_now(), run_id, _stale_cutoff())
    )
    conn.commit()
    claimed = cursor.rowcount == 1
    conn.close()
    return claimed


def log_step(run_id: str, step_name: str, status: str, details: str = ""):
    """Appends an event to the audit logs for visibility/debugging."""
    conn = _connect()
    conn.execute(
        "INSERT INTO step_logs VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), run_id, step_name, _now(), status, details)
    )
    conn.commit()
    conn.close()


def get_resumable_run():
    """Finds the most recent run that can still make progress: pending,
    paused for retry, or crashed mid-run (stale 'running' heartbeat).

    Terminally 'failed' runs are excluded on purpose: they exhausted their
    retries, so resuming them would retry forever and block new runs. Fresh
    'running' runs belong to a live process and are not resumable either.
    """
    init_db()
    conn = _connect()
    row = conn.execute(
        """
        SELECT run_id FROM agent_runs
        WHERE status IN ('pending', 'failed_retry')
           OR (status = 'running' AND updated_at < ?)
        ORDER BY created_at DESC LIMIT 1
        """,
        (_stale_cutoff(),)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def has_active_run() -> bool:
    """True if a run is being executed right now by a live process."""
    init_db()
    conn = _connect()
    count = conn.execute(
        "SELECT COUNT(*) FROM agent_runs WHERE status = 'running' AND updated_at >= ?",
        (_stale_cutoff(),)
    ).fetchone()[0]
    conn.close()
    return count > 0


def filter_unseen(postings: list) -> list:
    """Returns only postings that have never appeared in a published digest."""
    init_db()
    conn = _connect()
    seen = {row[0] for row in conn.execute("SELECT posting_id FROM seen_postings")}
    conn.close()
    return [p for p in postings if p["id"] not in seen]


def mark_seen(postings: list):
    """Records postings as published. Idempotent, so re-running PUBLISH after
    a crash is safe."""
    if not postings:
        return
    init_db()
    conn = _connect()
    conn.executemany(
        "INSERT OR IGNORE INTO seen_postings VALUES (?, ?, ?, ?, ?)",
        [(p["id"], _now(), p.get("company", ""), p.get("title", ""), p.get("url", ""))
         for p in postings]
    )
    conn.commit()
    conn.close()
