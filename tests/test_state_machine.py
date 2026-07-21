import sqlite3

import agent
import config
import state_manager


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test_state.db")


def _set_updated_at(run_id, value):
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("UPDATE agent_runs SET updated_at = ? WHERE run_id = ?", (value, run_id))
    conn.commit()
    conn.close()


def _fake_steps(monkeypatch, handlers):
    monkeypatch.setattr(agent, "STEP_ORDER", list(handlers.keys()))
    monkeypatch.setattr(agent, "STEP_HANDLERS", handlers)


def test_terminally_failed_run_is_not_resumable(tmp_path, monkeypatch):
    """A run that exhausted its retries must stay halted, not be resumed forever."""
    _use_temp_db(tmp_path, monkeypatch)

    run_id = state_manager.create_run()
    state_manager.update_run(run_id, "failed", "SUMMARIZE", {}, 3, "Max retries exceeded")

    assert state_manager.get_resumable_run() is None


def test_failed_retry_run_is_resumable(tmp_path, monkeypatch):
    """Crash recovery must keep working: paused runs are picked up again."""
    _use_temp_db(tmp_path, monkeypatch)

    run_id = state_manager.create_run()
    state_manager.update_run(run_id, "failed_retry", "SUMMARIZE", {}, 1, "boom")

    assert state_manager.get_resumable_run() == run_id


def test_new_run_starts_after_terminal_failure(tmp_path, monkeypatch):
    """After a run halts for good, the next cycle starts a fresh run instead of
    re-executing the dead one."""
    _use_temp_db(tmp_path, monkeypatch)
    _fake_steps(monkeypatch, {"A": lambda s: s})

    dead_id = state_manager.create_run()
    state_manager.update_run(dead_id, "failed", "SUMMARIZE", {}, 3, "Max retries exceeded")

    agent.run_agent_loop()

    conn = sqlite3.connect(config.DB_PATH)
    runs = {row[0]: (row[1], row[2]) for row in conn.execute(
        "SELECT run_id, status, retry_count FROM agent_runs")}
    conn.close()

    assert len(runs) == 2, "a fresh run should have been created"
    assert runs[dead_id] == ("failed", 3), "the dead run must not be touched"


def test_success_checkpoint_points_at_next_step(tmp_path, monkeypatch):
    """After a step succeeds, the persisted checkpoint must name the NEXT step,
    so a crash right after the success write cannot re-run the finished step."""
    _use_temp_db(tmp_path, monkeypatch)
    _fake_steps(monkeypatch, {"A": lambda s: s, "B": lambda s: s})

    writes = []
    real_update = state_manager.update_run

    def spy(run_id, status, current_step, state_data, retry_count, last_error=""):
        writes.append((status, current_step))
        return real_update(run_id, status, current_step, state_data, retry_count, last_error)

    monkeypatch.setattr(state_manager, "update_run", spy)

    agent.run_agent_loop()

    first_a = writes.index(("running", "A"))
    after_a = writes[first_a + 1]
    assert after_a != ("running", "A"), (
        "success checkpoint still points at the completed step A; a crash here "
        "would re-run it on resume")
    assert after_a == ("running", "B")


def test_completed_steps_do_not_rerun_on_resume(tmp_path, monkeypatch):
    """Resume must start at the failing step, never repeat earlier successes."""
    _use_temp_db(tmp_path, monkeypatch)

    calls = {"A": 0, "B": 0}
    fail_first_b = {"remaining": 1}

    def step_a(state):
        calls["A"] += 1
        return state

    def step_b(state):
        calls["B"] += 1
        if fail_first_b["remaining"] > 0:
            fail_first_b["remaining"] -= 1
            raise ValueError("transient")
        return state

    _fake_steps(monkeypatch, {"A": step_a, "B": step_b})

    agent.run_agent_loop()  # A ok, B fails -> paused
    agent.run_agent_loop()  # resume: B ok -> completed

    assert calls["A"] == 1, "step A must run exactly once across the resume"
    assert calls["B"] == 2

    conn = sqlite3.connect(config.DB_PATH)
    statuses = [row[0] for row in conn.execute("SELECT status FROM agent_runs")]
    conn.close()
    assert statuses == ["completed"]


def test_active_run_blocks_new_run_creation(tmp_path, monkeypatch):
    """A run that is actively executing in another process must not be joined
    or duplicated by this one."""
    _use_temp_db(tmp_path, monkeypatch)
    _fake_steps(monkeypatch, {"A": lambda s: s})

    active_id = state_manager.create_run()
    state_manager.update_run(active_id, "running", "A", {}, 0)  # fresh heartbeat

    agent.run_agent_loop()

    conn = sqlite3.connect(config.DB_PATH)
    rows = list(conn.execute("SELECT run_id, status FROM agent_runs"))
    conn.close()
    assert rows == [(active_id, "running")], (
        "loop must skip the cycle entirely, leaving the active run untouched")


def test_stale_running_run_is_resumed(tmp_path, monkeypatch):
    """A run stuck in 'running' long past the stale cutoff is a crashed run:
    it must be reclaimed and finished, not treated as active."""
    _use_temp_db(tmp_path, monkeypatch)
    _fake_steps(monkeypatch, {"A": lambda s: s})

    crashed_id = state_manager.create_run()
    state_manager.update_run(crashed_id, "running", "A", {}, 0)
    _set_updated_at(crashed_id, "2000-01-01 00:00:00")

    agent.run_agent_loop()

    conn = sqlite3.connect(config.DB_PATH)
    rows = list(conn.execute("SELECT run_id, status FROM agent_runs"))
    conn.close()
    assert rows == [(crashed_id, "completed")]
