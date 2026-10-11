"""Daily tracker for platform / SRE / AI-infra / ML training & inference roles.

python tracker.py              fetch, diff against state/seen.json, write latest.md, email new roles
python tracker.py --dry-run    fetch and print matches; no state, file, or email changes
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
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path

import ats

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state" / "seen.json"
LATEST_FILE = ROOT / "latest.md"
PRUNE_AFTER_DAYS = 45

US_HINT = re.compile(r"\b(US|USA|U\.S\.A?\.?|United States|North America|Americas|Anywhere)\b", re.I)
REMOTE = re.compile(r"remote", re.I)
US_ONLY = re.compile(r"^\s*(US|USA|United States( of America)?)\s*$", re.I)


def load_toml(name: str) -> dict:
    with open(ROOT / name, "rb") as f:
        return tomllib.load(f)


def any_re(patterns: list[str]) -> re.Pattern | None:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I) if patterns else None


class Filters:
    def __init__(self, cfg: dict):
        self.title_in = any_re(cfg["title"]["include"])
        self.title_out = any_re(cfg["title"].get("exclude", []))
        self.loc_in = any_re(cfg["location"]["include"])
        self.remote_us = cfg["location"].get("remote_us", True)

    def title_ok(self, title: str) -> bool:
        if self.title_out and self.title_out.search(title):
            return False
        return bool(self.title_in and self.title_in.search(title))

    def location_ok(self, loc: str) -> bool:
        if self.loc_in and self.loc_in.search(loc):
            return True
        if self.remote_us:
            if REMOTE.search(loc) and (US_HINT.search(loc) or not re.sub(r"[\W_]|remote", "", loc, flags=re.I)):
                return True
            if US_ONLY.match(loc):
                return True
        return False

    def __call__(self, job: ats.Job) -> bool:
        return self.title_ok(job.title) and self.location_ok(job.location)


def fetch_all(companies: list[dict], filters: Filters, default_queries: list[str]):
    def run(entry: dict):
        params = {k: v for k, v in entry.items() if k not in {"name", "ats"}}
        params.setdefault("queries", default_queries)
        try:
            jobs = list(ats.FETCHERS[entry["ats"]](entry["name"], title_ok=filters.title_ok, **params))
            return entry["name"], jobs, None
        except Exception as e:
            return entry["name"], [], f"{type(e).__name__}: {str(e)[:160]}"

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(run, companies))

    matches: dict[str, ats.Job] = {}
    errors: dict[str, str] = {}
    for name, jobs, err in results:
        if err:
            errors[name] = err
        kept = [j for j in jobs if filters(j)]
        for j in kept:
            matches[j.key] = j
        print(f"  {name:<24} {len(jobs):>5} jobs  {len(kept):>4} match" + (f"  ERROR {err}" if err else ""), file=sys.stderr)
    return matches, errors


def group_roles(jobs: list[ats.Job]) -> dict[str, list[list[ats.Job]]]:
    """company -> list of postings sharing a title (multi-location reqs are often separate postings)."""
    by_company: dict[str, dict[str, list[ats.Job]]] = defaultdict(dict)
    for j in jobs:
        by_company[j.company].setdefault(j.title.lower(), []).append(j)
    def newest(group: list[ats.Job]) -> str:
        return max((x.posted for x in group if x.posted[:1].isdigit()), default="")

    return {
        c: sorted(roles.values(), key=newest, reverse=True)
        for c, roles in sorted(by_company.items(), key=lambda kv: kv[0].lower())
    }


def _locations(group: list[ats.Job]) -> str:
    locs = list(dict.fromkeys(l.strip() for j in group for l in j.location.split(";") if l.strip()))
    return "; ".join(locs[:4]) + (f" (+{len(locs) - 4} more)" if len(locs) > 4 else "")


def render_markdown(matches: list[ats.Job], new_keys: set[str], errors: dict[str, str], today: str) -> str:
    grouped = group_roles(matches)
    roles = sum(len(g) for g in grouped.values())
    lines = [
        f"# Open roles — {today}",
        "",
        f"{roles} matching roles across {len(grouped)} companies. **NEW** = first seen today.",
        "",
    ]
    for company, groups in grouped.items():
        lines += [f"## {company} ({len(groups)})", "", "| Role | Location | Posted | Pay |", "|---|---|---|---|"]
        for g in groups:
            j = g[0]
            tag = "**NEW** " if any(x.key in new_keys for x in g) else ""
            title = j.title.replace("|", "/")
            lines.append(f"| {tag}[{title}]({j.url}) | {_locations(g).replace('|', '/')} | {j.posted} | {j.salary.replace('|', '/')} |")
        lines.append("")
    if errors:
        lines += ["## Fetch errors", ""] + [f"- {c}: `{e}`" for c, e in sorted(errors.items())] + [""]
    return "\n".join(lines)


def render_html(new_jobs: list[ats.Job], errors: dict[str, str], first_run: bool, repo_url: str) -> str:
    grouped = group_roles(new_jobs)
    esc = html.escape
    parts = ["<div style='font-family:-apple-system,Segoe UI,sans-serif;font-size:14px;max-width:820px'>"]
    if first_run:
        # Gmail clips messages over ~100KB, so the first run sends counts and links to latest.md instead.
        parts.append("<p><b>Tracker is live.</b> Open matching roles today — full list in latest.md. Future emails list only new roles.</p><table>")
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
    if repo_url:
        parts.append(f"<p style='margin-top:20px'><a href='{esc(repo_url)}/blob/main/latest.md'>All open matching roles</a></p>")
    if errors:
        parts.append("<p style='color:#a00;margin-top:20px'><b>Fetch errors</b> (fix slug in companies.toml):<br>")
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
    ap.add_argument("--dry-run", action="store_true", help="print matches only")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--only", help="comma-separated company names")
    ap.add_argument("--test-email", action="store_true", help="send a one-line test email and exit")
    args = ap.parse_args()

    if args.test_email:
        send_email("infra-job-tracker test", "<p>Email from infra-job-tracker works.</p>")
        return

    cfg = load_toml("config.toml")
    companies = load_toml("companies.toml")["company"]
    if args.only:
        wanted = {n.strip().lower() for n in args.only.split(",")}
        companies = [c for c in companies if c["name"].lower() in wanted]

    filters = Filters(cfg)
    print(f"fetching {len(companies)} companies", file=sys.stderr)
    matches, errors = fetch_all(companies, filters, cfg["search"]["queries"])

    if args.dry_run:
        for company, groups in group_roles(list(matches.values())).items():
            for g in groups:
                print(f"{company:<20} | {g[0].title[:70]:<70} | {_locations(g)[:60]}")
        print(f"\n{sum(len(g) for g in group_roles(list(matches.values())).values())} roles, {len(errors)} errors", file=sys.stderr)
        return

    today = date.today().isoformat()
    first_run = not STATE_FILE.exists()
    seen: dict[str, dict] = {} if first_run else json.loads(STATE_FILE.read_text())

    new_keys = {k for k in matches if k not in seen}
    for k in matches:
        seen.setdefault(k, {"first_seen": today})["last_seen"] = today
    cutoff = (date.today() - timedelta(days=PRUNE_AFTER_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v.get("last_seen", today) >= cutoff}

    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(seen, indent=0, sort_keys=True))
    LATEST_FILE.write_text(render_markdown(list(matches.values()), new_keys, errors, today))

    new_jobs = [matches[k] for k in new_keys]
    new_roles = sum(len(g) for g in group_roles(new_jobs).values())
    print(f"{len(matches)} matching postings, {new_roles} new roles, {len(errors)} errors", file=sys.stderr)

    if args.no_email or (not new_jobs and not cfg.get("email", {}).get("send_when_empty", False)):
        return
    repo = os.environ.get("GITHUB_REPOSITORY")
    repo_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}" if repo else ""
    label = "open" if first_run else "new"
    subject = f"{new_roles} {label} infra/ML roles · {today}" + (f" · {len(errors)} errors" if errors else "")
    send_email(subject, render_html(new_jobs, errors, first_run, repo_url))


if __name__ == "__main__":
    main()
