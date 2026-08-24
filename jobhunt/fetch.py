"""Fetch jobs from public ATS APIs and free remote aggregators. No auth, no scraping, no cost."""
from __future__ import annotations

import concurrent.futures
import html
import re
import time
from dataclasses import dataclass, asdict, field
from typing import Any, Iterable

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 jobhunt/1.0"}
TIMEOUT = 8

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<\s*(br|/p|/div|/li|/h[1-6])\s*/?>", "\n", text, flags=re.I)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = _NL.sub("\n\n", text)
    return text.strip()


@dataclass
class Job:
    job_id: str          # stable global id for dedupe: "<ats>:<slug>:<id>"
    ats: str
    company: str
    title: str
    location: str
    url: str
    description: str
    posted_at: str | None = None
    salary: str | None = None
    # filled in later by the pipeline
    score: float | None = None
    reason: str | None = None
    draft: dict[str, Any] = field(default_factory=dict)
    resume_tex_path: str | None = None
    resume_pdf_path: str | None = None
    cover_letter_tex_path: str | None = None
    cover_letter_pdf_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# ATS Parsers
# --------------------------------------------------------------------------

def parse_greenhouse(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("jobs", []):
        loc = (j.get("location") or {}).get("name") or ""
        out.append(Job(
            job_id=f"greenhouse:{slug}:{j.get('id')}",
            ats="greenhouse",
            company=company,
            title=(j.get("title") or "").strip(),
            location=loc.strip(),
            url=j.get("absolute_url") or "",
            description=strip_html(j.get("content")),
            posted_at=j.get("updated_at") or j.get("first_published"),
        ))
    return out


def parse_lever(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or []):
        cats = j.get("categories") or {}
        chunks = [j.get("descriptionPlain") or strip_html(j.get("description"))]
        for lst in (j.get("lists") or []):
            chunks.append(str(lst.get("text") or ""))
            chunks.append(strip_html(lst.get("content")))
        chunks.append(j.get("additionalPlain") or strip_html(j.get("additional")))
        ts = j.get("createdAt")
        posted = None
        if isinstance(ts, (int, float)):
            posted = time.strftime("%Y-%m-%d", time.gmtime(ts / 1000))
        out.append(Job(
            job_id=f"lever:{slug}:{j.get('id')}",
            ats="lever",
            company=company,
            title=(j.get("text") or "").strip(),
            location=(cats.get("location") or "").strip(),
            url=j.get("hostedUrl") or j.get("applyUrl") or "",
            description="\n\n".join(c for c in chunks if c).strip(),
            posted_at=posted,
            salary=cats.get("commitment"),
        ))
    return out


def parse_ashby(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("jobs", []):
        if j.get("isListed") is False:
            continue
        comp = j.get("compensation") or {}
        salary = None
        summary = comp.get("compensationTierSummary") or comp.get("summaryComponents")
        if isinstance(summary, str):
            salary = summary
        out.append(Job(
            job_id=f"ashby:{slug}:{j.get('id')}",
            ats="ashby",
            company=company,
            title=(j.get("title") or "").strip(),
            location=(j.get("location") or "").strip(),
            url=j.get("jobUrl") or j.get("applyUrl") or "",
            description=(j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")) or "").strip(),
            posted_at=j.get("publishedAt"),
            salary=salary,
        ))
    return out


def parse_workable(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    results = (body or {}).get("results", []) or (body or {}).get("jobs", [])
    for j in results:
        loc = ", ".join(filter(None, [j.get("city"), j.get("region"), j.get("country")]))
        if j.get("telecommuting"):
            loc = f"Remote ({loc})" if loc else "Remote"
        jid = j.get("shortcode") or j.get("id")
        out.append(Job(
            job_id=f"workable:{slug}:{jid}",
            ats="workable",
            company=company,
            title=(j.get("title") or "").strip(),
            location=loc.strip(),
            url=j.get("url") or j.get("shortlink") or f"https://apply.workable.com/{slug}/j/{jid}/",
            description=strip_html(j.get("description")),
            posted_at=j.get("published_on") or j.get("created_at"),
        ))
    return out


def parse_smartrecruiters(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("content", []):
        loc_data = j.get("location") or {}
        loc = ", ".join(filter(None, [loc_data.get("city"), loc_data.get("region"), loc_data.get("country")]))
        if loc_data.get("remote"):
            loc = f"Remote ({loc})" if loc else "Remote"
        jid = j.get("id")
        out.append(Job(
            job_id=f"smartrecruiters:{slug}:{jid}",
            ats="smartrecruiters",
            company=company,
            title=(j.get("name") or "").strip(),
            location=loc.strip(),
            url=f"https://jobs.smartrecruiters.com/{slug}/{jid}",
            description=strip_html(j.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text", "")),
            posted_at=j.get("releasedDate"),
        ))
    return out


def parse_recruitee(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("offers", []):
        loc = ", ".join(filter(None, [j.get("city"), j.get("country")]))
        if j.get("remote"):
            loc = f"Remote ({loc})" if loc else "Remote"
        jid = j.get("id")
        out.append(Job(
            job_id=f"recruitee:{slug}:{jid}",
            ats="recruitee",
            company=company,
            title=(j.get("title") or "").strip(),
            location=loc.strip(),
            url=j.get("careers_url") or "",
            description=strip_html(j.get("description")),
            posted_at=j.get("created_at") or j.get("published_at"),
        ))
    return out


def parse_breezy(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    items = body if isinstance(body, list) else []
    for j in items:
        loc_data = j.get("location") or {}
        loc = loc_data.get("name") or ""
        if loc_data.get("is_remote"):
            loc = f"Remote ({loc})" if loc else "Remote"
        jid = j.get("_id") or j.get("id")
        out.append(Job(
            job_id=f"breezy:{slug}:{jid}",
            ats="breezy",
            company=company,
            title=(j.get("name") or "").strip(),
            location=loc.strip(),
            url=j.get("url") or f"https://{slug}.breezy.hr/p/{jid}",
            description=strip_html(j.get("description")),
            posted_at=j.get("creation_date"),
        ))
    return out


# --------------------------------------------------------------------------
# Free Global Remote Aggregator Parsers
# --------------------------------------------------------------------------

def parse_remotive(_: str, __: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("jobs", []):
        jid = str(j.get("id"))
        company = (j.get("company_name") or "Remote Company").strip()
        loc = (j.get("candidate_required_location") or "Worldwide / Remote").strip()
        out.append(Job(
            job_id=f"remotive:global:{jid}",
            ats="remotive",
            company=company,
            title=(j.get("title") or "").strip(),
            location=f"Remote ({loc})",
            url=j.get("url") or "",
            description=strip_html(j.get("description")),
            posted_at=j.get("publication_date"),
            salary=j.get("salary"),
        ))
    return out


def parse_remoteok(_: str, __: str, body: Any) -> list[Job]:
    out = []
    items = body if isinstance(body, list) else []
    for j in items:
        if not isinstance(j, dict) or not j.get("id"):
            continue
        jid = str(j.get("id"))
        company = (j.get("company") or "Remote Company").strip()
        loc = (j.get("location") or "Worldwide / Remote").strip()
        out.append(Job(
            job_id=f"remoteok:global:{jid}",
            ats="remoteok",
            company=company,
            title=(j.get("position") or "").strip(),
            location=f"Remote ({loc})",
            url=j.get("url") or f"https://remoteok.com/remote-jobs/{jid}",
            description=strip_html(j.get("description")),
            posted_at=j.get("date"),
        ))
    return out


def parse_arbeitnow(_: str, __: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("data", []):
        jid = j.get("slug") or str(j.get("id") or "")
        company = (j.get("company_name") or "Tech Company").strip()
        loc = j.get("location") or ""
        if j.get("remote"):
            loc = f"Remote ({loc})" if loc else "Remote"
        out.append(Job(
            job_id=f"arbeitnow:global:{jid}",
            ats="arbeitnow",
            company=company,
            title=(j.get("title") or "").strip(),
            location=loc.strip(),
            url=j.get("url") or "",
            description=strip_html(j.get("description")),
            posted_at=time.strftime("%Y-%m-%d", time.gmtime(j.get("created_at"))) if isinstance(j.get("created_at"), (int, float)) else None,
        ))
    return out


def parse_jobicy(_: str, __: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("jobs", []):
        jid = str(j.get("id"))
        company = (j.get("companyName") or "Tech Company").strip()
        loc = (j.get("jobGeo") or "Worldwide / Remote").strip()
        out.append(Job(
            job_id=f"jobicy:global:{jid}",
            ats="jobicy",
            company=company,
            title=(j.get("jobTitle") or "").strip(),
            location=f"Remote ({loc})",
            url=j.get("url") or "",
            description=strip_html(j.get("jobDescription")),
            posted_at=j.get("pubDate"),
        ))
    return out


def parse_himalayas(_: str, __: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("jobs", []):
        jid = str(j.get("id") or "")
        company = (j.get("companyName") or "Tech Company").strip()
        restrs = j.get("locationRestrictions") or []
        loc = ", ".join(restrs) if restrs else "Worldwide / Remote"
        out.append(Job(
            job_id=f"himalayas:global:{jid}",
            ats="himalayas",
            company=company,
            title=(j.get("title") or "").strip(),
            location=f"Remote ({loc})",
            url=j.get("applicationUrl") or f"https://himalayas.app/companies/{j.get('companySlug')}/jobs/{j.get('slug')}",
            description=strip_html(j.get("description")),
            posted_at=j.get("publishedAt"),
        ))
    return out


def parse_hasjob_xml(xml_text: str) -> list[Job]:
    import xml.etree.ElementTree as ET
    out = []
    try:
        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title_raw = entry.findtext("atom:title", default="", namespaces=ns)
            link_elem = entry.find("atom:link", ns)
            link = link_elem.attrib.get("href", "") if link_elem is not None else ""
            content = entry.findtext("atom:content", default="", namespaces=ns) or entry.findtext("atom:summary", default="", namespaces=ns)
            pub = entry.findtext("atom:published", default="", namespaces=ns) or entry.findtext("atom:updated", default="", namespaces=ns)

            parts = re.split(r"\s+at\s+", title_raw, maxsplit=1, flags=re.I)
            title = parts[0].strip()
            company = parts[1].strip() if len(parts) > 1 else "Hasjob Startup"

            out.append(Job(
                job_id=f"hasjob:{abs(hash(link))}",
                ats="hasjob",
                company=company,
                title=title,
                location="India / Remote",
                url=link,
                description=strip_html(content),
                posted_at=pub,
            ))
    except Exception:
        pass
    return out


ENDPOINTS = {
    "greenhouse":       ("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", parse_greenhouse),
    "lever":            ("https://api.lever.co/v0/postings/{slug}?mode=json", parse_lever),
    "ashby":            ("https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true", parse_ashby),
    "workable":         ("https://apply.workable.com/api/v3/accounts/{slug}/jobs", parse_workable),
    "smartrecruiters":  ("https://api.smartrecruiters.com/v1/companies/{slug}/postings", parse_smartrecruiters),
    "recruitee":        ("https://{slug}.recruitee.com/api/offers", parse_recruitee),
    "breezy":           ("https://{slug}.breezy.hr/json", parse_breezy),
}

REMOTE_FEEDS = {
    "remotive":   ("https://remotive.com/api/remote-jobs?category=software-dev,data&limit=100", parse_remotive),
    "remoteok":   ("https://remoteok.com/api", parse_remoteok),
    "arbeitnow":  ("https://www.arbeitnow.com/api/job-board-api", parse_arbeitnow),
    "jobicy":     ("https://jobicy.com/api/v2/remote-jobs?count=50&industry=engineering", parse_jobicy),
    "himalayas":  ("https://himalayas.app/jobs/api?limit=50", parse_himalayas),
    "hasjob":     ("https://hasjob.co/feed", None),
}


def fetch_board(ats: str, slug: str, company: str | None = None,
                session: requests.Session | None = None) -> list[Job]:
    """Hit one company's public board. Returns [] on any failure (never raises)."""
    if ats not in ENDPOINTS:
        return []
    url_tpl, parser = ENDPOINTS[ats]
    sess = session or requests
    try:
        r = sess.get(url_tpl.format(slug=slug), headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        return parser(slug, company or slug, r.json())
    except Exception:
        return []


def fetch_remote_feed(feed_name: str, session: requests.Session | None = None) -> list[Job]:
    """Hit a free public remote job aggregator feed."""
    if feed_name == "hasjob":
        sess = session or requests
        try:
            r = sess.get("https://hasjob.co/feed", headers=UA, timeout=TIMEOUT)
            if r.status_code == 200:
                return parse_hasjob_xml(r.text)
        except Exception:
            return []
    if feed_name not in REMOTE_FEEDS:
        return []
    url, parser = REMOTE_FEEDS[feed_name]
    if parser is None:
        return []
    sess = session or requests
    try:
        r = sess.get(url, headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        return parser("", feed_name, r.json())
    except Exception:
        return []


def fetch_linkedin(query: str, location: str = "India", count: int = 25) -> list[Job]:
    """Fetch recent live jobs from LinkedIn's public guest search API (past 7 days only)."""
    import urllib.parse
    # f_TPR=r604800 restricts results to the past 1 week (604,800 seconds)
    url = (
        f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={urllib.parse.quote(query)}&location={urllib.parse.quote(location)}&f_TPR=r604800&start=0"
    )
    out = []
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return []

        cards = re.findall(r'<li[\s\S]*?</li>', r.text)
        for card in cards:
            title_m = re.search(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>([^<]+)</h3>', card)
            company_m = re.search(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[\s\S]*?>([^<]+)<', card)
            if not company_m:
                company_m = re.search(r'<a[^>]*class="[^"]*hidden-nested-link[^"]*"[^>]*>([^<]+)</a>', card)
            loc_m = re.search(r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>([^<]+)</span>', card)
            link_m = re.search(r'<a[^>]*class="[^"]*base-card__full-link[^"]*"[^>]*href="([^"?]+)', card)
            time_m = re.search(r'<time[^>]*datetime="([^"]+)"', card)

            if not title_m or not link_m:
                continue

            raw_title = title_m.group(1).strip()
            raw_company = company_m.group(1).strip() if company_m else "LinkedIn Posting"
            raw_loc = loc_m.group(1).strip() if loc_m else location
            raw_url = link_m.group(1).strip()
            posted_date = time_m.group(1).strip() if time_m else None

            jid_m = re.search(r'-([0-9]{8,12})(?:\?|$)', raw_url)
            jid = jid_m.group(1) if jid_m else str(abs(hash(raw_url)))

            clean_title = html.unescape(raw_title)
            clean_company = html.unescape(raw_company)
            clean_loc = html.unescape(raw_loc)
            slug = re.sub(r'[^a-zA-Z0-9]', '', clean_company.lower())[:15] or "company"

            out.append(Job(
                job_id=f"linkedin:{slug}:{jid}",
                ats="linkedin",
                company=clean_company,
                title=clean_title,
                location=clean_loc,
                url=raw_url,
                description=f"{clean_title} at {clean_company} in {clean_loc}. Direct job listing on LinkedIn.",
                posted_at=posted_date,
            ))
            if len(out) >= count:
                break
    except Exception:
        return []
    return out


def fetch_unstop(query: str, count: int = 25, opportunity: str = "jobs") -> list[Job]:
    """Fetch live off-campus fresher & junior jobs or internships from Unstop's public API."""
    import urllib.parse
    url = f"https://unstop.com/api/public/opportunity/search-result?opportunity={opportunity}&per_page={count}&searchTerm={urllib.parse.quote(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    out = []
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        items = (data.get("data") or {}).get("data") or []
        for it in items:
            jid = str(it.get("id") or "")
            title = it.get("title") or ""
            org = (it.get("organisation") or {}).get("name") or "Hiring Company"
            seo_url = it.get("seo_url") or (f"https://unstop.com/{it.get('public_url')}" if it.get("public_url") else "")
            desc = strip_html(it.get("details") or "")
            posted = it.get("updated_at") or it.get("approved_date")

            # Extract city locations
            loc_list = [loc.get("city") for loc in (it.get("locations") or []) if loc.get("city")]
            loc = ", ".join(loc_list) if loc_list else "India"

            slug = re.sub(r'[^a-zA-Z0-9]', '', org.lower())[:15] or "unstop"
            opp_label = "Internship" if opportunity == "internships" else "Job"
            out.append(Job(
                job_id=f"unstop:{slug}:{opportunity}:{jid}",
                ats="unstop",
                company=org,
                title=title,
                location=loc,
                url=seo_url,
                description=desc or f"{title} at {org}. Off-campus fresher {opp_label} opportunity on Unstop.",
                posted_at=posted,
            ))
            if len(out) >= count:
                break
    except Exception:
        return []
    return out


def fetch_all(companies: Iterable[dict], include_remote_feeds: bool = True,
              linkedin_searches: Iterable[dict] | None = None,
              unstop_searches: Iterable[str] | None = None,
              max_workers: int = 24) -> list[Job]:
    """Fetch jobs concurrently from all company ATS boards, remote feeds, LinkedIn, and Unstop."""
    jobs: list[Job] = []
    fut_map = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all company ATS boards
        for c in companies:
            ats = c.get("ats")
            slug = c.get("slug")
            name = c.get("name") or slug
            if ats and slug:
                fut = executor.submit(fetch_board, ats, slug, name)
                fut_map[fut] = (name, ats)

        # Submit free remote aggregator feeds
        if include_remote_feeds:
            for feed_key in REMOTE_FEEDS:
                fut = executor.submit(fetch_remote_feed, feed_key)
                fut_map[fut] = (f"Feed ({feed_key})", "remote-feed")

        # Submit LinkedIn search queries
        if linkedin_searches:
            for s in linkedin_searches:
                q = s.get("query")
                loc = s.get("location", "India")
                if q:
                    fut = executor.submit(fetch_linkedin, q, loc)
                    fut_map[fut] = (f"LinkedIn ({q} - {loc})", "linkedin")

        # Submit Unstop search queries (both jobs and internships)
        if unstop_searches:
            for q in unstop_searches:
                if q:
                    fut_jobs = executor.submit(fetch_unstop, q, 25, "jobs")
                    fut_map[fut_jobs] = (f"Unstop Jobs ({q})", "unstop")
                    fut_interns = executor.submit(fetch_unstop, q, 25, "internships")
                    fut_map[fut_interns] = (f"Unstop Intern ({q})", "unstop")

        for fut in concurrent.futures.as_completed(fut_map):
            name, src = fut_map[fut]
            try:
                got = fut.result()
                if got:
                    print(f"  {name:<32} {len(got):>4} jobs  ({src})", flush=True)
                    jobs.extend(got)
            except Exception as e:
                print(f"  ! {name} failed: {e}", flush=True)

    return jobs

