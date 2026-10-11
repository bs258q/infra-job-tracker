"""Fetchers for public applicant-tracking-system job boards."""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

USER_AGENT = "Mozilla/5.0 (compatible; infra-job-tracker/1.0)"
TIMEOUT = 30
WORKDAY_PAGE = 20
WORKDAY_MAX_PER_QUERY = 200


@dataclass
class Job:
    key: str
    company: str
    title: str
    location: str
    url: str
    posted: str = ""
    salary: str = ""
    workplace: str = ""  # remote | hybrid | onsite | "" (not stated)


class BoardNotFound(Exception):
    pass


def _request(url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise BoardNotFound(url) from e
            if e.code != 429 or attempt == 3:
                raise
            retry_after = e.headers.get("Retry-After") or ""
            time.sleep(min(int(retry_after), 30) if retry_after.isdigit() else 2 * 2**attempt)


def _ms_to_date(ms) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()


_MONEY = r"\$\s?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$\s?\d{2,3}(?:\.\d+)?\s?[kK]\b"
_USD_SUFFIX = r"\d{2,3},\d{3}(?:\.\d+)?\s*USD"
_PAY_RANGE = re.compile(
    rf"({_MONEY})\s*(?:USD)?\s*(?:/\s*(?:yr|year))?\s*(?:-|–|—|to)\s*({_MONEY})"
    rf"|({_MONEY})\s*/\s*year.{{0,80}}?up to\s*({_MONEY})"
    rf"|({_USD_SUFFIX})\s*(?:-|–|—|to)\s*({_USD_SUFFIX})",
    re.I | re.S,
)


def find_pay_range(text: str) -> str:
    """First US pay range in a job description, e.g. '$180,000 – $250,000'."""
    if not text:
        return ""
    plain = re.sub(r"<[^>]+>", " ", html.unescape(html.unescape(text)))
    m = _PAY_RANGE.search(plain)
    if not m:
        return ""
    lo, hi = next((m.group(i), m.group(i + 1)) for i in (1, 3, 5) if m.group(i))
    clean = lambda s: "$" + re.sub(r"[\s$]|USD", "", s, flags=re.I)
    return f"{clean(lo)} – {clean(hi)}"


# Only work-arrangement phrasing: "hybrid" alone also means hybrid cloud, hybrid parallelism, etc.
_HYBRID_TEXT = re.compile(
    r"\bhybrid (work(ing)?|schedule|arrangement|policy|position|work model)\b"
    r"|\b(is|be) (a )?hybrid (role|position)\b(?! that)|\b(role|position) is hybrid\b"
    r"|\bhybrid (in|at|from|out of) \w|\(hybrid\)|#LI-hybrid|location-based hybrid"
    r"|\bhybrid[,:-]? [1-4](-[1-4])? days|\b[1-4](-[1-4])? days? (a|per) week (in|at|from) (the|our|an?) office"
    r"|in[- ]office [1-4]\s*days",
    re.I,
)
_ONSITE_TEXT = re.compile(
    r"(fully|100%) (on-?site|in[- ]office)|\b(role|position) is (fully )?(on-?site|in[- ]office)\b"
    r"|in[- ]office 5 days|\b5 days (a|per) week (in|at) (the|our|an?) office|not (a )?remote",
    re.I,
)
_REMOTE_TEXT = re.compile(r"(fully|100%) remote|remote[- ]first|work from anywhere|this (role|position) is remote", re.I)


def workplace_from_text(location: str, description: str = "") -> str:
    if re.search(r"\bremote\b", location, re.I):
        return "remote"
    if re.search(r"\bhybrid\b", location, re.I):
        return "hybrid"
    if description:
        plain = re.sub(r"<[^>]+>", " ", html.unescape(html.unescape(description)))
        if _ONSITE_TEXT.search(plain):
            return "onsite"
        if _HYBRID_TEXT.search(plain):
            return "hybrid"
        if _REMOTE_TEXT.search(plain):
            return "remote"
    return ""


def _normalize_workplace(value: str | None) -> str:
    v = (value or "").lower().replace("-", "").replace("_", "").replace(" ", "")
    if v in {"remote", "fullyremote", "flexible"}:
        return "remote"
    if v in {"hybrid"}:
        return "hybrid"
    if v in {"onsite", "inoffice", "office"}:
        return "onsite"
    return ""


def greenhouse(company: str, slug: str, **_) -> Iterable[Job]:
    data = _request(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    for j in data.get("jobs", []):
        location = (j.get("location") or {}).get("name", "") or ""
        content = j.get("content") or ""
        yield Job(
            key=f"greenhouse:{slug}:{j['id']}",
            company=company,
            title=j["title"].strip(),
            location=location,
            url=j["absolute_url"],
            posted=(j.get("first_published") or j.get("updated_at") or "")[:10],
            salary=find_pay_range(content),
            workplace=workplace_from_text(location, content),
        )


def lever(company: str, slug: str, **_) -> Iterable[Job]:
    data = _request(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    for j in data:
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or [cats.get("location") or ""]
        location = "; ".join(l for l in locs if l)
        if j.get("workplaceType") == "remote" and "remote" not in location.lower():
            location = f"{location} (Remote)".strip()
        salary = ""
        if sr := j.get("salaryRange"):
            salary = f"{sr.get('currency', '')} {sr.get('min', '')}-{sr.get('max', '')}/{sr.get('interval', '')}".strip()
        yield Job(
            key=f"lever:{slug}:{j['id']}",
            company=company,
            title=j["text"].strip(),
            location=location,
            url=j["hostedUrl"],
            posted=_ms_to_date(j.get("createdAt")),
            salary=salary,
            workplace=_normalize_workplace(j.get("workplaceType")) or workplace_from_text(location),
        )


def ashby(company: str, slug: str, **_) -> Iterable[Job]:
    data = _request(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    jobs = data.get("jobs") or []
    if not jobs and data.get("jobs") is None:
        raise BoardNotFound(slug)
    for j in jobs:
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        location = "; ".join(dict.fromkeys(l for l in locs if l))
        if j.get("isRemote") and "remote" not in location.lower():
            location = f"{location} (Remote)".strip()
        comp = j.get("compensation") or {}
        yield Job(
            key=f"ashby:{slug}:{j['id']}",
            company=company,
            title=j["title"].strip(),
            location=location,
            url=j.get("jobUrl") or j.get("applyUrl") or "",
            posted=(j.get("publishedAt") or "")[:10],
            salary=comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary") or "",
            workplace=_normalize_workplace(j.get("workplaceType"))
            or ("remote" if j.get("isRemote") else workplace_from_text(location)),
        )


_MULTI_LOC = re.compile(r"^\d+ Locations$", re.I)
_DAYS_AGO = re.compile(r"Posted (\d+) Days? Ago", re.I)


def _workday_posted(text: str) -> str:
    today = datetime.now(timezone.utc).date()
    if re.search(r"today", text, re.I):
        return today.isoformat()
    if re.search(r"yesterday", text, re.I):
        return (today - timedelta(days=1)).isoformat()
    if m := _DAYS_AGO.search(text):
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    return text.replace("Posted ", "").lower()


def workday(
    company: str,
    host: str,
    tenant: str,
    site: str,
    queries: list[str],
    title_ok: Callable[[str], bool] | None = None,
    **_,
) -> Iterable[Job]:
    """Workday has no list-all endpoint worth paging through for big employers, so search per query."""
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    jobs: dict[str, Job] = {}
    for query in queries:
        offset, total = 0, None
        while offset < WORKDAY_MAX_PER_QUERY:
            data = _request(
                f"{base}/jobs",
                {"appliedFacets": {}, "limit": WORKDAY_PAGE, "offset": offset, "searchText": query},
            )
            if total is None:
                total = data.get("total") or 0
            posts = data.get("jobPostings") or []
            for p in posts:
                path = p.get("externalPath")
                if not path or path in jobs:
                    continue
                jobs[path] = Job(
                    key=f"workday:{tenant}:{path}",
                    company=company,
                    title=p.get("title", "").strip(),
                    location=p.get("locationsText", "") or "",
                    url=f"https://{host}/en-US/{site}{path}",
                    posted=_workday_posted(p.get("postedOn", "") or ""),
                    workplace=_normalize_workplace(p.get("remoteType")),
                )
            offset += WORKDAY_PAGE
            if not posts or offset >= total:
                break

    # Search results only say "N Locations" and "Posted 30+ Days Ago"; the detail call has
    # the real locations, exact posting date, and the pay range from the description.
    def resolve(item: tuple[str, Job]) -> None:
        path, job = item
        try:
            info = _request(f"{base}{path}").get("jobPostingInfo") or {}
        except Exception:
            return
        if _MULTI_LOC.match(job.location):
            locs = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
            job.location = "; ".join(l for l in locs if l) or job.location
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", info.get("startDate") or ""):
            job.posted = info["startDate"]
        description = info.get("jobDescription") or ""
        job.salary = find_pay_range(description)
        job.workplace = (
            job.workplace
            or _normalize_workplace(info.get("remoteType"))
            or workplace_from_text(job.location, description)
        )

    pending = [(path, job) for path, job in jobs.items() if title_ok and title_ok(job.title)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(resolve, pending))
    return list(jobs.values())


def amazon(company: str, queries: list[str], state: str = "California", max_per_query: int = 300, **_) -> Iterable[Job]:
    jobs: dict[str, Job] = {}
    for query in queries:
        offset = 0
        while offset < max_per_query:
            params = urllib.parse.urlencode(
                {
                    "base_query": query,
                    "normalized_country_code[]": "USA",
                    "normalized_state_name[]": state,
                    "result_limit": 100,
                    "offset": offset,
                    "sort": "recent",
                }
            )
            data = _request(f"https://www.amazon.jobs/en/search.json?{params}")
            posts = data.get("jobs") or []
            for p in posts:
                jid = p.get("id_icims") or p.get("id")
                if not jid or jid in jobs:
                    continue
                locs = []
                for raw in p.get("locations") or []:
                    try:
                        locs.append(json.loads(raw).get("normalizedLocation", ""))
                    except (TypeError, ValueError):
                        pass
                posted = p.get("posted_date") or ""
                try:
                    posted = datetime.strptime(" ".join(posted.split()), "%B %d, %Y").date().isoformat()
                except ValueError:
                    pass
                jobs[jid] = Job(
                    key=f"amazon:{jid}",
                    company=company,
                    title=p.get("title", "").strip(),
                    location="; ".join(l for l in locs if l) or p.get("normalized_location", ""),
                    url=f"https://www.amazon.jobs{p.get('job_path', '')}",
                    posted=posted,
                    workplace=workplace_from_text(" ".join(locs)),
                    salary=find_pay_range(" ".join(str(p.get(f) or "") for f in ("description", "preferred_qualifications"))),
                )
            offset += 100
            if len(posts) < 100 or offset >= (data.get("hits") or 0):
                break
    return list(jobs.values())


def eightfold(company: str, host: str, domain: str, queries: list[str], max_per_query: int = 200, **_) -> Iterable[Job]:
    jobs: dict[str, Job] = {}
    for query in queries:
        start = 0
        while start < max_per_query:
            params = urllib.parse.urlencode({"domain": domain, "query": query, "start": start, "num": 10})
            data = _request(f"https://{host}/api/apply/v2/jobs?{params}")
            posts = data.get("positions") or []
            for p in posts:
                jid = str(p.get("id"))
                if jid in jobs:
                    continue
                jobs[jid] = Job(
                    key=f"eightfold:{domain}:{jid}",
                    company=company,
                    title=(p.get("name") or "").strip(),
                    location="; ".join(p.get("locations") or [p.get("location") or ""]),
                    url=p.get("canonicalPositionUrl") or f"https://{host}/careers/job/{jid}",
                    posted=_ms_to_date((p.get("t_create") or 0) * 1000),
                    workplace=_normalize_workplace(p.get("work_location_option"))
                    or workplace_from_text("; ".join(p.get("locations") or [])),
                )
            start += len(posts)
            if not posts or start >= (data.get("count") or 0):
                break
    return list(jobs.values())


def himalayas(company: str, queries: list[str], country: str = "US", max_per_query: int = 400, **_) -> Iterable[Job]:
    """Himalayas remote-job board; `company` is just the source label, jobs carry their own employer."""
    # The search endpoint ignores `offset`; it pages with `page` (1-based, 20 per page) and
    # rate-limits concurrent requests, so pages are fetched one at a time.
    posts: list[dict] = []
    for query in queries:
        n, pages = 1, 1
        while n <= pages:
            params = urllib.parse.urlencode({"q": query, "country": country, "page": n})
            data = _request(f"https://himalayas.app/jobs/api/search?{params}")
            batch = data.get("jobs") or []
            if not batch:
                break
            posts += batch
            pages = min(-(-(data.get("totalCount") or 0) // 20), max_per_query // 20)
            n += 1
            time.sleep(0.3)

    jobs: dict[str, Job] = {}
    for p in posts:
        jid = p.get("guid") or p.get("applicationLink")
        if not jid or jid in jobs:
            continue
        countries = p.get("locationRestrictions") or []
        salary = ""
        if p.get("minSalary") and (p.get("currency") or "USD") == "USD" and p.get("salaryPeriod") in (None, "", "year", "annual", "yearly"):
            salary = f"${p['minSalary']:,} – ${p.get('maxSalary') or p['minSalary']:,}"
        jobs[jid] = Job(
            key=f"himalayas:{jid}",
            company=(p.get("companyName") or "").strip(),
            title=(p.get("title") or "").strip(),
            location="Remote (" + (", ".join(countries) or "Anywhere") + ")",
            url=p.get("applicationLink") or jid,
            posted=_ms_to_date((p.get("pubDate") or 0) * 1000),
            salary=salary,
            workplace="remote",
        )
    return list(jobs.values())


def remotive(company: str, queries: list[str], **_) -> Iterable[Job]:
    jobs: dict[str, Job] = {}
    for query in queries:
        data = _request(f"https://remotive.com/api/remote-jobs?{urllib.parse.urlencode({'search': query})}")
        for p in data.get("jobs") or []:
            jid = str(p.get("id"))
            if jid in jobs:
                continue
            jobs[jid] = Job(
                key=f"remotive:{jid}",
                company=(p.get("company_name") or "").strip(),
                title=(p.get("title") or "").strip(),
                location=f"Remote ({p.get('candidate_required_location') or 'Anywhere'})",
                url=p.get("url") or "",
                posted=(p.get("publication_date") or "")[:10],
                salary=p.get("salary") or "",
                workplace="remote",
            )
    return list(jobs.values())


FETCHERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "workday": workday,
    "amazon": amazon,
    "eightfold": eightfold,
    "himalayas": himalayas,
    "remotive": remotive,
}
