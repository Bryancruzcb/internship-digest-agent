import json

import requests

import config
import sources


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _fake_get(payload):
    return lambda url, timeout=30: FakeResponse(payload)


# --- per-ATS adapters: normalization, intern filtering, id namespacing ---

def test_greenhouse_adapter(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get({"jobs": [
        {"id": 101, "title": "Software Engineer Intern", "absolute_url": "https://gh.io/101",
         "location": {"name": "SF"}, "first_published": "2026-07-01T08:00:00-04:00"},
        {"id": 102, "title": "Internal Tools Engineer", "absolute_url": "https://gh.io/102",
         "location": {"name": "NYC"}, "first_published": "2026-07-01T08:00:00-04:00"},
    ]}))

    result = sources.fetch_greenhouse("acme", "Acme")

    assert [p["id"] for p in result] == ["gh:acme:101"], \
        "'Internal' must not match the intern filter"
    assert result[0]["company"] == "Acme"
    assert result[0]["url"] == "https://gh.io/101"


def test_lever_adapter(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get([
        {"id": "ab-1", "text": "Data Science Co-op", "hostedUrl": "https://lv.io/ab-1",
         "createdAt": 1753000000000, "categories": {"location": "Seattle"}},
        {"id": "ab-2", "text": "International Sales Lead", "hostedUrl": "https://lv.io/ab-2",
         "createdAt": 1753000000000, "categories": {"location": "Remote"}},
    ]))

    result = sources.fetch_lever("acme", "Acme")

    assert [p["id"] for p in result] == ["lv:acme:ab-1"], \
        "co-op counts; 'International' does not"


def test_ashby_adapter(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get({"jobs": [
        {"id": "x1", "title": "ML Internship", "jobUrl": "https://as.io/x1",
         "location": "Palo Alto", "publishedAt": "2026-07-20T00:00:00Z", "isListed": True},
        {"id": "x2", "title": "Research Intern", "jobUrl": "https://as.io/x2",
         "location": "Palo Alto", "publishedAt": "2026-07-20T00:00:00Z", "isListed": False},
    ]}))

    result = sources.fetch_ashby("acme", "Acme")

    assert [p["id"] for p in result] == ["as:acme:x1"], "unlisted jobs are dropped"


def test_oracle_orc_adapter(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get({"items": [{"requisitionList": [
        {"Id": "9366", "Title": "Software Development Intern",
         "PostedDate": "2026-07-01", "PrimaryLocation": "Fremont, CA, United States"},
        {"Id": "9400", "Title": "Staff Engineer",
         "PostedDate": "2026-07-01", "PrimaryLocation": "Chicago, IL"},
    ]}]}))

    result = sources.fetch_oracle_orc("fa-test.oraclecloud.com", "CX_1", "UL Solutions")

    assert [p["id"] for p in result] == ["orc:fa-test.oraclecloud.com:CX_1:9366"]
    assert "fa-test.oraclecloud.com" in result[0]["url"]


# --- watchlist orchestration ---

def test_watchlist_merges_and_survives_a_failing_source(tmp_path, monkeypatch):
    watchlist = tmp_path / "watchlist.json"
    watchlist.write_text(json.dumps([
        {"source": "greenhouse", "token": "good", "company": "GoodCo"},
        {"source": "greenhouse", "token": "broken", "company": "BadCo"},
    ]), encoding="utf-8")
    monkeypatch.setattr(config, "WATCHLIST_PATH", watchlist)

    def fake_fetch(token, company):
        if token == "broken":
            raise requests.exceptions.ConnectionError("down")
        return [{"id": f"gh:{token}:1", "company": company, "title": "SWE Intern",
                 "locations": ["SF"], "url": "https://x", "date_posted": 0}]

    monkeypatch.setattr(sources, "fetch_greenhouse", fake_fetch)

    result = sources.fetch_watchlist()

    assert [p["company"] for p in result] == ["GoodCo"], \
        "one broken source must not kill the rest"


