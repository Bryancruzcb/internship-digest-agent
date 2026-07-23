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

ALERT_HTML = """
<html><body>
  <p>New jobs matching your saved search:</p>
  <a href="https://app.joinhandshake.com/jobs/8912345?ref=email">Software Engineering Intern</a>
  at <b>UL Solutions</b>
  <a href="https://app.joinhandshake.com/jobs/8912399?ref=email">Marketing Coordinator</a>
  at <b>SomeCo</b>
  <a href="https://app.joinhandshake.com/settings">Unsubscribe</a>
</body></html>
"""


def test_handshake_alert_parser_extracts_job_links():
    result = sources.parse_handshake_alert(ALERT_HTML)

    ids = [p["id"] for p in result]
    assert "hs:8912345" in ids, "job links must be extracted"
    assert all(not p["url"].endswith("/settings") for p in result), \
        "non-job links must be ignored"
    intern = next(p for p in result if p["id"] == "hs:8912345")
    assert intern["title"] == "Software Engineering Intern"
    assert intern["url"].startswith("https://app.joinhandshake.com/jobs/8912345")
