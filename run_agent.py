import logging

from agent import run_agent_loop

# Clean logs for one-off CLI execution
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("StatefulAgent.CLI")


def main():
    logger.info("Executing one-off agent run...")
    run_agent_loop()
    logger.info("One-off run finished.")


if __name__ == "__main__":
    main()
