# Weekly Internship Digest Agent

A scheduled agent that publishes a weekly digest of new software internship
postings. Under the hood it is a small durable-execution engine: every pipeline
step checkpoints its progress to SQLite, so if the process crashes mid-run, the
next cycle resumes from the failing step instead of starting over. The same
pattern — at a much larger scale — is what tools like Temporal, Airflow, and
AWS Step Functions provide.

## What a run does

1. **FETCH** — downloads the community-maintained
   [SimplifyJobs internship feed](https://github.com/SimplifyJobs/Summer2026-Internships)
   and keeps active postings for the configured term.
2. **FILTER** — drops every posting that already appeared in a previous digest
   (tracked in a `seen_postings` table).
3. **SUMMARIZE** — asks an LLM (Gemini, OpenAI, or local Ollama) for a short
   overview of what's new. With no API key configured, the digest is published
   with a placeholder instead — a missing key is a configuration problem, not a
   transient failure, so it does not burn the retry budget.
4. **PUBLISH** — writes `reports/YYYY-MM-DD-internship-digest.md` and only then
   marks the postings as seen. A run that failed before publishing keeps its
   postings eligible for the next digest.

The first run publishes a large catch-up digest (everything currently active);
every run after that reports only what's new.

## Reliability design

* **Checkpoint persistence** — each run's status, step pointer, and
  accumulated data live in SQLite (`agent_state.db`). After a step succeeds,
  the checkpoint points at the *next* step, so a crash at any moment never
  re-runs a finished step.
* **Retries for transient failures** — a failing step gets 3 attempts (one per
  scheduler cycle). After the third failure the run is halted for good and the
  next cycle starts a fresh run; halted runs are never resurrected.
* **Crash vs. active detection** — a run whose heartbeat is fresh is being
  executed by a live process, and other cycles skip it. A run stuck in
  `running` past the stale cutoff (default 30 min) is treated as crashed and
  resumed. Ownership is taken with an atomic claim, so two processes cannot
  execute the same run.
* **Idempotent publishing** — the report write and seen-marking are both safe
  to repeat, which is what makes resume-after-crash correct.

## Setup

```bash
pip install -r requirements.txt
cp env.example .env   # then add an API key if you want LLM summaries
```

## Running

```bash
python run_agent.py    # one-off run (also resumes an interrupted run)
python scheduler.py    # daemon: runs weekly (Monday 09:00 by default)
```

For a fast local demo, set `AGENT_INTERVAL_SECONDS=30` in `.env` and the
daemon runs on that interval instead of weekly.

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests cover the state machine (halt-for-good after max retries, fresh run
after a halt, resume-at-failing-step, checkpoint-points-at-next-step, active
vs. stale run handling), the dedupe/publish behavior, and the feed
normalization. No test touches the network.

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | – | Enables LLM summaries |
| `AGENT_PROVIDER` | `gemini` | `gemini`, `openai`, or `ollama` |
| `AGENT_MODEL` | `gemini-2.5-flash` | Model name for the provider |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Local Ollama endpoint |
| `LISTINGS_URL` | SimplifyJobs Summer 2026 feed | Feed JSON to pull |
| `FILTER_TERM` | `Summer 2026` | Term tag to keep |
| `SCHEDULE_DAY_OF_WEEK` / `SCHEDULE_HOUR` | `mon` / `9` | Weekly schedule |
| `AGENT_INTERVAL_SECONDS` | – | Demo mode: run every N seconds |
| `STALE_RUN_MINUTES` | `30` | Heartbeat age before a run counts as crashed |

When SimplifyJobs publishes the Summer 2027 repo (usually around
August–September), point `LISTINGS_URL` at it and set
`FILTER_TERM=Summer 2027`.

## Limitations

* Single machine, single SQLite file — this is deliberate; the project is
  about durable-execution mechanics, not distributed infrastructure.
* Retries happen once per scheduler cycle, so with the weekly schedule a
  transient failure waits a week to retry. Run `python run_agent.py` to retry
  immediately.
* The digest only knows what the SimplifyJobs feed knows.
