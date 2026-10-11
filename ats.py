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
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable

import usgeo

USER_AGENT = "Mozilla/5.0 (compatible; infra-job-tracker/1.0)"
TIMEOUT = 30
WORKDAY_PAGE = 20
WORKDAY_MAX_PER_QUERY = 200  # only for worldwide searches on boards without a usable location facet
WORKDAY_MAX_RESULTS = 2000  # Workday caps `total` and stops paging here
WORKDAY_MAX_FACET_IDS = 200


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
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise BoardNotFound(url) from e
            # Rate limits are retried longest; server errors and timeouts are often transient too.
            if not (e.code == 429 and attempt < 5 or e.code in (500, 502, 503, 504) and attempt < 2):
                raise
            retry_after = e.headers.get("Retry-After") or ""
            time.sleep(min(int(retry_after), 30) if retry_after.isdigit() else min(2 * 2**attempt, 30))
        except (urllib.error.URLError, TimeoutError):
            if attempt >= 2:
                raise
            time.sleep(2 * 2**attempt)


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


def workday_location_facet(facets: list[dict], location_ok: Callable[[str], bool]) -> dict[str, list[str]] | None:
    """The board's location facet values that pass `location_ok`, as Workday `appliedFacets`.

    Boards expose location facets at several levels (city list, country, a Remote/On-site split),
    sometimes nested in groups like `locationMainGroup`. Use the most granular one: every posting has
    a city, while a coarse value such as "Remote" passes `location_ok` without covering offices.
    Returns {} when every location matches, None when the board has no location facet that matches.
    """
    finest: tuple[str, list[dict]] | None = None
    stack = list(facets)
    while stack:
        facet = stack.pop()
        values = facet.get("values") or []
        if any("facetParameter" in v for v in values):
            stack.extend(values)
            continue
        param = facet.get("facetParameter") or ""
        if "location" in param.lower() and (finest is None or len(values) > len(finest[1])):
            finest = param, values
    if finest is None:
        return None
    param, values = finest
    hits = [v["id"] for v in values if v.get("id") and location_ok(v.get("descriptor") or "")]
    if not hits:
        return None
    return {} if len(hits) == len(values) else {param: hits}


def workday(
    company: str,
    host: str,
    tenant: str,
    site: str,
    queries: list[str],
    title_ok: Callable[[str], bool] | None = None,
    location_ok: Callable[[str], bool] | None = None,
    **_,
) -> Iterable[Job]:
    """List every posting in the profile's locations via the board's location facet. Falls back to
    searching per query when that is over Workday's result cap, or when the board has no usable facet."""
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    jobs: dict[str, Job] = {}

    def page(search: str, facets: dict, offset: int) -> dict:
        return _request(
            f"{base}/jobs",
            {"appliedFacets": facets, "limit": WORKDAY_PAGE, "offset": offset, "searchText": search},
        )

    def collect(search: str, facets: dict, limit: int, first: dict | None = None) -> None:
        first = first or page(search, facets, 0)
        total = min(first.get("total") or 0, limit)
        with ThreadPoolExecutor(max_workers=4) as pool:
            rest = pool.map(lambda o: page(search, facets, o), range(WORKDAY_PAGE, total, WORKDAY_PAGE))
            for data in [first, *rest]:
                for p in data.get("jobPostings") or []:
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

    located = workday_location_facet(page("", {}, 0).get("facets") or [], location_ok) if location_ok else None
    if located is None:
        for query in queries:
            collect(query, {}, WORKDAY_MAX_PER_QUERY)
    elif sum(len(ids) for ids in located.values()) > WORKDAY_MAX_FACET_IDS:
        # Workday rejects requests with a few hundred facet values (e.g. every US city on a big board);
        # such a selection is most of the board anyway, so search it and filter locations afterwards.
        for query in queries:
            collect(query, {}, WORKDAY_MAX_RESULTS)
    else:
        listing = page("", located, 0)
        if (listing.get("total") or 0) < WORKDAY_MAX_RESULTS:
            collect("", located, WORKDAY_MAX_RESULTS, listing)
        else:
            for query in queries:
                collect(query, located, WORKDAY_MAX_RESULTS)

    # Search results only say "N Locations" and "Posted 30+ Days Ago"; the detail call has
    # the real locations, exact posting date, and the pay range from the description.
    def resolve(item: tuple[str, Job]) -> None:
        path, job = item
        try:
            info = _request(f"{base}{path}").get("jobPostingInfo") or {}
        except Exception:
            return
        if not job.location or _MULTI_LOC.match(job.location):
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
    """Lists every posting in `state` (a few thousand at most), so titles the search terms miss still match."""
    jobs: dict[str, Job] = {}
    for query, limit in [("", 10_000)] if state else [(q, max_per_query) for q in queries]:
        offset = 0
        while offset < limit:
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


