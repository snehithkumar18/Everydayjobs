"""Parsers + prefilter, run against the fixtures in their native ATS shapes.

No network, no API key. This is the suite that catches the two bugs that cost
me an evening each: Lever's epoch-milliseconds timestamps, and a bare `sde`
regex that silently matches nothing.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunt import mock
from jobhunt.fetch import (
    parse_ashby, parse_greenhouse, parse_lever,
    parse_workable, parse_smartrecruiters, parse_recruitee, parse_breezy,
    parse_remotive, parse_remoteok, parse_arbeitnow, parse_jobicy,
    strip_html, Job
)
from jobhunt.mock import fetch_all_mock
from jobhunt.prefilter import prefilter

CONFIG = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml")
                        .read_text(encoding="utf-8"))
FILTERS = CONFIG["filters"]


# ------------------------------------------------------------- strip_html ---

def test_strip_html_unescapes_twice():
    """Greenhouse ships HTML-entity-escaped HTML: unescape, strip, unescape."""
    raw = "&lt;p&gt;Go &amp;amp; Java&lt;/p&gt;"
    assert strip_html(raw) == "Go & Java"


def test_strip_html_turns_block_tags_into_newlines():
    out = strip_html("<p>One</p><p>Two</p><ul><li>a</li><li>b</li></ul>")
    assert "One" in out and "Two" in out and "a" in out and "b" in out
    assert "<" not in out


def test_strip_html_handles_none_and_empty():
    assert strip_html(None) == ""
    assert strip_html("") == ""


# ---------------------------------------------------------------- parsers ---

def test_greenhouse_maps_every_field():
    jobs = parse_greenhouse("acme-edge", "Acme Edge", mock.GREENHOUSE["acme-edge"])
    j = next(j for j in jobs if j.title.startswith("Software Engineer II"))
    assert j.job_id == "greenhouse:acme-edge:5501001"
    assert j.ats == "greenhouse"
    assert j.company == "Acme Edge"
    assert j.location == "Bangalore, India"
    assert j.url.startswith("https://boards.greenhouse.io/")
    assert "distributed services" in j.description


def test_lever_concatenates_description_lists_and_additional():
    jobs = parse_lever("quantstack", "QuantStack", mock.LEVER["quantstack"])
    j = next(j for j in jobs if j.title == "Backend Engineer (Go)")
    assert "market data pipeline" in j.description
    assert "Requirements" in j.description
    assert "2-5 years backend experience" in j.description
    assert "No take-home" in j.description


def test_lever_createdAt_is_epoch_milliseconds():
    two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).date()
    jobs = parse_lever("quantstack", "QuantStack", mock.LEVER["quantstack"])
    j = next(j for j in jobs if j.title == "Backend Engineer (Go)")
    assert j.posted_at == two_days_ago.isoformat()


def test_ashby_skips_unlisted_drafts():
    jobs = parse_ashby("helioscale", "Helioscale", mock.ASHBY["helioscale"])
    assert all("unlisted" not in j.url for j in jobs)
    assert len(jobs) == 2


def test_ashby_reads_compensation_and_html_fallback():
    jobs = parse_ashby("helioscale", "Helioscale", mock.ASHBY["helioscale"])
    networking = next(j for j in jobs if j.title == "Software Engineer, Networking")
    assert networking.salary == "₹32L – ₹48L"
    ds = next(j for j in jobs if j.title == "Data Scientist, Growth")
    assert "Causal inference" in ds.description


def test_workable_parser():
    data = {
        "results": [
            {
                "shortcode": "W123",
                "title": "Senior Python Engineer",
                "city": "Bengaluru",
                "country": "India",
                "telecommuting": True,
                "url": "https://apply.workable.com/acme/j/W123",
                "description": "Python, Django, FastAPI",
                "published": "2026-08-15T00:00:00Z"
            }
        ]
    }
    jobs = parse_workable("acme", "Acme Corp", data)
    assert len(jobs) == 1
    assert jobs[0].job_id == "workable:acme:W123"
    assert jobs[0].title == "Senior Python Engineer"
    assert "Remote" in jobs[0].location


def test_smartrecruiters_parser():
    data = {
        "content": [
            {
                "id": "SR456",
                "name": "Machine Learning Engineer",
                "location": {"city": "Bangalore", "country": "India", "remote": True},
                "refNumber": "REF123",
                "releasedDate": "2026-08-15T00:00:00.000Z"
            }
        ]
    }
    jobs = parse_smartrecruiters("acme", "Acme Corp", data)
    assert len(jobs) == 1
    assert jobs[0].job_id == "smartrecruiters:acme:SR456"
    assert jobs[0].title == "Machine Learning Engineer"


def test_remotive_feed_parser():
    data = {
        "jobs": [
            {
                "id": 9901,
                "title": "Full Stack Developer",
                "company_name": "Global Tech",
                "candidate_required_location": "Worldwide",
                "url": "https://remotive.com/job/9901",
                "description": "<p>React & Python</p>",
                "publication_date": "2026-08-15T00:00:00",
                "salary": "$100k - $120k"
            }
        ]
    }
    jobs = parse_remotive("", "", data)
    assert len(jobs) == 1
    assert jobs[0].job_id == "remotive:global:9901"
    assert jobs[0].company == "Global Tech"
    assert jobs[0].salary == "$100k - $120k"


def test_job_ids_are_globally_unique_and_namespaced():
    jobs = fetch_all_mock()
    ids = [j.job_id for j in jobs]
    assert len(ids) == len(set(ids))
    assert all(re.match(r"^(greenhouse|lever|ashby):[^:]+:.+$", i) for i in ids)


def test_parsers_take_decoded_json_not_a_response():
    assert parse_greenhouse("x", "X", {}) == []
    assert parse_lever("x", "X", []) == []
    assert parse_ashby("x", "X", {}) == []
    assert parse_workable("x", "X", {}) == []
    assert parse_smartrecruiters("x", "X", {}) == []
    assert parse_recruitee("x", "X", {}) == []
    assert parse_breezy("x", "X", []) == []


# -------------------------------------------------------------- prefilter ---

@pytest.mark.parametrize("title", [
    "Software Engineer II, Distributed Systems",
    "Software Development Engineer, Core Infra",
    "Backend Engineer (Go)",
    "Site Reliability Engineer",
    "SDE II",
    "AI Engineer",
    "Machine Learning Engineer",
    "Full Stack Developer",
    "Data Engineer",
])
def test_include_titles_match_real_titles(title):
    inc = FILTERS["include_titles"]
    assert any(re.search(p, title, re.I) for p in inc), title


def test_bare_sde_regex_does_not_match_the_spelled_out_title():
    assert not re.search(r"\bsde\b", "Software Development Engineer", re.I)
    assert re.search(r"\bsde\b", "SDE II", re.I)
    inc = FILTERS["include_titles"]
    assert any(re.search(p, "Software Development Engineer, Core Infra", re.I) for p in inc)


@pytest.mark.parametrize("title", [
    "Staff Software Engineer, Storage",       # too senior
    "Engineering Manager, Platform",          # management track
    "Enterprise Account Executive",           # wrong function
    "Director of Engineering",                # too senior
    "VP of AI",                               # too senior
])
def test_junk_titles_are_rejected(title):
    inc, exc = FILTERS["include_titles"], FILTERS["exclude_titles"]
    included = any(re.search(p, title, re.I) for p in inc)
    excluded = any(re.search(p, title, re.I) for p in exc)
    assert excluded or not included, f"{title!r} would have survived"


def test_full_mock_funnel_keeps_valid_matches():
    kept = prefilter(fetch_all_mock(), FILTERS)
    titles = sorted(j.title for j in kept)
    assert "Backend Engineer (Go)" in titles
    assert "Software Development Engineer, Core Infra" in titles
    assert "Software Engineer II, Distributed Systems" in titles
    # Stale and wrong city are rejected
    assert "Senior Software Engineer, Platform" not in titles


def test_stale_posting_is_dropped_by_freshness_gate():
    kept = prefilter(fetch_all_mock(), FILTERS)
    assert not any("Senior Software Engineer, Platform" == j.title for j in kept)


def test_wrong_city_dropped_but_remote_kept():
    kept = prefilter(fetch_all_mock(), FILTERS)
    assert not any("San Francisco" in (j.location or "") for j in kept)
    assert any("Remote" in (j.location or "") for j in kept)


def test_allow_remote_is_what_lets_an_out_of_region_remote_role_through():
    remote = Job(job_id="lever:x:1", ats="lever", company="X",
                 title="Backend Engineer", location="Remote - Global",
                 url="https://example.com", description="Go")

    kept_on = prefilter([remote], dict(FILTERS, allow_remote=True))
    kept_off = prefilter([remote], dict(FILTERS, allow_remote=False))

    assert len(kept_on) == 1
    assert kept_off == []


def test_empty_filters_keep_everything():
    jobs = fetch_all_mock()
    assert len(prefilter(jobs, {})) == len(jobs)
