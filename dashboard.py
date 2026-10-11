"""Builds the JSON the web dashboard reads (web/public/data)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import ats

DATA_DIR = Path(__file__).parent / "web" / "public" / "data"
HISTORY_DAYS = 180

CATEGORIES = [
    ("Inference & Serving", r"inference|serving|model deployment"),
    ("Training", r"training|pre-?train|post-?train|\bRL\b|reinforcement"),
    ("GPU & Compute", r"\bGPU|compute|\bHPC\b|supercomput|cluster|accelerat|kernel|CUDA|compiler|\bfleet\b"),
    ("SRE & Reliability", r"\bSRE\b|reliability|production engineer|observability"),
    ("Platform & DevOps", r"platform|devops|kubernetes|container|orchestration|scheduler|\bruntime\b"),
    ("ML Systems", r"\b(ML|AI|machine learning|LLM) ?(infra|systems|ops|platform)|\bMLOps\b"),
    ("Distributed Systems", r"distributed systems|\bscaling\b|storage"),
]
FALLBACK_CATEGORY = "Infrastructure"

REGIONS = [
    ("San Francisco", r"san francisco|\bSF\b"),
    ("Peninsula", r"palo alto|menlo park|redwood (city|shores)|san mateo|foster city|burlingame|san carlos|san bruno|millbrae|belmont|mountain view|los altos"),
    ("South Bay", r"sunnyvale|san jose|santa clara|cupertino|milpitas|campbell|los gatos"),
    ("East Bay", r"oakland|berkeley|emeryville|alameda|fremont|pleasanton|livermore|walnut creek|san ramon|hayward|newark, ca"),
    ("Bay Area", r"bay area"),
]


def _level(title: str) -> str:
    t = re.sub(r"member of (the )?technical staff", "", title, flags=re.I)
    if re.search(r"principal|distinguished|fellow|\barchitect\b", t, re.I):
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


def build_roles(
    matches: list[ats.Job],
    seen: dict[str, dict],
    is_remote_us: Callable[[str], bool],
) -> list[dict]:
    groups: dict[str, list[ats.Job]] = {}
    for j in matches:
        groups.setdefault(_role_id(j.company, j.title), []).append(j)

    today = date.today()
    roles = []
    for rid, jobs in groups.items():
        first = jobs[0]
        locs = list(dict.fromkeys(l.strip() for j in jobs for l in re.split(r"[;|]", j.location) if l.strip()))
        locs.sort(key=lambda l: not any(re.search(p, l, re.I) for _, p in REGIONS))
        loc_text = "; ".join(locs)
        regions = [name for name, pat in REGIONS if re.search(pat, loc_text, re.I)]
        remote = any(is_remote_us(l) for l in locs) or is_remote_us(loc_text)
        if remote:
            regions.append("Remote (US)")

        cats = [name for name, pat in CATEGORIES if re.search(pat, first.title, re.I)] or [FALLBACK_CATEGORY]

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

        # Prefer a Bay Area posting's link when one title is posted per location.
        bay = next((j for j in jobs if any(re.search(p, j.location, re.I) for _, p in REGIONS)), first)

        roles.append(
            {
                "id": rid,
                "company": first.company,
                "title": first.title,
                "url": bay.url,
                "locations": locs,
                "regions": regions,
                "remote": remote,
                "categories": cats,
                "level": _level(first.title),
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


def write(roles: list[dict], new_ids: set[str], errors: dict[str, str], company_count: int) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {"generatedAt": now, "companiesTracked": company_count, "errors": errors}
    (DATA_DIR / "jobs.json").write_text(json.dumps({**meta, "roles": roles}, separators=(",", ":")))

    hist_file = DATA_DIR / "history.json"
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
