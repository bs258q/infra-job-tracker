"""Find which public job board a company uses (see BOARDS, plus Workday and Oracle Recruiting Cloud).

Usage: python discover.py "Together AI" anthropic "Thinking Machines"
       python discover.py https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
Prints companies.toml entries for every board that returns open jobs. Names are matched against
guessed slugs on every board in BOARDS; URLs (an ATS board, or a careers page linking to one) are
read directly, which is the only way to find a Workday or Oracle board.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import ats

BOARDS = ("greenhouse", "lever", "ashby", "workable", "gem", "rippling", "smartrecruiters", "recruitee", "breezy")

_BOARD_URLS = [
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board(?:/js)?\?for=([\w-]+)", re.I)),
    ("greenhouse", re.compile(r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io/(?!embed\b)([\w-]+)", re.I)),
    ("lever", re.compile(r"jobs(?:\.eu)?\.lever\.co/([\w.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?!j/|api/)([\w-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/api/v\d/(?:widget/)?accounts/([\w-]+)", re.I)),
    ("gem", re.compile(r"(?:jobs\.gem\.com|api\.gem\.com/job_board/v0)/([\w-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/(?!sr-jobs\b)([\w-]+)", re.I)),
    ("smartrecruiters", re.compile(r"api\.smartrecruiters\.com/v1/companies/([\w-]+)", re.I)),
    ("rippling", re.compile(r"ats\.rippling\.com/(?:api/v\d/board/)?(?!api\b)([\w-]+)", re.I)),
    ("recruitee", re.compile(r"\b(?!www\.|app\.|api\.|blog\.|support\.)([\w-]+)\.recruitee\.com", re.I)),
    ("breezy", re.compile(r"\b(?!www\.|app\.|api\.|marketing\.|help\.)([\w-]+)\.breezy\.hr", re.I)),
]
_WORKDAY_URL = re.compile(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?(?!wday/)([\w-]+)")
_ORACLE_URL = re.compile(r"([\w-]+(?:\.[\w-]+)*\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z]{2}(?:-[A-Z]{2})?/sites/([\w-]+)")


def slug_candidates(name: str) -> list[str]:
    base = name.lower().strip()
    words = re.findall(r"[a-z0-9]+", base)
    joined, hyphen = "".join(words), "-".join(words)
    out = [joined, hyphen]
    for suffix in ("ai", "hq", "inc", "labs", "-ai"):
        out.append(joined + suffix)
    if words and words[-1] in {"ai", "labs", "inc", "systems", "hq"}:
        out.append("".join(words[:-1]))
    return list(dict.fromkeys(s for s in out if s))


def boards_in_text(text: str) -> list[dict]:
    """Board entries (without `name`) for every ATS board URL in `text`, in order of appearance."""
    found: list[tuple[int, dict]] = []
    for board, pattern in _BOARD_URLS:
        for m in pattern.finditer(text):
            found.append((m.start(), {"ats": board, "slug": m.group(1).rstrip(".")}))
    for m in _WORKDAY_URL.finditer(text):
        tenant, wd, site = m.groups()
        found.append((m.start(), {"ats": "workday", "host": f"{tenant}.{wd}.myworkdayjobs.com", "tenant": tenant, "site": site}))
    for m in _ORACLE_URL.finditer(text):
        found.append((m.start(), {"ats": "oracle", "host": m.group(1), "site": m.group(2)}))
    unique = {tuple(sorted(e.items())): e for _, e in sorted(found, key=lambda f: f[0])}
    return list(unique.values())


def boards_at_url(url: str) -> list[dict]:
    """Boards named by the URL itself, else boards linked from the page it serves."""
    if direct := boards_in_text(url):
        return direct
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ats.USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            page = resp.read(2_000_000).decode("utf-8", "replace")
    except Exception:
        return []
    return boards_in_text(page)


def count_jobs(name: str, entry: dict) -> int:
    """Open postings on a board (0 if it doesn't exist); Workday only reports a total."""
    try:
        if entry["ats"] == "workday":
            base = f"https://{entry['host']}/wday/cxs/{entry['tenant']}/{entry['site']}/jobs"
            return ats._request(base, {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}).get("total") or 0
        if entry["ats"] == "oracle":
            finder = f"findReqs;siteNumber={entry['site']},limit=1,offset=0"
            data = ats._request(f"https://{entry['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&finder={finder}")
            return (data.get("items") or [{}])[0].get("TotalJobsCount") or 0
        return sum(1 for _ in ats.FETCHERS[entry["ats"]](name, slug=entry["slug"]))
    except Exception:
        return 0


def probe(name: str, board: str, slug: str):
    n = count_jobs(name, {"ats": board, "slug": slug})
    return (name, {"ats": board, "slug": slug}, n) if n else None


def toml_entry(name: str, entry: dict) -> str:
    fields = {"name": name, **entry}
    return "[[company]]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in fields.items())


def main(args: list[str]) -> None:
    urls = [a for a in args if re.match(r"https?://", a)]
    names = [a for a in args if a not in urls]
    tasks = [(n, b, s) for n in names for s in slug_candidates(n) for b in BOARDS]
    with ThreadPoolExecutor(max_workers=24) as pool:
        hits = [h for h in pool.map(lambda t: probe(*t), tasks) if h]
        for url in urls:
            entries = boards_at_url(url)
            label = lambda e: e.get("tenant") or e.get("slug") or e["host"].split(".")[0]
            counts = list(pool.map(lambda e: count_jobs(label(e), e), entries))
            hits += [(label(e), e, n) for e, n in zip(entries, counts) if n]
            if not any(counts):
                print(f"# no open jobs on a supported board at: {url}", file=sys.stderr)
    found = {h[0] for h in hits}
    for name, entry, n in sorted(hits, key=lambda h: (h[0].lower(), -h[2])):
        print(f"# {n} open jobs\n{toml_entry(name, entry)}")
    for name in names:
        if name not in found:
            print(f"# not found on {'/'.join(BOARDS)}: {name}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
