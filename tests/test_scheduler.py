import config
import scheduler as scheduler_mod


def test_default_schedule_is_weekly_cron(monkeypatch):
    monkeypatch.setattr(config, "AGENT_INTERVAL_SECONDS", None)

    sched = scheduler_mod.build_scheduler()
    job = sched.get_job("weekly_worker_agent_job")

    assert job is not None
    assert type(job.trigger).__name__ == "CronTrigger"


def test_interval_override_for_demo_runs(monkeypatch):
    monkeypatch.setattr(config, "AGENT_INTERVAL_SECONDS", 5)

    sched = scheduler_mod.build_scheduler()
    job = sched.get_job("weekly_worker_agent_job")

    assert type(job.trigger).__name__ == "IntervalTrigger"


def test_scheduler_starts_and_stops(monkeypatch):
    monkeypatch.setattr(config, "AGENT_INTERVAL_SECONDS", None)

    sched = scheduler_mod.build_scheduler()
    sched.start()
    try:
        assert sched.running
    finally:
        sched.shutdown(wait=False)
