"""Daily job tracker. Each profiles/<id>.toml is a separate search (infra, salesforce, ...).

python tracker.py                         infra profile: fetch, diff against state/infra/seen.json,
                                          write dashboard data, email new roles
python tracker.py --profile salesforce    same for profiles/salesforce.toml
python tracker.py --dry-run               fetch and print matches; no state, file, or email changes
python tracker.py --only "OpenAI,NVIDIA" --dry-run
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import sys
import tomllib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import ats
import dashboard
import dedupe
import usgeo
from usgeo import is_remote_us

ROOT = Path(__file__).parent
PROFILES_DIR = ROOT / "profiles"
PRUNE_AFTER_DAYS = 45


def load_toml(name: str | Path) -> dict:
    with open(ROOT / name, "rb") as f:
        return tomllib.load(f)


def load_profile(profile_id: str) -> dict:
    path = PROFILES_DIR / f"{profile_id}.toml"
    if not path.exists():
        known = ", ".join(p.stem for p in sorted(PROFILES_DIR.glob("*.toml")))
        raise SystemExit(f"No profile {profile_id!r}; known profiles: {known}")
    return load_toml(path)


def load_companies(cfg: dict) -> list[dict]:
    prof = cfg.get("profile", {})
    skip = {s.lower() for s in prof.get("skip", [])}
    companies: dict[str, dict] = {}
    boards: set[tuple] = set()
    for pattern in prof.get("companies", ["companies/tech.toml"]):
        files = sorted(ROOT.glob(pattern)) if any(ch in pattern for ch in "*?[") else [ROOT / pattern]
        for file in files:
            for c in load_toml(file).get("company", []):
                # The same board listed in two files (or under two names) is fetched once.
                board = (c["ats"], (c.get("slug") or c.get("host") or c["name"]).lower(), c.get("site", ""))
                if c["name"].lower() in skip or c["name"].lower() in companies or board in boards:
                    continue
                companies[c["name"].lower()] = c
                boards.add(board)
    return list(companies.values())


def profile_index() -> list[dict]:
    out = []
    for path in sorted(PROFILES_DIR.glob("*.toml")):
        prof = load_toml(path).get("profile", {})
        out.append({"id": path.stem, "name": prof.get("name", path.stem), "description": prof.get("description", "")})
    return out


def any_re(patterns: list[str]) -> re.Pattern | None:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I) if patterns else None


def _segments(loc: str) -> list[str]:
    return [s for s in re.split(r"[;|]", loc) if s.strip()] or [loc]


class Filters:
    def __init__(self, cfg: dict):
        self.title_in = any_re(cfg["title"]["include"])
        self.title_req = any_re(cfg["title"].get("require", []))
        self.title_out = any_re(cfg["title"].get("exclude", []))
        loc = cfg["location"]
        self.mode = loc.get("mode", "list")
        self.loc_in = any_re(loc.get("include", []))
        self.remote_us = loc.get("remote_us", True)
        self.workplaces = set(loc.get("workplaces", []))

    def title_ok(self, title: str) -> bool:
        if self.title_out and self.title_out.search(title):
            return False
        if self.title_req and not self.title_req.search(title):
            return False
        return bool(self.title_in and self.title_in.search(title))

    def location_ok(self, loc: str) -> bool:
        segments = _segments(loc)
        if self.mode == "us":
            return any(usgeo.is_us(s) or is_remote_us(s) for s in segments)
        if self.loc_in and self.loc_in.search(loc):
            return True
        return self.remote_us and any(is_remote_us(s) for s in segments)

    def workplace_ok(self, workplace: str) -> bool:
        return not self.workplaces or (workplace or "unknown") in self.workplaces

    def __call__(self, job: ats.Job) -> bool:
        return self.title_ok(job.title) and self.location_ok(job.location) and self.workplace_ok(job.workplace)


def fetch_all(companies: list[dict], filters: Filters, default_queries: list[str]):
    def run(entry: dict):
        params = {k: v for k, v in entry.items() if k not in {"name", "ats"}}
        params.setdefault("queries", default_queries)
        try:
            jobs = list(ats.FETCHERS[entry["ats"]](
                entry["name"], title_ok=filters.title_ok, location_ok=filters.location_ok, **params
            ))
            for j in jobs:
                j.workplace = j.workplace or ats.workplace_from_text(j.location)
                j.employment = j.employment or ats.employment_from_text(j.title)
            return entry["name"], jobs, None
        except Exception as e:
            return entry["name"], [], f"{type(e).__name__}: {str(e)[:160]}"

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(run, companies))

    # A company's own board is the source of truth; remote-board copies of its roles are dropped.
    direct = {dedupe.company_key(c["name"]) for c in companies if c["ats"] not in ats.AGGREGATORS}
    matches: dict[str, ats.Job] = {}
    errors: dict[str, str] = {}
    for entry, (name, jobs, err) in zip(companies, results):
        if err:
            errors[name] = err
        kept = [j for j in jobs if filters(j)]
        note = ""
        if entry["ats"] in ats.AGGREGATORS:
            own = [j for j in kept if dedupe.company_key(j.company) in direct]
            kept = [j for j in kept if dedupe.company_key(j.company) not in direct]
            note = f"  ({len(own)} more already tracked directly)" if own else ""
        for j in kept:
            matches[j.key] = j
        print(f"  {name:<24} {len(jobs):>5} jobs  {len(kept):>4} match{note}" + (f"  ERROR {err}" if err else ""), file=sys.stderr)
    return matches, errors


def mark_seen(matches: dict[str, ats.Job], seen: dict[str, dict], now: str, today: str) -> set[str]:
    """Record postings and their roles in `seen`; return keys of postings whose role is new.

    A role is new only if neither it nor any of its postings was seen before, so a repost under a
    new posting ID (or the same opening on a second board) doesn't alert again.
    """
    role_of = {k: dedupe.role_key(j.company, j.title) for k, j in matches.items()}
    known = {rk for k, rk in role_of.items() if k in seen or f"role:{rk}" in seen}
    for k, rk in role_of.items():
        seen.setdefault(k, {"first_seen": now})["last_seen"] = today
        role = seen.setdefault(f"role:{rk}", {"first_seen": seen[k]["first_seen"]})
        role["first_seen"] = min(role["first_seen"], seen[k]["first_seen"])
        role["last_seen"] = today
    return {k for k, rk in role_of.items() if rk not in known}


def group_roles(jobs: list[ats.Job]) -> dict[str, list[list[ats.Job]]]:
    """company -> roles, each the postings of one opening (one per location, board, or repost)."""
    by_company: dict[str, dict[str, list[ats.Job]]] = defaultdict(dict)
    names: dict[str, str] = {}
    for j in jobs:
        ck = dedupe.company_key(j.company)
        names.setdefault(ck, j.company)
        by_company[ck].setdefault(dedupe.title_key(j.title), []).append(j)
    def newest(group: list[ats.Job]) -> str:
        return max((x.posted for x in group if x.posted[:1].isdigit()), default="")

    return {
        names[ck]: sorted(roles.values(), key=newest, reverse=True)
        for ck, roles in sorted(by_company.items(), key=lambda kv: names[kv[0]].lower())
    }


def _locations(group: list[ats.Job]) -> str:
    locs = list(dict.fromkeys(l.strip() for j in group for l in j.location.split(";") if l.strip()))
    return "; ".join(locs[:4]) + (f" (+{len(locs) - 4} more)" if len(locs) > 4 else "")


def render_html(new_jobs: list[ats.Job], errors: dict[str, str], first_run: bool, all_roles_url: str) -> str:
    grouped = group_roles(new_jobs)
    esc = html.escape
    parts = ["<div style='font-family:-apple-system,Segoe UI,sans-serif;font-size:14px;max-width:820px'>"]
    if first_run:
        # Gmail clips messages over ~100KB, so the first run sends counts and links to the dashboard instead.
        parts.append("<p><b>Tracker is live.</b> Open matching roles today — full list on the dashboard. Future emails list only new roles.</p><table>")
        for company, groups in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
            parts.append(f"<tr><td>{esc(company)}</td><td style='padding-left:12px;text-align:right'>{len(groups)}</td></tr>")
        parts.append("</table>")
        grouped = {}
    for company, groups in grouped.items():
        parts.append(f"<h3 style='margin:18px 0 6px'>{esc(company)} <span style='color:#888'>({len(groups)})</span></h3><ul style='margin:0;padding-left:18px'>")
        for g in groups:
            j = g[0]
            meta = " · ".join(x for x in (_locations(g), j.posted, j.salary) if x)
            parts.append(f"<li style='margin:3px 0'><a href='{esc(j.url)}'>{esc(j.title)}</a> <span style='color:#666'>— {esc(meta)}</span></li>")
        parts.append("</ul>")
    if all_roles_url:
        parts.append(f"<p style='margin-top:20px'><a href='{esc(all_roles_url)}'>All open matching roles</a></p>")
    if errors:
        parts.append("<p style='color:#a00;margin-top:20px'><b>Fetch errors</b> (fix the entry in companies/*.toml):<br>")
        parts.append("<br>".join(f"{esc(c)}: {esc(e)}" for c, e in sorted(errors.items())) + "</p>")
    parts.append("</div>")
    return "\n".join(parts)


def send_email(subject: str, body_html: str) -> None:
    user = (os.environ.get("SMTP_USER") or "").strip()
    # Google shows app passwords as "abcd efgh ijkl mnop"; pasted copies often keep the spaces.
    password = re.sub(r"\s+", "", os.environ.get("SMTP_PASSWORD") or "")
    if not (user and password):
        print("SMTP_USER / SMTP_PASSWORD not set; skipping email", file=sys.stderr)
        return
    to = [a.strip() for a in (os.environ.get("EMAIL_TO") or user).split(",") if a.strip()]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, ", ".join(to)
    msg.set_content("HTML email — open in a client that renders HTML.")
    msg.add_alternative(body_html, subtype="html")
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    local, _, domain = user.partition("@")
    print(f"SMTP login as {local[:3]}***@{domain} (password length {len(password)})", file=sys.stderr)

    errors = []
    for port in (465, 587):
        try:
            if port == 465:
                s = smtplib.SMTP_SSL(host, port, timeout=60)
            else:
                s = smtplib.SMTP(host, port, timeout=60)
                s.starttls()
            with s:
                s.login(user, password)
                s.send_message(msg)
            print(f"emailed {', '.join(to)} via port {port}", file=sys.stderr)
            return
        except smtplib.SMTPAuthenticationError as e:
            raise SystemExit(
                f"Gmail rejected the login ({e.smtp_code}): use a 16-character app password from "
                "https://myaccount.google.com/apppasswords, not your normal password."
            ) from e
        except (smtplib.SMTPException, OSError) as e:
            errors.append(f"port {port}: {type(e).__name__}: {e}")
    raise SystemExit("Email failed. " + " | ".join(errors))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="infra", help="profiles/<name>.toml (default: infra)")
    ap.add_argument("--dry-run", action="store_true", help="print matches only")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--only", help="comma-separated company names")
    ap.add_argument("--test-email", action="store_true", help="send a one-line test email and exit")
    args = ap.parse_args()

    if args.test_email:
        send_email("infra-job-tracker test", "<p>Email from infra-job-tracker works.</p>")
        return

    cfg = load_profile(args.profile)
    profile_name = cfg.get("profile", {}).get("name", args.profile)
    companies = load_companies(cfg)
    if args.only:
        wanted = {n.strip().lower() for n in args.only.split(",")}
        companies = [c for c in companies if c["name"].lower() in wanted]

    filters = Filters(cfg)
    print(f"[{args.profile}] fetching {len(companies)} sources", file=sys.stderr)
    matches, errors = fetch_all(companies, filters, cfg["search"]["queries"])

    if args.dry_run:
        for company, groups in group_roles(list(matches.values())).items():
            for g in groups:
                print(f"{company:<20} | {g[0].title[:70]:<70} | {g[0].workplace or '-':<7} | {_locations(g)[:60]}")
        print(f"\n{sum(len(g) for g in group_roles(list(matches.values())).values())} roles, {len(errors)} errors", file=sys.stderr)
        return

    today = date.today().isoformat()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state_file = ROOT / "state" / args.profile / "seen.json"
    first_run = not state_file.exists()
    seen: dict[str, dict] = {} if first_run else json.loads(state_file.read_text())

    new_keys = mark_seen(matches, seen, now, today)
    cutoff = (date.today() - timedelta(days=PRUNE_AFTER_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v.get("last_seen", today) >= cutoff}

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(seen, indent=0, sort_keys=True))
    facets = dashboard.Facets(cfg.get("dashboard", {}))
    roles = dashboard.build_roles(list(matches.values()), seen, is_remote_us, facets)
    # The first run's "new" count is the whole backlog, which would swamp the trends chart.
    new_role_ids = set() if first_run else {r["id"] for r in roles if r["firstSeen"] == now}
    dashboard.write(args.profile, roles, new_role_ids, errors, len(companies), facets, dashboard.elsewhere(cfg))
    dashboard.write_profiles(profile_index())

    new_jobs = [matches[k] for k in new_keys]
    new_roles = sum(len(g) for g in group_roles(new_jobs).values())
    print(f"{len(matches)} matching postings, {new_roles} new roles, {len(errors)} errors", file=sys.stderr)

    if args.no_email or (not new_jobs and not cfg.get("email", {}).get("send_when_empty", False)):
        return
    label = "open" if first_run else "new"
    subject = f"{new_roles} {label} {profile_name} roles · {today}" + (f" · {len(errors)} errors" if errors else "")
    base_url = os.environ.get("DASHBOARD_URL", "").rstrip("/")
    roles_url = f"{base_url}/?p={args.profile}" if base_url else ""
    send_email(subject, render_html(new_jobs, errors, first_run, roles_url))


if __name__ == "__main__":
    main()