def yc(company: str, slug: str, **_) -> Iterable[Job]:
    """A YC company's public jobs page (ycombinator.com/companies/<slug>/jobs, mirrors Work at a Startup)."""
    req = urllib.request.Request(f"https://www.ycombinator.com/companies/{slug}/jobs", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            page = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise BoardNotFound(slug) from e
        raise
    m = re.search(r'data-page="([^"]+)"', page)
    if not m:
        raise BoardNotFound(slug)
    for j in json.loads(html.unescape(m.group(1))).get("props", {}).get("jobPostings") or []:
        location = j.get("location") or ""
        yield Job(
            key=f"yc:{slug}:{j['id']}",
            company=company,
            title=(j.get("title") or "").strip(),
            location=location,
            url=f"https://www.ycombinator.com{j.get('url', '')}",
            salary=j.get("salaryRange") or "",
            workplace=workplace_from_text(location),
        )


def workable(company: str, slug: str, **_) -> Iterable[Job]:
    data = _request(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    # The widget repeats a job once per location under the same shortcode.
    by_code: dict[str, list[dict]] = {}
    for j in data.get("jobs") or []:
        by_code.setdefault(j["shortcode"], []).append(j)
    for copies in by_code.values():
        j = copies[0]
        locs = [", ".join(p for p in (l.get("city"), l.get("region"), l.get("country")) if p)
                for c in copies for l in c.get("locations") or [] if not l.get("hidden")]
        location = "; ".join(dict.fromkeys(l for l in locs if l))
        if j.get("telecommuting") and "remote" not in location.lower():
            location = f"{location} (Remote)".strip()
        yield Job(
            key=f"workable:{slug}:{j['shortcode']}",
            company=company,
            title=(j.get("title") or "").strip(),
            location=location,
            url=j.get("url") or f"https://apply.workable.com/j/{j['shortcode']}",
            posted=j.get("published_on") or "",
            workplace="remote" if j.get("telecommuting") else workplace_from_text(location),
        )


def gem(company: str, slug: str, **_) -> Iterable[Job]:
    for j in _request(f"https://api.gem.com/job_board/v0/{slug}/job_posts/"):
        location = "; ".join(dict.fromkeys(
            o["location"]["name"] for o in j.get("offices") or [] if (o.get("location") or {}).get("name")
        )) or (j.get("location") or {}).get("name", "")
        content = j.get("content") or ""
        yield Job(
            key=f"gem:{slug}:{j['id']}",
            company=company,
            title=(j.get("title") or "").strip(),
            location=location,
            url=j.get("absolute_url") or "",
            posted=(j.get("first_published_at") or "")[:10],
            salary=find_pay_range(content),
            workplace=_normalize_workplace(j.get("location_type")) or workplace_from_text(location, content),
        )


def smartrecruiters(company: str, slug: str, **_) -> Iterable[Job]:
    offset, total = 0, 1
    while offset < total:
        data = _request(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}")
        posts = data.get("content") or []
        total = data.get("totalFound") or 0
        for j in posts:
            loc = j.get("location") or {}
            location = loc.get("fullLocation") or ", ".join(p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p)
            if loc.get("remote") and "remote" not in location.lower():
                location = f"{location} (Remote)".strip()
            yield Job(
                key=f"smartrecruiters:{slug}:{j['id']}",
                company=company,
                title=(j.get("name") or "").strip(),
                location=location,
                url=f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                posted=(j.get("releasedDate") or "")[:10],
                workplace="remote" if loc.get("remote") else "hybrid" if loc.get("hybrid") else workplace_from_text(location),
            )
        if not posts:
            break
        offset += len(posts)


def rippling(company: str, slug: str, **_) -> Iterable[Job]:
    # The board repeats a job once per location under the same id.
    by_id: dict[str, list[dict]] = {}
    page, pages = 0, 1
    while page < pages:
        data = _request(f"https://ats.rippling.com/api/v2/board/{slug}/jobs?page={page}&pageSize=100")
        pages = data.get("totalPages") or 0
        for j in data.get("items") or []:
            by_id.setdefault(j["id"], []).append(j)
        page += 1
    for jid, copies in by_id.items():
        locs = [l for c in copies for l in c.get("locations") or []]
        location = "; ".join(dict.fromkeys(l.get("name", "") for l in locs if l.get("name")))
        workplaces = [_normalize_workplace(l.get("workplaceType")) for l in locs]
        workplace = next((w for w in ("remote", "hybrid", "onsite") if w in workplaces), "")
        if workplace == "remote" and "remote" not in location.lower():
            location = f"{location} (Remote)".strip()
        yield Job(
            key=f"rippling:{slug}:{jid}",
            company=company,
            title=(copies[0].get("name") or "").strip(),
            location=location,
            url=copies[0].get("url") or f"https://ats.rippling.com/{slug}/jobs/{jid}",
            workplace=workplace or workplace_from_text(location),
        )


def recruitee(company: str, slug: str, **_) -> Iterable[Job]:
    for j in _request(f"https://{slug}.recruitee.com/api/offers/").get("offers") or []:
        location = j.get("location") or ", ".join(p for p in (j.get("city"), j.get("country")) if p)
        if j.get("remote") and "remote" not in location.lower():
            location = f"{location} (Remote)".strip()
        pay = j.get("salary") or {}
        salary = f"${pay['min']:,} – ${pay['max']:,}" if pay.get("currency") == "USD" and pay.get("min") and pay.get("max") else ""
        yield Job(
            key=f"recruitee:{slug}:{j['id']}",
            company=company,
            title=(j.get("title") or "").strip(),
            location=location,
            url=j.get("careers_url") or "",
            posted=(j.get("published_at") or "")[:10],
            salary=salary,
            workplace="remote" if j.get("remote") else "hybrid" if j.get("hybrid") else "onsite" if j.get("on_site") else "",
        )


def breezy(company: str, slug: str, **_) -> Iterable[Job]:
    for j in _request(f"https://{slug}.breezy.hr/json"):
        loc = j.get("location") or {}
        location = loc.get("name") or ""
        if loc.get("is_remote") and "remote" not in location.lower():
            location = f"{location} (Remote)".strip()
        yield Job(
            key=f"breezy:{slug}:{j['id']}",
            company=company,
            title=(j.get("name") or "").strip(),
            location=location,
            url=j.get("url") or "",
            posted=(j.get("published_date") or "")[:10],
            salary=j.get("salary") or "",
            workplace="remote" if loc.get("is_remote") else workplace_from_text(location),
        )


def oracle(company: str, host: str, site: str, queries: list[str], max_per_query: int = 200, **_) -> Iterable[Job]:
    """Oracle Recruiting Cloud (`<host>/hcmUI/CandidateExperience/en/sites/<site>`), searched by keyword."""
    jobs: dict[str, Job] = {}
    for query in queries:
        offset = 0
        while offset < max_per_query:
            finder = f'findReqs;siteNumber={site},keyword="{query}",limit=25,offset={offset}'
            data = _request(
                f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
                f"&expand=requisitionList.secondaryLocations&finder={urllib.parse.quote(finder, safe='=;,')}"
            )
            result = (data.get("items") or [{}])[0]
            reqs = result.get("requisitionList") or []
            for r in reqs:
                locs = [r.get("PrimaryLocation") or ""] + [s.get("Name", "") for s in r.get("secondaryLocations") or []]
                location = "; ".join(dict.fromkeys(l for l in locs if l))
                jobs.setdefault(str(r["Id"]), Job(
                    key=f"oracle:{host}:{r['Id']}",
                    company=company,
                    title=(r.get("Title") or "").strip(),
                    location=location,
                    url=f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{r['Id']}",
                    posted=r.get("PostedDate") or "",
                    workplace=_normalize_workplace((r.get("WorkplaceTypeCode") or "").removeprefix("ORA_"))
                    or workplace_from_text(location),
                ))
            offset += 25
            if len(reqs) < 25 or offset >= (result.get("TotalJobsCount") or 0):
                break
    return list(jobs.values())


# ---------- Multi-employer boards: `company` is only the source label; jobs carry their own employer ----------

def _usd_range(lo, hi) -> str:
    return f"${int(lo):,} – ${int(hi or lo):,}" if lo and int(lo) > 0 else ""


def remoteok(company: str, **_) -> Iterable[Job]:
    """Remote OK's latest ~100 postings (its API terms: link back to the Remote OK job page, which `url` does)."""
    for p in _request("https://remoteok.com/api")[1:]:
        yield Job(
            key=f"remoteok:{p['id']}",
            company=(p.get("company") or "").strip(),
            title=html.unescape(p.get("position") or "").strip(),
            location=f"Remote ({p.get('location') or 'Anywhere'})",
            url=p.get("url") or "",
            posted=(p.get("date") or "")[:10],
            salary=_usd_range(p.get("salary_min"), p.get("salary_max")),
            workplace="remote",
        )


def jobicy(company: str, queries: list[str], geo: str = "usa", **_) -> Iterable[Job]:
    jobs: dict[str, Job] = {}
    for query in queries:
        params = urllib.parse.urlencode({"count": 100, "tag": query, "geo": geo})
        for p in _request(f"https://jobicy.com/api/v2/remote-jobs?{params}").get("jobs") or []:
            usd = p.get("salaryCurrency") == "USD" and p.get("salaryPeriod") in ("yearly", "annual", None)
            jobs.setdefault(str(p["id"]), Job(
                key=f"jobicy:{p['id']}",
                company=html.unescape(p.get("companyName") or "").strip(),
                title=html.unescape(p.get("jobTitle") or "").strip(),
                location=f"Remote ({p.get('jobGeo') or 'Anywhere'})",
                url=p.get("url") or "",
                posted=(p.get("pubDate") or "")[:10],
                salary=_usd_range(p.get("salaryMin"), p.get("salaryMax")) if usd else "",
                workplace="remote",
            ))
    return list(jobs.values())


WWR_FEEDS = ["remote-jobs", "categories/remote-devops-sysadmin-jobs", "categories/remote-back-end-programming-jobs",
             "categories/remote-full-stack-programming-jobs"]


def weworkremotely(company: str, feeds: list[str] = WWR_FEEDS, **_) -> Iterable[Job]:
    jobs: dict[str, Job] = {}
    for feed in feeds:
        req = urllib.request.Request(f"https://weworkremotely.com/{feed}.rss", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            xml = resp.read().decode("utf-8", "replace")
        for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
            tag = lambda name: html.unescape((re.search(rf"<{name}>(.*?)</{name}>", item, re.S) or ["", ""])[1]).strip()
            employer, _, title = tag("title").partition(": ")
            try:
                posted = parsedate_to_datetime(tag("pubDate")).date().isoformat()
            except (TypeError, ValueError):
                posted = ""
            link = tag("link")
            jobs.setdefault(link, Job(
                key=f"weworkremotely:{link.rsplit('/', 1)[-1]}",
                company=employer.strip(),
                title=title.strip(),
                location=f"Remote ({tag('region') or 'Anywhere'})",
                url=link,
                posted=posted,
                workplace="remote",
            ))
    return list(jobs.values())


def workingnomads(company: str, **_) -> Iterable[Job]:
    for p in _request("https://www.workingnomads.com/api/exposed_jobs/"):
        yield Job(
            key=f"workingnomads:{p['url'].rstrip('/').rsplit('/', 1)[-1]}",
            company=(p.get("company_name") or "").strip(),
            title=(p.get("title") or "").strip(),
            location=f"Remote ({p.get('location') or 'Anywhere'})",
            url=p["url"],
            posted=(p.get("pub_date") or "")[:10],
            workplace="remote",
        )


_HN_ROLE = re.compile(
    r"engineer|developer|\bSRE\b|architect|scientist|administrator|\badmin\b|devops|programmer|\bML\b|researcher", re.I
)
_HN_WHERE = re.compile(r"remote|hybrid|on-?site|in[- ]office|\bnyc\b|\bsf\b|bay area", re.I)


def hackernews(company: str, **_) -> Iterable[Job]:
    """This month's "Ask HN: Who is hiring?" thread. Top-level comments start with a
    `Company | Role | Location | ...` line; one job per role listed there."""
    stories = _request("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=10")["hits"]
    story = next((s for s in stories if s.get("title", "").startswith("Ask HN: Who is hiring?")), None)
    if not story:
        return
    sid = story["objectID"]
    comments = _request(f"https://hn.algolia.com/api/v1/search?tags=comment,story_{sid}&hitsPerPage=1000")["hits"]
    for c in comments:
        if str(c.get("parent_id")) != sid or not c.get("comment_text"):
            continue
        first = re.sub(r"<[^>]+>", "", html.unescape(re.split(r"<p>", c["comment_text"])[0]))
        segments = [s.strip() for s in first.split("|") if s.strip()]
        if len(segments) < 2:
            continue
        employer = re.sub(r"\s*\(.*?\)\s*$", "", segments[0]).strip()
        roles = [s for s in segments[1:] if _HN_ROLE.search(s)]
        where = "; ".join(s for s in segments[1:] if s not in roles and (_HN_WHERE.search(s) or usgeo.is_us(s)))
        pay = find_pay_range(first)
        for i, role in enumerate(r.strip() for seg in roles[:1] for r in re.split(r"\s+[·•]\s+|;\s*", seg) if r.strip()):
            # "Platform Engineer (NYC, Hybrid)" carries its own location
            own = re.search(r"\(([^()]*)\)\s*$", role)
            location = own.group(1) if own and (_HN_WHERE.search(own.group(1)) or usgeo.is_us(own.group(1))) else where
            yield Job(
                key=f"hackernews:{c['objectID']}:{i}",
                company=employer,
                title=role,
                location=location,
                url=f"https://news.ycombinator.com/item?id={c['objectID']}",
                posted=(c.get("created_at") or "")[:10],
                salary=pay,
                workplace=workplace_from_text(location),
            )


FETCHERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "workable": workable,
    "gem": gem,
    "workday": workday,
    "amazon": amazon,
    "eightfold": eightfold,
    "himalayas": himalayas,
    "remotive": remotive,
    "yc": yc,
    "smartrecruiters": smartrecruiters,
    "rippling": rippling,
    "recruitee": recruitee,
    "breezy": breezy,
    "oracle": oracle,
    "remoteok": remoteok,
    "jobicy": jobicy,
    "weworkremotely": weworkremotely,
    "workingnomads": workingnomads,
    "hackernews": hackernews,
}
# Multi-employer boards; their copies of a directly tracked company's roles are dropped.
AGGREGATORS = {"himalayas", "remotive", "remoteok", "jobicy", "weworkremotely", "workingnomads", "hackernews"}
