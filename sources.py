"""Posting sources beyond the SimplifyJobs feed.

Watchlist adapters poll company ATS endpoints directly (no auth), catching
postings the day they go live. The Handshake adapter parses saved-search job
alert emails — Handshake has no public API and forbids scraping, but parsing
mail it sends you is fair game.
"""

import imaplib
import json
import logging
import re
from datetime import datetime, timedelta
from email import message_from_bytes

import requests

import config
import tools

logger = logging.getLogger("StatefulAgent.Sources")

INTERN_RE = re.compile(r"\b(intern(ship)?s?|co[- ]?op)\b", re.IGNORECASE)


def _is_intern(title: str) -> bool:
    return bool(INTERN_RE.search(title))


def _iso_to_epoch(value) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def fetch_greenhouse(token: str, company: str) -> list:
    """Greenhouse public board API: boards-api.greenhouse.io/v1/boards/<token>/jobs"""
    resp = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", timeout=30)
    resp.raise_for_status()
    out = []
    for job in resp.json().get("jobs", []):
        title = job.get("title", "")
        if not _is_intern(title):
            continue
        location = (job.get("location") or {}).get("name", "")
        out.append({
            "id": f"gh:{token}:{job['id']}",
            "company": company,
            "title": title,
            "locations": [location] if location else [],
            "url": job.get("absolute_url", ""),
            "date_posted": _iso_to_epoch(job.get("first_published")),
        })
    return out


def fetch_lever(token: str, company: str) -> list:
    """Lever public postings API: api.lever.co/v0/postings/<token>?mode=json"""
    resp = requests.get(f"https://api.lever.co/v0/postings/{token}?mode=json", timeout=30)
    resp.raise_for_status()
    out = []
    for job in resp.json():
        title = job.get("text", "")
        if not _is_intern(title):
            continue
        location = (job.get("categories") or {}).get("location", "")
        out.append({
            "id": f"lv:{token}:{job['id']}",
            "company": company,
            "title": title,
            "locations": [location] if location else [],
            "url": job.get("hostedUrl", ""),
            "date_posted": int(job.get("createdAt", 0) / 1000),
        })
    return out


def fetch_ashby(token: str, company: str) -> list:
    """Ashby public job board API: api.ashbyhq.com/posting-api/job-board/<org>"""
    resp = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}", timeout=30)
    resp.raise_for_status()
    out = []
    for job in resp.json().get("jobs", []):
        title = job.get("title", "")
        if not job.get("isListed", True) or not _is_intern(title):
            continue
        location = job.get("location", "")
        out.append({
            "id": f"as:{token}:{job['id']}",
            "company": company,
            "title": title,
            "locations": [location] if location else [],
            "url": job.get("jobUrl", ""),
            "date_posted": _iso_to_epoch(job.get("publishedAt")),
        })
    return out


def fetch_oracle_orc(host: str, site_number: str, company: str, site_name: str = "CX") -> list:
    """Oracle Recruiting Cloud CE API (the pattern UL Solutions uses).

    Undocumented-but-stable public endpoint; the finder syntax could shift
    with Oracle quarterly updates, so failures here are logged, not fatal.
    """
    requisitions = []
    offset = 0
    while True:
        # expand=requisitionList... is required — without it the API returns
        # counts but an empty requisitionList.
        url = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
               f"?onlyData=true&expand=requisitionList.secondaryLocations"
               f"&finder=findReqs;siteNumber={site_number},limit=200,offset={offset},"
               f"sortBy=POSTING_DATES_DESC")
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        page = []
        for item in resp.json().get("items", []):
            page.extend(item.get("requisitionList", []))
        requisitions.extend(page)
        if len(page) < 200:
            break
        offset += 200
    out = []
    for req in requisitions:
        title = req.get("Title", "")
        if not _is_intern(title):
            continue
        location = req.get("PrimaryLocation", "")
        out.append({
            "id": f"orc:{host}:{site_number}:{req['Id']}",
            "company": company,
            "title": title,
            "locations": [location] if location else [],
            "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site_name}/job/{req['Id']}",
            "date_posted": _iso_to_epoch(req.get("PostedDate")),
        })
    return out


def fetch_watchlist() -> list:
    """Runs every adapter in watchlist.json. One broken company must never
    cost the digest the rest, so failures are logged and skipped."""
    if not config.WATCHLIST_PATH.exists():
        return []
    entries = json.loads(config.WATCHLIST_PATH.read_text(encoding="utf-8"))
    postings = []
    for entry in entries:
        source, company = entry.get("source"), entry.get("company", "?")
        try:
            if source == "greenhouse":
                fetched = fetch_greenhouse(entry["token"], company)
            elif source == "lever":
                fetched = fetch_lever(entry["token"], company)
            elif source == "ashby":
                fetched = fetch_ashby(entry["token"], company)
            elif source == "oracle_orc":
                fetched = fetch_oracle_orc(
                    entry["host"], entry["site_number"], company,
                    entry.get("site_name", "CX"))
            else:
                logger.warning(f"Watchlist: unknown source '{source}' for {company}; skipped.")
                continue
            needle = entry.get("location_contains", "").lower()
            if needle:
                fetched = [p for p in fetched
                           if any(needle in loc.lower() for loc in p["locations"])]
            postings.extend(fetched)
        except Exception as e:
            logger.warning(f"Watchlist: {company} ({source}) failed: {e}; skipped.")
    logger.info(f"Watchlist yielded {len(postings)} intern posting(s).")
    return postings


