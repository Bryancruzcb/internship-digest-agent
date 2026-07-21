import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler

import config
from agent import run_agent_loop

# Clean logs for terminal visibility
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("StatefulAgent.Scheduler")


def build_scheduler() -> BackgroundScheduler:
    """Creates the scheduler with the agent job registered: weekly by default,
    or a fast interval when AGENT_INTERVAL_SECONDS is set (demo mode)."""
    scheduler = BackgroundScheduler()
    if config.AGENT_INTERVAL_SECONDS:
        scheduler.add_job(
            run_agent_loop,
            'interval',
            seconds=config.AGENT_INTERVAL_SECONDS,
            id='weekly_worker_agent_job'
        )
    else:
        scheduler.add_job(
            run_agent_loop,
            'cron',
            day_of_week=config.SCHEDULE_DAY_OF_WEEK,
            hour=config.SCHEDULE_HOUR,
            id='weekly_worker_agent_job'
        )
    return scheduler


def main():
    logger.info("Initializing Agent Background Daemon...")

    if not config.GEMINI_API_KEY and not config.OPENAI_API_KEY:
        logger.warning(
            "No LLM API key configured; digests will be published without an LLM summary. "
            "Add GEMINI_API_KEY or OPENAI_API_KEY to your .env file to enable it."
        )

    scheduler = build_scheduler()
    scheduler.start()

    if config.AGENT_INTERVAL_SECONDS:
        logger.info(f"Demo mode: running every {config.AGENT_INTERVAL_SECONDS} seconds.")
    else:
        logger.info(f"Scheduled weekly: {config.SCHEDULE_DAY_OF_WEEK} at {config.SCHEDULE_HOUR:02d}:00.")
    logger.info("Scheduler started. Press Ctrl+C to exit.")

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down scheduler gracefully...")
        scheduler.shutdown()
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
