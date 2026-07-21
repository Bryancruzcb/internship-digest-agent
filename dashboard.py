import logging
import threading

import markdown as md
from flask import Flask, abort, redirect, render_template, url_for

import agent
import config
import state_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("StatefulAgent.Dashboard")

app = Flask(__name__)


def _trigger_run():
    """Runs the agent loop off the request thread. The loop's own atomic claim
    and active-run guard make this safe even if clicked repeatedly."""
    threading.Thread(target=agent.run_agent_loop, daemon=True).start()


def _list_reports() -> list:
    if not config.REPORTS_DIR.exists():
        return []
    return sorted((p.name for p in config.REPORTS_DIR.glob("*-internship-digest.md")),
                  reverse=True)


@app.route("/")
def index():
    runs = state_manager.list_runs()
    reports = _list_reports()
    stats = {
        "total_runs": len(runs),
        "completed": sum(1 for r in runs if r["status"] == "completed"),
        "postings": state_manager.seen_count(),
        "digests": len(reports),
    }
    weekly = state_manager.weekly_seen_counts()
    max_count = max((w["count"] for w in weekly), default=0)
    return render_template("index.html", runs=runs, stats=stats, weekly=weekly,
                           max_count=max_count, reports=reports,
                           active=state_manager.has_active_run())


@app.route("/runs/<run_id>")
def run_detail(run_id):
    run = state_manager.load_run(run_id)
    if not run:
        abort(404)
    return render_template("run_detail.html", run=run,
                           steps=state_manager.list_steps(run_id))


@app.route("/reports/<name>")
def report(name):
    # Whitelist against the actual directory listing — no path assembly from
    # user input reaches the filesystem.
    if name not in _list_reports():
        abort(404)
    text = (config.REPORTS_DIR / name).read_text(encoding="utf-8")
    return render_template("report.html", name=name, body=md.markdown(text))


@app.route("/run", methods=["POST"])
def run_now():
    if state_manager.has_active_run():
        logger.info("Run Now ignored: a run is already active.")
    else:
        _trigger_run()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