# Modern alert emails wrap every link in a per-email tracking URL, so job ids
# aren't visible; job data lives in job-list-* spans inside the content link.
HS_ITEM_RE = re.compile(
    r'<a\b([^>]*job-list-content-link[^>]*)>(.*?)</a>', re.IGNORECASE | re.DOTALL)
HS_HREF_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)
HS_SPAN_RES = {
    "employer": re.compile(r'class="[^"]*job-list-employer[^"]*"[^>]*>(.*?)</span>',
                           re.IGNORECASE | re.DOTALL),
    "title": re.compile(r'class="[^"]*job-list-title[^"]*"[^>]*>(.*?)</span>',
                        re.IGNORECASE | re.DOTALL),
    "meta": re.compile(r'class="[^"]*job-list-meta[^"]*"[^>]*>(.*?)</span>',
                       re.IGNORECASE | re.DOTALL),
}
# Older/simpler notification formats link straight to the posting.
HS_DIRECT_RE = re.compile(
    r'<a[^>]+href="(https://app\.joinhandshake\.com/jobs/(\d+)[^"]*)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL)


def _clean(fragment: str) -> str:
    import html as html_mod
    return html_mod.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def parse_handshake_alert(html: str) -> list:
    """Extracts job postings from a Handshake alert email (job-match alerts,
    weekly round-ups, and saved-search notifications)."""
    import hashlib
    out = []

    for match in HS_ITEM_RE.finditer(html):
        attrs, body = match.groups()
        employer_m = HS_SPAN_RES["employer"].search(body)
        title_m = HS_SPAN_RES["title"].search(body)
        if not (employer_m and title_m):
            continue
        employer, title = _clean(employer_m.group(1)), _clean(title_m.group(1))
        meta_m = HS_SPAN_RES["meta"].search(body)
        location = ""
        if meta_m:
            parts = [p.strip() for p in _clean(meta_m.group(1)).split("•")]
            if len(parts) >= 2:
                location = parts[-1]
        href_m = HS_HREF_RE.search(attrs)
        # Tracking URLs change per email — a content hash keeps the id stable.
        digest = hashlib.sha1(f"{employer}|{title}".encode()).hexdigest()[:16]
        out.append({
            "id": f"hs:{digest}",
            "company": employer,
            "title": title,
            "locations": [location] if location else [],
            "url": href_m.group(1) if href_m else "",
            "date_posted": 0,
        })

    for match in HS_DIRECT_RE.finditer(html):
        url, job_id, raw_title = match.groups()
        title = _clean(raw_title)
        if not title:
            continue
        out.append({
            "id": f"hs:{job_id}",
            "company": "via Handshake",
            "title": title,
            "locations": [],
            "url": url,
            "date_posted": 0,
        })

    seen_ids = set()
    unique = []
    for p in out:
        if p["id"] in seen_ids:
            continue
        seen_ids.add(p["id"])
        unique.append(p)
    return unique


def fetch_handshake_alerts() -> list:
    """Reads recent Handshake job-alert emails over IMAP. Disabled until
    HANDSHAKE_IMAP_USER / HANDSHAKE_IMAP_PASSWORD are configured."""
    if not (config.HANDSHAKE_IMAP_USER and config.HANDSHAKE_IMAP_PASSWORD):
        return []
    try:
        mail = imaplib.IMAP4_SSL(config.HANDSHAKE_IMAP_HOST)
        mail.login(config.HANDSHAKE_IMAP_USER, config.HANDSHAKE_IMAP_PASSWORD)
        mail.select(config.HANDSHAKE_IMAP_FOLDER, readonly=True)
        since = (datetime.now() - timedelta(days=8)).strftime("%d-%b-%Y")
        _, data = mail.search(None, f'(FROM "handshake" SINCE {since})')
        postings = []
        for num in data[0].split():
            _, msg_data = mail.fetch(num, "(RFC822)")
            message = message_from_bytes(msg_data[0][1])
            for part in message.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        postings.extend(parse_handshake_alert(
                            payload.decode(part.get_content_charset() or "utf-8", "replace")))
        mail.logout()
        logger.info(f"Handshake alerts yielded {len(postings)} posting(s).")
        return postings
    except Exception as e:
        logger.warning(f"Handshake alert fetch failed: {e}; skipped.")
        return []


def fetch_all() -> list:
    """Merges every configured source. Watchlist first so its direct ATS links
    win the company+title dedupe over aggregator copies."""
    postings = fetch_watchlist() + fetch_handshake_alerts()
    postings += tools.fetch_postings(config.LISTINGS_URL, config.FILTER_TERMS)
    seen_keys = set()
    merged = []
    for p in postings:
        key = (p["company"].strip().lower(), p["title"].strip().lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        merged.append(p)
    return merged
