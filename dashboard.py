"""Builds the JSON the web dashboard reads (web/public/data/<profile>/)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

import ats
import dedupe
import usgeo

DATA_ROOT = Path(__file__).parent / "web" / "public" / "data"
HISTORY_DAYS = 180
REMOTE_REGION = "Remote (US)"
LEVELS = ["Principal+", "Staff", "Senior", "MTS", "Mid / Other"]
WORKPLACES = [("remote", "Remote"), ("hybrid", "Hybrid"), ("onsite", "On-site"), ("unknown", "Not stated")]
EMPLOYMENTS = [
    ("full-time", "Full-time"), ("contract-w2", "Contract (W2)"), ("contract-c2c", "Contract (C2C)"),
    ("contract-to-hire", "Contract-to-hire"), ("1099", "1099"), ("contract", "Contract (unspecified)"),
    ("", "Not stated"),
]
# A role posted several times takes its most specific stated type.
_EMPLOYMENT_PRECEDENCE = ["contract-c2c", "contract-w2", "contract-to-hire", "1099", "full-time", "contract", ""]


def _level(title: str, architect_is_level: bool = True) -> str:
    t = re.sub(r"member of (the )?technical staff", "", title, flags=re.I)
    principal = r"principal|distinguished|fellow" + (r"|\barchitect\b" if architect_is_level else "")
    if re.search(principal, t, re.I):
        return "Principal+"
    if re.search(r"\bstaff\b", t, re.I):
        return "Staff"
    if re.search(r"\bsenior\b|\bsr\.?\b|\blead\b|\bIII\b", t, re.I):
        return "Senior"
    if re.search(r"member of (the )?technical staff|\bMTS\b", title, re.I):
        return "MTS"
    return "Mid / Other"


def parse_salary(text: str) -> tuple[int | None, int | None]:
    """Annual USD (min, max) from free-form pay text; None for hourly or non-USD ranges."""
    if not text or re.search(r"hour|/\s*hr\b", text, re.I):
        return None, None
    usd = re.search(r"(?<![A-Z])\$|USD", text.replace("CA$", "").replace("A$", ""))
    if not usd and re.search(r"€|£|¥|₹|\b(EUR|GBP|CAD|INR|JPY)\b|CA\$", text):
        return None, None
    values = []
    for num, unit in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s*([kKmM])?(?![\d,])", text):
        v = float(num.replace(",", ""))
        if unit in ("k", "K"):
            v *= 1_000
        elif unit in ("m", "M"):
            v *= 1_000_000
        if 30_000 <= v <= 3_000_000:
            values.append(int(v))
    if not values:
        return None, None
    return min(values[:2]), max(values[:2])


def _role_id(company: str, title: str) -> str:
    return hashlib.sha1(f"{company}|{title}".lower().encode()).hexdigest()[:12]


class Facets:
    """Category / region rules from a profile's [dashboard] section."""

    def __init__(self, cfg: dict):
        self.fallback = cfg.get("fallback", "Other")
        self.categories = [(c["name"], re.compile(c["pattern"], re.I)) for c in cfg.get("categories", [])]
        self.regions = [(r["name"], re.compile(r["pattern"], re.I) if "pattern" in r else set(r["states"])) for r in cfg.get("regions", [])]
        self.architect_is_level = cfg.get("architect_is_level", True)
        self.employment = bool(cfg.get("employment", False))

    def categories_for(self, title: str) -> list[str]:
        return [name for name, pat in self.categories if pat.search(title)] or [self.fallback]

    def regions_for(self, text: str) -> list[str]:
        found_states = None
        out = []
        for name, rule in self.regions:
            if isinstance(rule, set):
                if found_states is None:
                    found_states = usgeo.states(text)
                if rule & found_states:
                    out.append(name)
            elif rule.search(text):
                out.append(name)
        return out

    def order(self) -> dict[str, list[str]]:
        out = {
            "categories": [n for n, _ in self.categories] + [self.fallback],
            "regions": [n for n, _ in self.regions] + [REMOTE_REGION],
            "levels": LEVELS,
            "workplaces": [label for _, label in WORKPLACES],
        }
        if self.employment:
            out["employments"] = [label for _, label in EMPLOYMENTS]
        return out


def _employment(jobs: list[ats.Job]) -> str:
    kinds = {j.employment for j in jobs}
    kind = next(k for k in _EMPLOYMENT_PRECEDENCE if k in kinds or k == "")
    return dict(EMPLOYMENTS)[kind]


def _workplace(jobs: list[ats.Job], remote: bool) -> str:
    kinds = {j.workplace for j in jobs}
    for kind, label in WORKPLACES:
        if kind in kinds or (kind == "remote" and remote):
            return label
    return "Not stated"


