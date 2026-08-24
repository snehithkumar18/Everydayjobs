"""Deterministic filter that runs BEFORE any LLM call.

This is the whole cost story: ~12,000 raw jobs -> ~30-50 high-signal candidates for 0 rupees,
ensuring LLMs only process jobs that are strictly open to freshers / 0-1 years experience.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .fetch import Job

REMOTE_HINTS = (
    "remote", "anywhere", "work from home", "wfh", "distributed",
    "worldwide", "global", "telecommute", "virtual", "work from anywhere",
)

# Geographic filters for remote listings
RESTRICTED_NON_INDIA_PATTERNS = [
    r"\b(us only|u\.s\. only|usa only|united states only|north america only|canada only|uk only|europe only|eu only|emea only|latam only)\b",
    r"\b(remote\s*[-–—]\s*(?:us|usa|uk|canada|germany|france|australia))\b",
    r"\b(remote\s*\((?:us|usa|uk|canada|germany|france|australia)\))\b",
]

# Hard rejection patterns for senior/experienced roles in title
SENIORITY_TITLE_PATTERNS = [
    r"\b(?:sr\.?|senior|lead|principal|staff|architect|director|manager|vp|vice\s+president|head\s+of|chief|distinguished)\b",
    r"\b(?:tech\s+lead|team\s+lead|engineering\s+lead|group\s+lead)\b",
    r"\b(?:mid[- ]?level|mid[- ]?senior|experienced|expert|specialist|consultant|senior\s+consultant)\b",
    r"\b(?:sde[- ]?(?:2|3|4|5|ii|iii|iv|v)|software\s+engineer[- ]?(?:2|3|4|5|ii|iii|iv|v))\b",
    r"\b(?:engineer[- ]?(?:2|3|4|5|ii|iii|iv|v)|developer[- ]?(?:2|3|4|5|ii|iii|iv|v))\b",
    r"\b(?:l2|l3|l4|l5|l6|e4|e5|e6|ic4|ic5|ic6)\b",
]

# Patterns in JD description requiring 2+ or higher years of experience
OVER_EXPERIENCE_PATTERNS = [
    # "2+ years", "3-5 years", "min 2 years of experience", "at least 3 yrs"
    r"(?:minimum|at least|req(?:uire)?s?|having|with)\s+(?:of\s+)?([2-9]|\d{2,})\+?\s*(?:to\s*\d+\s*)?(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp|relevant experience)",
    r"\b([2-9]|\d{2,})\s*\+\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp|relevant experience|work experience)\b",
    r"\b([2-9]|\d{2,})\s*(?:-|to)\s*\d+\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp|relevant experience)\b",
    r"\bexperience\s*(?:required|needed|level)?\s*:\s*([2-9]|\d{2,})\+?\s*(?:years?|yrs?)\b",
    r"\b([2-9]|\d{2,})\+?\s*(?:years?|yrs?)\s+in\s+(?:software|development|python|java|engineering|fullstack|react|backend|ai|ml)",
    r"\b([2-9]|\d{2,})\+?\s*(?:years?|yrs?)\s+(?:commercial|industry|professional|hands-on)\s+experience\b",
]

# Positive signals that confirm a role is meant for freshers/entry-level
FRESHER_SIGNALS = [
    r"\b(?:fresher|freshers|0\s*[-–—to]\s*[12]\s*years?|0\s*years?|entry[- ]?level|junior|jr\.?|intern|internship|trainee|graduate|campus|apprentice)\b",
    r"\b(?:no\s+(?:prior\s+)?experience\s+required|open\s+to\s+freshers|recent\s+graduates?|2024|2025|2026\s+batch)\b",
]

SENIORITY_TITLE_COMPILED = [re.compile(p, re.I) for p in SENIORITY_TITLE_PATTERNS]
OVER_EXPERIENCE_COMPILED = [re.compile(p, re.I) for p in OVER_EXPERIENCE_PATTERNS]
FRESHER_SIGNALS_COMPILED = [re.compile(p, re.I) for p in FRESHER_SIGNALS]


def _any_compiled(compiled: list[re.Pattern], text: str) -> bool:
    return any(p.search(text) for p in compiled)


def _any_match(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.fromisoformat(v) if fmt is None else datetime.strptime(v, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def requires_too_much_experience(job: Job) -> bool:
    """Returns True if the job strictly requires 2+ years of professional experience."""
    combined_text = f"{job.title} {job.description[:3000]}".lower()

    # Check if job explicitly welcomes freshers or 0-1 / 0-2 yrs
    is_explicit_fresher = _any_compiled(FRESHER_SIGNALS_COMPILED, combined_text)

    # Check if title has senior designations
    if _any_compiled(SENIORITY_TITLE_COMPILED, job.title):
        return True

    # If not explicitly a fresher role, check if description mentions 2+ years of experience
    if not is_explicit_fresher:
        if _any_compiled(OVER_EXPERIENCE_COMPILED, combined_text):
            return True

    return False


RESTRICTED_NON_INDIA_COMPILED = [re.compile(p, re.I) for p in RESTRICTED_NON_INDIA_PATTERNS]


def prefilter(jobs: list[Job], cfg: dict) -> list[Job]:
    if not cfg:
        return list(jobs)

    inc = cfg.get("include_titles") or [r"."]
    exc = cfg.get("exclude_titles") or []
    inc_compiled = [re.compile(p, re.I) for p in inc]
    exc_compiled = [re.compile(p, re.I) for p in exc]
    locs = [l.lower() for l in (cfg.get("locations") or [])]
    allow_remote = bool(cfg.get("allow_remote", True))
    max_age = cfg.get("max_age_days")
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age) if max_age else None
    check_exp = bool(cfg.get("strict_fresher_filter", True))

    kept = []
    stats = {"title": 0, "location": 0, "age": 0, "experience": 0}

    for j in jobs:
        # 1. Title inclusion / exclusion check
        if not _any_compiled(inc_compiled, j.title) or (exc_compiled and _any_compiled(exc_compiled, j.title)):
            stats["title"] += 1
            continue

        # 2. Hard Seniority / Experience filter (Fresher only)
        if check_exp and requires_too_much_experience(j):
            stats["experience"] += 1
            continue

        # 3. Location / Remote check
        if locs:
            hay = f"{j.location} {j.title}".lower()
            is_remote = allow_remote and any(h in hay for h in REMOTE_HINTS)
            if is_remote and _any_compiled(RESTRICTED_NON_INDIA_COMPILED, hay):
                if not any(l in hay for l in locs) and not any(g in hay for g in ("worldwide", "global", "anywhere", "apac", "all locations")):
                    is_remote = False

            if not is_remote and not any(l in hay for l in locs):
                stats["location"] += 1
                continue

        # 4. Freshness / Age check
        if cutoff:
            posted = _parse_date(j.posted_at)
            if posted and posted < cutoff:
                stats["age"] += 1
                continue

        kept.append(j)

    print(f"  prefilter: {len(jobs)} -> {len(kept)} "
          f"(dropped title={stats['title']} exp_req_>1yr={stats['experience']} "
          f"location={stats['location']} stale={stats['age']})")
    return kept
