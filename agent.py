import logging
from datetime import datetime

from google import genai
from google.genai import types
from openai import OpenAI

import config
import state_manager
import tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("StatefulAgent.Core")


def call_llm(prompt: str, system_instruction: str = None) -> str:
    """Queries the configured LLM provider."""
    provider = config.DEFAULT_MODEL_PROVIDER
    model = config.DEFAULT_MODEL

    logger.info(f"Invoking LLM ({provider}:{model})...")

    if provider == "gemini":
        if not config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set.")
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7
            )
        )
        return response.text.strip()

    elif provider in ("openai", "ollama"):
        if provider == "openai":
            if not config.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY is not set.")
            client = OpenAI(api_key=config.OPENAI_API_KEY)
        else:
            client = OpenAI(base_url=config.OLLAMA_BASE_URL, api_key="ollama")

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _llm_configured() -> bool:
    provider = config.DEFAULT_MODEL_PROVIDER
    if provider == "gemini":
        return bool(config.GEMINI_API_KEY)
    if provider == "openai":
        return bool(config.OPENAI_API_KEY)
    return provider == "ollama"  # local, no key needed


def run_step_fetch(state_data: dict) -> dict:
    """Step 1: Downloads this term's active postings from the listings feed."""
    state_data["postings"] = tools.fetch_postings(config.LISTINGS_URL, config.FILTER_TERMS)
    return state_data


def run_step_filter(state_data: dict) -> dict:
    """Step 2: Keeps only postings that have never been in a digest before."""
    postings = state_data.pop("postings", [])
    new_postings = state_manager.filter_unseen(postings)
    logger.info(f"{len(new_postings)} new posting(s) out of {len(postings)} active.")
    state_data["new_postings"] = new_postings
    return state_data


def run_step_summarize(state_data: dict) -> dict:
    """Step 3: Asks the LLM for a short overview of what's new.

    A missing API key is a configuration problem, not a transient failure, so
    it degrades to a placeholder instead of burning the retry budget.
    """
    new_postings = state_data.get("new_postings", [])

    if not new_postings:
        state_data["summary"] = "No new postings since the last digest."
        return state_data

    if not _llm_configured():
        logger.warning("No LLM API key configured; publishing digest without an LLM summary.")
        state_data["summary"] = (
            f"{len(new_postings)} new posting(s) this week. "
            "(LLM summary disabled: no API key configured.)"
        )
        return state_data

    listing_text = "\n".join(
        f"- {p['company']}: {p['title']} ({'; '.join(p['locations']) or 'location unlisted'})"
        for p in new_postings
    )
    prompt = (
        "These software internship postings appeared since last week's digest. "
        "In 2-4 sentences, summarize what's new for a CS student applying to "
        "internships: notable companies, clusters of roles, and locations.\n\n"
        f"{listing_text}"
    )
    system_instruction = "You are a concise career-research assistant. Be direct and specific."

    state_data["summary"] = call_llm(prompt, system_instruction=system_instruction)
    return state_data


def run_step_publish(state_data: dict) -> dict:
    """Step 4: Writes the date-stamped digest and records postings as seen.

    Seen-marking happens only here — a run that failed before publishing keeps
    its postings eligible for the next digest. Both the file write and the
    marking are idempotent, so re-running after a crash is safe.
    """
    new_postings = state_data.get("new_postings", [])
    date_str = datetime.now().strftime("%Y-%m-%d")
    report_path = config.REPORTS_DIR / f"{date_str}-internship-digest.md"

    if not new_postings and report_path.exists():
        logger.info("Nothing new and today's digest already exists; keeping it.")
    else:
        report = tools.compile_report(new_postings, state_data.get("summary", ""), date_str)
        tools.publish_report(report, config.REPORTS_DIR, date_str)

    state_manager.mark_seen(new_postings)
    state_data["report_path"] = str(report_path)
    return state_data


STEP_HANDLERS = {
    "FETCH": run_step_fetch,
    "FILTER": run_step_filter,
    "SUMMARIZE": run_step_summarize,
    "PUBLISH": run_step_publish,
}

STEP_ORDER = ["FETCH", "FILTER", "SUMMARIZE", "PUBLISH"]

MAX_ATTEMPTS = 3


def execute_run(run_id: str):
    """Core execution engine: claims the run, then executes steps from the
    checkpoint with per-step retries and crash-safe persistence."""
    if not state_manager.claim_run(run_id):
        logger.info(f"Run {run_id} is owned by another process or terminal; skipping.")
        return

    run = state_manager.load_run(run_id)
    state_data = run["state_data"]
    retry_count = run["retry_count"]
    current_step = run["current_step"]

    if current_step == "FINISHED":
        # Crashed after the last step succeeded but before the completed write.
        state_manager.update_run(run_id, "completed", "FINISHED", state_data, 0)
        logger.info(f"Run {run_id} had already finished all steps; marked completed.")
        return

    start_idx = STEP_ORDER.index(current_step) if current_step in STEP_ORDER else 0
    logger.info(f"Executing run {run_id} from step {STEP_ORDER[start_idx]} "
                f"(attempt {retry_count + 1}/{MAX_ATTEMPTS})")
    state_manager.log_step(run_id, "START", "success",
                           f"Starting/Resuming execution from {STEP_ORDER[start_idx]}")

    for i in range(start_idx, len(STEP_ORDER)):
        step_name = STEP_ORDER[i]
        handler = STEP_HANDLERS[step_name]

        logger.info(f"=== Running Step: {step_name} ===")
        state_manager.update_run(run_id, "running", step_name, state_data, retry_count)

        try:
            state_data = handler(state_data)
        except Exception as e:
            retry_count += 1
            error_msg = str(e)
            logger.error(f"Error in step {step_name}: {error_msg}")
            state_manager.log_step(run_id, step_name, "failed",
                                   f"Attempt {retry_count} failed: {error_msg}")

            if retry_count < MAX_ATTEMPTS:
                logger.info(f"Attempt {retry_count}/{MAX_ATTEMPTS} failed. "
                            "Pausing execution to retry next cycle.")
                state_manager.update_run(run_id, "failed_retry", step_name,
                                         state_data, retry_count, error_msg)
            else:
                logger.critical(f"Step {step_name} failed after {retry_count} attempts. "
                                "Halting run; a fresh run will start next cycle.")
                state_manager.update_run(run_id, "failed", step_name, state_data,
                                         retry_count, f"Max attempts exceeded: {error_msg}")
            return

        # Success: checkpoint points at the NEXT step, so a crash after this
        # write can never re-run the step that just finished.
        retry_count = 0
        next_step = STEP_ORDER[i + 1] if i + 1 < len(STEP_ORDER) else "FINISHED"
        state_manager.update_run(run_id, "running", next_step, state_data, retry_count)
        state_manager.log_step(run_id, step_name, "success",
                               f"Step {step_name} completed successfully.")

    state_manager.update_run(run_id, "completed", "FINISHED", state_data, 0)
    state_manager.log_step(run_id, "FINISHED", "success", "Run completed successfully!")
    logger.info(f"=== Run {run_id} completed successfully! ===")


def run_agent_loop():
    """Main entry: skips if a run is active elsewhere, resumes an interrupted
    run if one exists, otherwise starts fresh."""
    if state_manager.has_active_run():
        logger.info("Another run is currently active; skipping this cycle.")
        return

    run_id = state_manager.get_resumable_run()
    if run_id:
        logger.info(f"Found resumable run {run_id}. Resuming...")
    else:
        logger.info("No resumable runs found. Starting fresh run...")
        run_id = state_manager.create_run()

    execute_run(run_id)
