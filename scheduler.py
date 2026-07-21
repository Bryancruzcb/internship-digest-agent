import asyncio
import logging
import sys
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import config
from agent import run_agent_loop

# Clean logs for terminal visibility
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("StatefulAgent.Scheduler")

def build_scheduler() -> AsyncIOScheduler:
    """Creates the scheduler with the agent job registered.

    The returned scheduler must be started from inside a running event loop:
    APScheduler 3.11's AsyncIOScheduler.start() calls asyncio.get_running_loop().
    """
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_agent_loop,
        'interval',
        seconds=config.AGENT_INTERVAL_SECONDS,
        id='weekly_worker_agent_job'
    )
    return scheduler

async def main():
    logger.info("Initializing Agent Background Daemon...")

    # Check for keys in environment
    if not config.GEMINI_API_KEY and not config.OPENAI_API_KEY:
        logger.warning(
            "API keys are missing in config/environment. The agent will run its simulated steps, "
            "but the 'ANALYZE' step (which calls the LLM) will fail and trigger retry routines."
        )
        logger.warning("To fix, add GEMINI_API_KEY or OPENAI_API_KEY to your .env file.")

    logger.info(f"Scheduling agent execution to trigger every {config.AGENT_INTERVAL_SECONDS} seconds.")
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("Scheduler started. Press Ctrl+C to exit.")

    try:
        # Sleep until cancelled; the scheduler runs jobs on this event loop.
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown()

if __name__ == "__main__":
    # Match run_agent.py so both entry points use the same event loop flavor.
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
