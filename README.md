# Stateful Autonomous Worker Agent (Weekly Scaffold)

This project implements a scheduled, stateful, multi-step agent with built-in checkpoint persistence, error retries, and failure recovery.

---

## Architecture Design

*   **Checkpoint Persistence**: The agent tracks its variables, accumulated data, and last successfully completed step inside a SQLite database (`agent_state.db`).
*   **Self-Healing Recovery**: If the system crashes, runs out of memory, or fails midway through execution, the scheduler daemon automatically detects the incomplete run upon restart and resumes from the exact failing step.
*   **Retry & Failure Throttle**: Each step is run inside an error boundary. If a step fails, it increments a database retry counter and retries up to 3 times before pausing/halting the entire run to prevent API cost burn loops.

---

## File Structure

*   `config.py` - Sets up directory paths, DB name, model provider selection, and loads `.env`.
*   `state_manager.py` - Connects to SQLite and handles saving/loading of agent status and step checkpoints.
*   `tools.py` - Simulates web searches, article compilation, and file publishing.
*   `agent.py` - The core step pipeline (RESEARCH -> ANALYZE -> COMPILE -> PUBLISH) and execution engine.
*   `scheduler.py` - Starts an async background daemon scheduler (`AsyncIOScheduler`) to trigger the agent loop on a recurring interval.
*   `run_agent.py` - CLI tool to trigger a one-off execution.

---

## Setup & Running

1.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Add environment keys**:
    Copy `env.example` to `.env` and fill in `GEMINI_API_KEY`.

3.  **Run a one-off run (or resume a failing run)**:
    ```bash
    python run_agent.py
    ```

4.  **Run the background daemon scheduler**:
    ```bash
    python scheduler.py
    ```
