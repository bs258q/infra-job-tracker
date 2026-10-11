"""Builds the JSON the web dashboard reads (web/public/data/<profile>/)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import ats
import usgeo

DATA_ROOT = Path(__file__).parent / "web" / "public" / "data"
HISTORY_DAYS = 180
REMOTE_REGION = "Remote (US)"
LEVELS = ["Principal+", "Staff", "Senior", "MTS", "Mid / Other"]
WORKPLACES = [("remote", "Remote"), ("hybrid", "Hybrid"), ("onsite", "On-site"), ("unknown", "Not stated")]


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
        return {
            "categories": [n for n, _ in self.categories] + [self.fallback],
            "regions": [n for n, _ in self.regions] + [REMOTE_REGION],
            "levels": LEVELS,
            "workplaces": [label for _, label in WORKPLACES],
        }


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
        groups.setdefault(_role_id(j.company, j.title), []).append(j)

    today = date.today()
    roles = []
    for rid, jobs in groups.items():
        first = jobs[0]
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

        roles.append(
            {
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
                "firstSeen": min(seen[j.key]["first_seen"] for j in jobs),
                "salary": salary_text,
                "salaryMin": lo,
                "salaryMax": hi,
                "source": first.key.split(":", 1)[0],
                "postings": len(jobs),
            }
        )
    roles.sort(key=lambda r: (r["firstSeen"], r["posted"] or ""), reverse=True)
    return roles


def write(
    profile_id: str,
    roles: list[dict],
    new_ids: set[str],
    errors: dict[str, str],
    company_count: int,
    facets: Facets,
) -> None:
    data_dir = DATA_ROOT / profile_id
    data_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {"generatedAt": now, "companiesTracked": company_count, "errors": errors, "facets": facets.order()}
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