def test_watchlist_location_contains_filter(tmp_path, monkeypatch):
    watchlist = tmp_path / "watchlist.json"
    watchlist.write_text(json.dumps([
        {"source": "greenhouse", "token": "acme", "company": "Acme",
         "location_contains": "United States"},
    ]), encoding="utf-8")
    monkeypatch.setattr(config, "WATCHLIST_PATH", watchlist)
    monkeypatch.setattr(sources, "fetch_greenhouse", lambda token, company: [
        {"id": "gh:acme:1", "company": company, "title": "SWE Intern",
         "locations": ["Fremont, CA, United States"], "url": "https://x", "date_posted": 0},
        {"id": "gh:acme:2", "company": company, "title": "Lab Intern",
         "locations": ["Hanoi, Vietnam"], "url": "https://y", "date_posted": 0},
    ])

    result = sources.fetch_watchlist()

    assert [p["id"] for p in result] == ["gh:acme:1"]


def test_fetch_all_merges_and_dedupes_by_company_title(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WATCHLIST_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(config, "HANDSHAKE_IMAP_USER", None)
    monkeypatch.setattr(
        sources.tools, "fetch_postings",
        lambda url, terms: [{"id": "simplify-1", "company": "Acme", "title": "SWE Intern",
                             "locations": ["SF"], "url": "https://simplify", "date_posted": 1}])
    monkeypatch.setattr(
        sources, "fetch_watchlist",
        lambda: [{"id": "gh:acme:1", "company": "ACME", "title": "swe intern",
                  "locations": ["SF"], "url": "https://direct", "date_posted": 2}])

    result = sources.fetch_all()

    assert len(result) == 1, "same company+title across sources is one posting"
    assert result[0]["id"] == "gh:acme:1", "the direct-ATS copy wins (fresher link)"


# --- handshake alert-email parsing (fixture; no network, no credentials) ---

# Condensed from a real Handshake job-match alert (2026-07): links are
# tracking-wrapped, and job data lives in job-list-* spans.
REAL_ALERT_HTML = """
<html><body>
<a class="job-list-logo-link" href="https://email.notifications.joinhandshake.com/c/AAAA">
  <img alt="Google, Inc. logo"></a>
<a class="job-list-content-link" href="https://email.notifications.joinhandshake.com/c/BBBB">
  <span class="job-list-employer">Google, Inc.</span>
  <span class="job-list-title">Software Engineering Intern, MS, Summer 2027</span>
  <span class="job-list-meta">$98&#8211;131K/yr &#8226; Internship &#8226; Bellevue, WA +29 (Onsite)</span>
</a>
<a href="https://email.notifications.joinhandshake.com/u/unsubscribe">unsubscribe</a>
</body></html>
"""

LEGACY_ALERT_HTML = """
<html><body>
  <a href="https://app.joinhandshake.com/jobs/8912345?ref=email">Software Engineering Intern</a>
  <a href="https://app.joinhandshake.com/settings">Unsubscribe</a>
</body></html>
"""


def test_handshake_parser_reads_real_alert_format():
    result = sources.parse_handshake_alert(REAL_ALERT_HTML)

    assert len(result) == 1, "one job item; logo/unsubscribe links ignored"
    job = result[0]
    assert job["company"] == "Google, Inc."
    assert job["title"] == "Software Engineering Intern, MS, Summer 2027"
    assert job["locations"] == ["Bellevue, WA +29 (Onsite)"]
    assert job["url"] == "https://email.notifications.joinhandshake.com/c/BBBB"
    assert job["id"].startswith("hs:")


def test_handshake_parser_id_is_stable_across_emails():
    """Tracking URLs differ per email; the id must not — else the same job
    reappears in every digest."""
    a = sources.parse_handshake_alert(REAL_ALERT_HTML)[0]
    b = sources.parse_handshake_alert(
        REAL_ALERT_HTML.replace("/c/BBBB", "/c/DIFFERENT-TOKEN"))[0]

    assert a["id"] == b["id"]


def test_handshake_parser_still_reads_direct_job_links():
    result = sources.parse_handshake_alert(LEGACY_ALERT_HTML)

    assert [p["title"] for p in result] == ["Software Engineering Intern"]
    assert result[0]["url"].startswith("https://app.joinhandshake.com/jobs/8912345")
