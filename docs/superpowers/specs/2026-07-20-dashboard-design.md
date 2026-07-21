# Dashboard design — 2026-07-20

Approved by Bryan 2026-07-20 (options: Flask, Run Now button, stat row + weekly
bars). Implementation plan is folded into this spec (single-file feature).

## Purpose

A local web dashboard over the agent's SQLite state so the pipeline's behavior
— runs, retries, step audit trail, published digests — is visible without
reading the database by hand. Read-only except for one demo-friendly action:
triggering a run.

## Components

* `dashboard.py` — Flask app. Thin: route handlers call `state_manager` read
  helpers and render templates. Started with `python dashboard.py`, binds
  127.0.0.1:5000.
* `state_manager` read helpers (new): `list_runs()`, `list_steps(run_id)`,
  `weekly_seen_counts()`, `seen_count()`. Plain functions returning dicts —
  testable without Flask.
* `templates/` — `base.html` (inline CSS, no external assets), `index.html`,
  `run_detail.html`, `report.html`.

## Routes

| Route | Behavior |
|---|---|
| `GET /` | Stat tiles (total runs, completed, postings tracked, digests published), new-postings-per-week bars, runs table with status badges, digest list, Run Now button |
| `GET /runs/<run_id>` | Run header + step timeline from `step_logs`; 404 for unknown id |
| `GET /reports/<name>` | Digest markdown rendered to HTML; name validated against the reports dir listing (no traversal) |
| `POST /run` | If `has_active_run()`: redirect home with "already running" notice. Else: start `run_agent_loop` in a daemon thread, redirect home |

## Error handling

Unknown run/report → 404. Empty database → zero-state page, no crash. The
Run Now thread swallows nothing: failures land in the run row like any other
run, which is the point.

## Testing (implementation plan = this list, TDD order)

1. `list_runs` / `list_steps` / `weekly_seen_counts` return expected shapes
   from a seeded temp DB.
2. `GET /` 200, shows run status text and stat numbers.
3. `GET /runs/<id>` shows step names; unknown id 404s.
4. `GET /reports/<name>` renders digest content; `..`-style names 404.
5. `POST /run` triggers `run_agent_loop` exactly once (monkeypatched);
   with an active run present it does not trigger and still redirects.

## Also in this pass

* GitHub Actions workflow: pytest on push/PR to main.
* README: dashboard section + CI badge.
* New deps: `flask`, `markdown` in requirements.txt.
