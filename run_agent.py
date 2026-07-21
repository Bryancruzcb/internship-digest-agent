import asyncio
import sys
import logging
from agent import run_agent_loop

# Clean logs for one-off CLI execution
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("StatefulAgent.CLI")

def main():
    logger.info("Executing one-off stateful agent run...")
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_agent_loop())
    logger.info("One-off run check completed.")

if __name__ == "__main__":
    main()
