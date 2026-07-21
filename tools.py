import logging
from pathlib import Path

import requests

logger = logging.getLogger("StatefulAgent.Tools")


def fetch_postings(url: str, term: str) -> list:
    """Downloads the SimplifyJobs listings feed and returns normalized postings
    for the given term (e.g. 'Summer 2026')."""
    logger.info(f"Fetching listings feed for term '{term}'...")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    postings = normalize_postings(response.json(), term)
    logger.info(f"Feed contains {len(postings)} active '{term}' postings.")
    return postings


def normalize_postings(raw: list, term: str) -> list:
    """Reduces raw feed entries to the fields the digest needs, keeping only
    active, visible postings for the requested term."""
    postings = []
    for entry in raw:
        if not entry.get("active") or not entry.get("is_visible"):
            continue
        if term not in entry.get("terms", []):
            continue
        postings.append({
            "id": entry["id"],
            "company": entry.get("company_name", ""),
            "title": entry.get("title", ""),
            "locations": entry.get("locations", []),
            "url": entry.get("url", ""),
            "date_posted": entry.get("date_posted", 0),
        })
    return postings


def compile_report(new_postings: list, summary: str, date_str: str) -> str:
    """Formats the digest as markdown."""
    lines = [f"# Internship Digest — {date_str}", "", "## Summary", "", summary, ""]

    if new_postings:
        lines.append(f"## New postings ({len(new_postings)})")
        lines.append("")
        for p in sorted(new_postings, key=lambda p: p["company"].lower()):
            location = "; ".join(p["locations"]) if p["locations"] else "Location unlisted"
            lines.append(f"- **{p['company']}** — [{p['title']}]({p['url']}) — {location}")
    else:
        lines.append("No new postings since the last digest.")

    lines.append("")
    return "\n".join(lines)


def publish_report(content: str, reports_dir, date_str: str) -> Path:
    """Writes the digest to a date-stamped file so past weeks are never
    overwritten. Returns the path."""
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{date_str}-internship-digest.md"
    path.write_text(content, encoding="utf-8")
    logger.info(f"Report written to {path}")
    return path