def build_roles(
    matches: list[ats.Job],
    seen: dict[str, dict],
    is_remote_us: Callable[[str], bool],
    facets: Facets,
) -> list[dict]:
    groups: dict[str, list[ats.Job]] = {}
    for j in matches:
        groups.setdefault(dedupe.role_key(j.company, j.title), []).append(j)

    today = date.today()
    roles = []
    for key, jobs in groups.items():
        # Ids stay a hash of one raw company/title so pipeline entries saved in browsers keep matching.
        first = min(jobs, key=lambda j: (j.company.lower(), j.title.lower(), j.key))
        rid = _role_id(first.company, first.title)
        first_seen = seen.get(f"role:{key}", {}).get("first_seen") or min(seen[j.key]["first_seen"] for j in jobs)
        locs = list(dict.fromkeys(l.strip() for j in jobs for l in re.split(r"[;|]", j.location) if l.strip()))
        locs.sort(key=lambda l: not facets.regions_for(l))
        loc_text = "; ".join(locs)
        regions = facets.regions_for(loc_text)
        remote = any(j.workplace == "remote" for j in jobs) or any(is_remote_us(l) for l in locs)
        if remote:
            regions.append(REMOTE_REGION)

        posted_iso = [j.posted for j in jobs if re.fullmatch(r"\d{4}-\d{2}-\d{2}", j.posted)]
        posted_approx = False
        if posted_iso:
            posted = max(posted_iso)
        elif any("30+" in j.posted for j in jobs):
            posted, posted_approx = (today - timedelta(days=30)).isoformat(), True
        else:
            posted = None

        salary_text = next((j.salary for j in jobs if j.salary), "")
        lo, hi = parse_salary(salary_text)

        # Prefer the link of a posting in a listed region when one title is posted per location.
        preferred = next((j for j in jobs if facets.regions_for(j.location)), first)

        role = {
            "id": rid,
            "company": first.company,
            "title": first.title,
            "url": preferred.url,
            "locations": locs,
            "regions": regions,
            "remote": remote,
            "workplace": _workplace(jobs, remote),
            "categories": facets.categories_for(first.title),
            "level": _level(first.title, facets.architect_is_level),
            "posted": posted,
            "postedApprox": posted_approx,
            "firstSeen": first_seen,
            "salary": salary_text,
            "salaryMin": lo,
            "salaryMax": hi,
            "source": first.key.split(":", 1)[0],
            "postings": len(jobs),
        }
        if facets.employment:
            role["employment"] = _employment(jobs)
        roles.append(role)
    roles.sort(key=lambda r: (r["firstSeen"], r["posted"] or ""), reverse=True)
    return roles


# Sites with no public jobs feed (their terms forbid scraping): the dashboard links to saved searches instead.
# Each takes (query, location, remote) and lists the past week, newest first, where the site supports it.
_ELSEWHERE: list[tuple[str, Callable[[str, str, bool], str]]] = [
    ("LinkedIn", lambda q, l, r: "https://www.linkedin.com/jobs/search/?" + urlencode(
        {"keywords": q, "location": l, "f_TPR": "r604800", "sortBy": "DD", **({"f_WT": "2"} if r else {})})),
    ("Indeed", lambda q, l, r: "https://www.indeed.com/jobs?" + urlencode({"q": q, "l": "Remote" if r else l, "fromage": 7, "sort": "date"})),
    ("Glassdoor", lambda q, l, r: "https://www.glassdoor.com/Job/jobs.htm?" + urlencode({"sc.keyword": q, "locKeyword": "Remote" if r else l, "fromAge": 7})),
    ("Dice", lambda q, l, r: "https://www.dice.com/jobs?" + urlencode(
        {"q": q, "filters.postedDate": "SEVEN", **({"filters.workplaceTypes": "Remote"} if r else {"location": l})})),
    ("Wellfound", lambda q, l, r: f"https://wellfound.com/role/{'r' if r else 'l'}/{slugify(q)}" + ("" if r else f"/{slugify(l)}")),
    ("Built In", lambda q, l, r: f"https://builtin.com/jobs{'/remote' if r else ''}?" + urlencode({"search": q})),
    ("Google Jobs", lambda q, l, r: "https://www.google.com/search?" + urlencode({"q": f"{q} jobs {'remote' if r else l}", "ibp": "htl;jobs"})),
]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def elsewhere(cfg: dict) -> list[dict]:
    """Saved searches on sites that aren't ingested, from the profile's [elsewhere] section."""
    sec = cfg.get("elsewhere", {})
    out = []
    for s in sec.get("searches", []):
        remote = bool(s.get("remote"))
        label = f"{s['query']} · {'Remote (US)' if remote else s.get('location', '')}"
        out.append({"label": label, "links": [{"name": n, "url": f(s["query"], s.get("location", ""), remote)} for n, f in _ELSEWHERE]})
    if extra := sec.get("extra"):
        out.append({"label": "More job sites", "links": [{"name": e["name"], "url": e["url"]} for e in extra]})
    return out


def write(
    profile_id: str,
    roles: list[dict],
    new_ids: set[str],
    errors: dict[str, str],
    company_count: int,
    facets: Facets,
    links: list[dict] | None = None,
) -> None:
    data_dir = DATA_ROOT / profile_id
    data_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {"generatedAt": now, "companiesTracked": company_count, "errors": errors, "facets": facets.order(),
            "elsewhere": links or []}
    (data_dir / "jobs.json").write_text(json.dumps({**meta, "roles": roles}, separators=(",", ":")))

    hist_file = data_dir / "history.json"
    history = json.loads(hist_file.read_text()) if hist_file.exists() else []
    today = date.today().isoformat()
    by_company: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for r in roles:
        by_company[r["company"]] = by_company.get(r["company"], 0) + 1
        for c in r["categories"]:
            by_category[c] = by_category.get(c, 0) + 1
    prev_new = next((h["new"] for h in history if h["date"] == today), 0)
    history = [h for h in history if h["date"] != today]
    history.append(
        {
            "date": today,
            "total": len(roles),
            "new": prev_new + len(new_ids),
            "byCompany": by_company,
            "byCategory": by_category,
        }
    )
    cutoff = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat()
    history = sorted((h for h in history if h["date"] >= cutoff), key=lambda h: h["date"])
    hist_file.write_text(json.dumps(history, separators=(",", ":")))


def write_profiles(profiles: list[dict]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    (DATA_ROOT / "profiles.json").write_text(json.dumps(profiles, indent=1))
