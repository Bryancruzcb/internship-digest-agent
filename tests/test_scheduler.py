import asyncio

import scheduler as scheduler_mod


def test_scheduler_starts_inside_running_event_loop():
    """APScheduler 3.11's AsyncIOScheduler.start() requires a running loop;
    the daemon must construct and start it from async context."""
    async def go():
        sched = scheduler_mod.build_scheduler()
        sched.start()
        try:
            assert sched.running
            assert sched.get_job("weekly_worker_agent_job") is not None
        finally:
            sched.shutdown(wait=False)

    asyncio.run(go())
