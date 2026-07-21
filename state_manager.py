import sqlite3
import json
import uuid
import time
import logging
import config

logger = logging.getLogger("StatefulAgent.StateManager")

def init_db():
    """Initializes the database schema if it doesn't exist."""
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    # Run states table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            run_id TEXT PRIMARY KEY,
            timestamp TEXT,
            status TEXT,
            current_step TEXT,
            state_data TEXT,
            retry_count INTEGER,
            last_error TEXT
        )
    """)
    
    # Audit trail / Step logs table
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
    
    conn.commit()
    conn.close()

def create_run() -> str:
    """Creates a new execution run checkpoint and returns its run_id."""
    init_db()
    run_id = str(uuid.uuid4())
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO agent_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, timestamp, "pending", "START", json.dumps({}), 0, "")
    )
    
    conn.commit()
    conn.close()
    return run_id

def load_run(run_id: str) -> dict:
    """Loads the status and data checkpoint of a specific run."""
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
        
    return {
        "run_id": row[0],
        "timestamp": row[1],
        "status": row[2],
        "current_step": row[3],
        "state_data": json.loads(row[4]),
        "retry_count": row[5],
        "last_error": row[6]
    }

def update_run(run_id: str, status: str, current_step: str, state_data: dict, retry_count: int, last_error: str = ""):
    """Updates the database checkpoint state of the agent run."""
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        """
        UPDATE agent_runs 
        SET status = ?, current_step = ?, state_data = ?, retry_count = ?, last_error = ?
        WHERE run_id = ?
        """,
        (status, current_step, json.dumps(state_data), retry_count, last_error, run_id)
    )
    
    conn.commit()
    conn.close()

def log_step(run_id: str, step_name: str, status: str, details: str = ""):
    """Appends an event to the audit logs for visibility/debugging."""
    log_id = str(uuid.uuid4())
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO step_logs VALUES (?, ?, ?, ?, ?, ?)",
        (log_id, run_id, step_name, timestamp, status, details)
    )
    
    conn.commit()
    conn.close()

def get_latest_incomplete_run() -> str:
    """Finds the most recent run that can still make progress (pending/running/failed_retry).

    Terminally 'failed' runs are excluded on purpose: they already exhausted
    their retries, so resuming them would retry forever and block new runs.
    """
    init_db()
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT run_id FROM agent_runs WHERE status NOT IN ('completed', 'failed') ORDER BY timestamp DESC LIMIT 1"
    )
    row = cursor.fetchone()
    conn.close()
    
    return row[0] if row else None
