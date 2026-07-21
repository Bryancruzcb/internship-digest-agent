import time
import logging
from google import genai
from google.genai import types
from openai import OpenAI
import config
import state_manager
import tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("StatefulAgent.Core")

async def call_llm(prompt: str, system_instruction: str = None) -> str:
    """Queries the LLM provider based on config settings."""
    provider = config.DEFAULT_MODEL_PROVIDER
    model = config.DEFAULT_MODEL
    
    logger.info(f"Invoking LLM for analysis ({provider}:{model})...")
    
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

async def run_step_research(state_data: dict) -> dict:
    """Step 1: Gathers information using tools."""
    topic = state_data.get("topic", "Agentic AI workflows")
    articles = tools.search_news(topic)
    state_data["articles"] = articles
    return state_data

async def run_step_analyze(state_data: dict) -> dict:
    """Step 2: Uses LLM to analyze gathered data."""
    articles = state_data.get("articles", [])
    if not articles:
        raise ValueError("No research articles found to analyze.")
        
    articles_str = json_str = ""
    for idx, a in enumerate(articles):
        articles_str += f"[{idx+1}] Title: {a['title']}\nSource: {a['source']}\nSummary: {a['summary']}\n\n"
        
    prompt = (
        "Please read the following collected tech articles and write a 2-sentence executive summary "
        "synthesizing the key takeaways and developer impact:\n\n"
        f"{articles_str}"
    )
    
    system_instruction = "You are an expert AI industry analyst. Be direct, clear, and highly professional."
    
    analysis = await call_llm(prompt, system_instruction=system_instruction)
    state_data["analysis"] = analysis
    return state_data

async def run_step_compile(state_data: dict) -> dict:
    """Step 3: Formats markdown report."""
    articles = state_data.get("articles", [])
    analysis = state_data.get("analysis", "")
    
    report = tools.compile_report(articles, analysis)
    state_data["report"] = report
    return state_data

async def run_step_publish(state_data: dict) -> dict:
    """Step 4: Writes markdown file output."""
    report = state_data.get("report", "")
    if not report:
        raise ValueError("No compiled report found to publish.")
        
    filepath = tools.publish_report(report)
    state_data["filepath"] = filepath
    return state_data

# Map steps to their handler functions
STEP_HANDLERS = {
    "RESEARCH": run_step_research,
    "ANALYZE": run_step_analyze,
    "COMPILE": run_step_compile,
    "PUBLISH": run_step_publish
}

STEP_ORDER = ["RESEARCH", "ANALYZE", "COMPILE", "PUBLISH"]

async def execute_run(run_id: str):
    """Core state loop execution engine with persistence, error recovery, and retries."""
    run = state_manager.load_run(run_id)
    if not run:
        logger.error(f"Run {run_id} not found in database.")
        return
        
    logger.info(f"Executing run {run_id} (Status: {run['status']}, Current Step: {run['current_step']})")
    
    state_data = run["state_data"]
    # Ensure a topic is set
    if "topic" not in state_data:
        state_data["topic"] = "AI Agent Orchestration"
        
    retry_count = run["retry_count"]
    current_step = run["current_step"]
    
    # Determine where we start
    start_idx = 0
    if current_step in STEP_ORDER:
        start_idx = STEP_ORDER.index(current_step)
        
    # Set status to running
    state_manager.update_run(run_id, "running", current_step, state_data, retry_count)
    state_manager.log_step(run_id, "START", "success", f"Starting/Resuming execution from {current_step}")
    
    for i in range(start_idx, len(STEP_ORDER)):
        step_name = STEP_ORDER[i]
        handler = STEP_HANDLERS[step_name]
        
        logger.info(f"=== Running Step: {step_name} ===")
        state_manager.update_run(run_id, "running", step_name, state_data, retry_count)
        
        try:
            # Simulate processing and run step
            state_data = await handler(state_data)
            
            # Step succeeded: Reset retry count and update checkpoint
            retry_count = 0
            state_manager.update_run(run_id, "running", step_name, state_data, retry_count)
            state_manager.log_step(run_id, step_name, "success", f"Step {step_name} completed successfully.")
            
        except Exception as e:
            # Step failed: Increment retry count and log details
            retry_count += 1
            error_msg = str(e)
            logger.error(f"Error in step {step_name}: {error_msg}")
            
            # Record failure in logs
            state_manager.log_step(run_id, step_name, "failed", f"Attempt {retry_count} failed: {error_msg}")
            
            if retry_count < 3:
                # We can retry in the next scheduler cycle (checkpoint is saved)
                logger.info(f"Retry threshold not met ({retry_count}/3). Pausing execution to retry next cycle.")
                state_manager.update_run(run_id, "failed_retry", step_name, state_data, retry_count, error_msg)
                return
            else:
                # Maximum retries exceeded: Halt execution and notify/fail
                logger.critical(f"Step {step_name} failed after {retry_count} attempts. Halting run.")
                state_manager.update_run(run_id, "failed", step_name, state_data, retry_count, f"Max retries exceeded: {error_msg}")
                return
                
    # Complete execution
    state_manager.update_run(run_id, "completed", "FINISHED", state_data, 0)
    state_manager.log_step(run_id, "FINISHED", "success", "Run completed successfully!")
    logger.info(f"=== Run {run_id} completed successfully! ===")

async def run_agent_loop():
    """Main daemon runner: resumes interrupted runs or starts a new one."""
    incomplete_run_id = state_manager.get_latest_incomplete_run()
    
    if incomplete_run_id:
        logger.info(f"Found incomplete run {incomplete_run_id}. Resuming...")
        run_id = incomplete_run_id
    else:
        logger.info("No incomplete runs found. Starting fresh run...")
        run_id = state_manager.create_run()
        
    await execute_run(run_id)
