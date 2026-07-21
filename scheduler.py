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

def main():
    logger.info("Initializing Agent Background Daemon...")
    
    # Check for keys in environment
    if not config.GEMINI_API_KEY and not config.OPENAI_API_KEY:
        logger.warning(
            "API keys are missing in config/environment. The agent will run its simulated steps, "
            "but the 'ANALYZE' step (which calls the LLM) will fail and trigger retry routines."
        )
        logger.warning("To fix, add GEMINI_API_KEY or OPENAI_API_KEY to your .env file.")

    # Create AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    
    # Schedule our agent job
    logger.info(f"Scheduling agent execution to trigger every {config.AGENT_INTERVAL_SECONDS} seconds.")
    scheduler.add_job(
        run_agent_loop,
        'interval',
        seconds=config.AGENT_INTERVAL_SECONDS,
        id='weekly_worker_agent_job'
    )
    
    # Start scheduler
    scheduler.start()
    logger.info("Scheduler started. Press Ctrl+C to exit.")
    
    # Keep the async loop running
    loop = asyncio.get_event_loop()
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down scheduler gracefully...")
        scheduler.shutdown()
        logger.info("Scheduler stopped.")

if __name__ == "__main__":
    main()
