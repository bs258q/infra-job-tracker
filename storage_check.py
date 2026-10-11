"""Warn by email before the JSON-in-git storage outgrows itself.

python storage_check.py              print sizes; email once if a threshold is crossed (deduped)
python storage_check.py --no-email   print sizes only; no email, no alert-state change
python storage_check.py --test       send a [TEST] email with the current sizes, crossed or not

Thresholds are warn levels set well below the point where things actually hurt, so the email
arrives while there's still time to clean up or move to a database. Always exits 0.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
MB = 1024 * 1024

STATE_FILE_WARN = 5 * MB  # one state/<profile>/*.json; rewritten and committed every run
DATA_FILE_WARN = 3 * MB  # jobs.json / history.json; the browser downloads and parses it on load
STATE_TOTAL_WARN = 25 * MB  # all of state/
GITHUB_FILE_WARN = 50 * MB  # GitHub rejects pushes with a file over 100 MB
REPO_WARN = 500 * MB  # GitHub recommends repositories stay under 1 GB
REALERT_DAYS = 7

ALERT_FILE = ROOT / "state" / "storage-alert.json"

ADVICE = {
    "seen.json": "Shorten PRUNE_AFTER_DAYS in tracker.py, or move seen-job state to SQLite/Supabase.",
    "discovery.json": "Drop old discovery entries, or move the discovery log to SQLite/Supabase.",
    "jobs.json": "Paginate / split jobs.json, or serve postings from Supabase instead of a static file.",
    "history.json": "Shorten HISTORY_DAYS in dashboard.py, or move history to Supabase.",
}
STATE_ADVICE = "Move state to SQLite/Supabase, or prune it more aggressively."
REPO_ADVICE = "Squash the history of the bot 'Job snapshot' commits, or move state out of git."
GITHUB_FILE_ADVICE = "Urgent: GitHub rejects files over 100 MB. Move this file out of git now."


@dataclass
class Check:
    key: str
    label: str
    size: int
    limit: int
    advice: str

    @property
    def crossed(self) -> bool:
        return self.size >= self.limit


def measure(root: Path = ROOT) -> list[Check]:
    checks: list[Check] = []
    state = root / "state"
    for f in sorted(state.glob("*/*.json")):
        rel = f.relative_to(root).as_posix()
        advice = ADVICE.get(f.name, STATE_ADVICE)
        checks.append(Check(f"state-file:{rel}", rel, f.stat().st_size, STATE_FILE_WARN, advice))
        checks.append(Check(f"github-file:{rel}", rel, f.stat().st_size, GITHUB_FILE_WARN, GITHUB_FILE_ADVICE))
    for f in sorted((root / "web" / "public" / "data").glob("*/*.json")):
        if f.name not in ("jobs.json", "history.json"):
            continue
        rel = f.relative_to(root).as_posix()
        checks.append(Check(f"data-file:{rel}", rel, f.stat().st_size, DATA_FILE_WARN, ADVICE[f.name]))
        # jobs.json is gitignored, so only history.json can hit GitHub's per-file limit.
        if f.name == "history.json":
            checks.append(Check(f"github-file:{rel}", rel, f.stat().st_size, GITHUB_FILE_WARN, GITHUB_FILE_ADVICE))
    if state.is_dir():
        total = sum(f.stat().st_size for f in state.rglob("*") if f.is_file())
        checks.append(Check("state-total", "state/ (total)", total, STATE_TOTAL_WARN, STATE_ADVICE))
    return checks


def repo_size(root: Path = ROOT) -> tuple[int, str] | None:
    """(bytes, source). In Actions the checkout is shallow, so ask GitHub for the real size."""
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if repo and token:
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)["size"] * 1024, "GitHub API"
        except Exception as e:
            print(f"repo size from GitHub API failed: {e}", file=sys.stderr)
    try:
        if _git(root, "rev-parse", "--is-shallow-repository") == "true":
            return None
        stats = dict(line.split(": ", 1) for line in _git(root, "count-objects", "-v").splitlines())
        return (int(stats["size-pack"]) + int(stats["size"])) * 1024, "git count-objects"
    except Exception as e:
        print(f"git count-objects failed: {e}", file=sys.stderr)
        return None


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def should_alert(crossed_keys: list[str], last: dict, today: date) -> bool:
    """Email when the set of crossed thresholds changes, else at most once every REALERT_DAYS."""
    if not crossed_keys:
        return False
    if set(crossed_keys) != set(last.get("keys", [])):
        return True
    try:
        sent = date.fromisoformat(last["sent"])
    except (KeyError, TypeError, ValueError):
        return True
    return (today - sent).days >= REALERT_DAYS


def fmt(n: int) -> str:
    return f"{n / MB:.2f} MB" if n >= 100 * 1024 else f"{n / 1024:.1f} KB"


def table(checks: list[Check]) -> str:
    rows = [("item", "size", "threshold", "used", "")]
    for c in checks:
        if c.key.startswith("github-file:") and not c.crossed:
            continue  # same file is already listed against its lower threshold
        rows.append((c.label, fmt(c.size), fmt(c.limit), f"{c.size / c.limit:.0%}", "OVER" if c.crossed else "ok"))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip() for r in rows)


def render_html(checks: list[Check], test: bool) -> str:
    crossed = [c for c in checks if c.crossed]
    esc = html.escape
    parts = []
    if test:
        parts.append("<p><b>Test email</b> from storage_check.py --test; nothing below needs action unless marked OVER.</p>")
    if crossed:
        parts.append("<p>These stored files are nearing the point where cleanup or a real database is needed:</p>")
        parts.append("<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>")
        parts.append("<tr><th align='left'>Item</th><th>Size</th><th>Threshold</th><th align='left'>Recommendation</th></tr>")
        for c in crossed:
            parts.append(
                f"<tr><td>{esc(c.label)}</td><td>{fmt(c.size)}</td><td>{fmt(c.limit)}</td><td>{esc(c.advice)}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append("<p>No storage threshold is crossed.</p>")
    parts.append(f"<p>All measurements:</p><pre>{esc(table(checks))}</pre>")
    parts.append(f"<p>You'll get this again if the list changes, or in {REALERT_DAYS} days if it doesn't.</p>")
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-email", action="store_true", help="print sizes only")
    ap.add_argument("--test", action="store_true", help="send a [TEST] email even if nothing is crossed")
    args = ap.parse_args()

    checks = measure()
    repo = repo_size()
    if repo:
        size, source = repo
        checks.append(Check("repo-size", f"git repo ({source})", size, REPO_WARN, REPO_ADVICE))
    print(table(checks))

    crossed = [c for c in checks if c.crossed]
    for c in crossed:
        print(f"::warning::Storage nearing limit: {c.label} is {fmt(c.size)} (threshold {fmt(c.limit)}). {c.advice}")

    if args.no_email:
        return
    if args.test:
        _send("[TEST] Job tracker: storage check", render_html(checks, test=True))
        return

    keys = sorted(c.key for c in crossed)
    last = json.loads(ALERT_FILE.read_text()) if ALERT_FILE.exists() else {}
    today = date.today()
    if not should_alert(keys, last, today):
        if not keys and last.get("keys"):
            # All clear: forget the old set so a future crossing alerts right away.
            ALERT_FILE.write_text(json.dumps({"sent": last.get("sent"), "keys": []}, indent=1) + "\n")
        return
    if _send("Job tracker: storage nearing limits", render_html(checks, test=False)):
        ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)
        ALERT_FILE.write_text(json.dumps({"sent": today.isoformat(), "keys": keys}, indent=1) + "\n")


def _send(subject: str, body_html: str) -> bool:
    """True if the email went out. Never raises: a storage alert must not fail the run."""
    if not (os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD")):
        print("SMTP_USER / SMTP_PASSWORD not set; skipping storage email", file=sys.stderr)
        return False
    from tracker import send_email

    try:
        send_email(subject, body_html)
        return True
    except (Exception, SystemExit) as e:
        print(f"::warning::Storage alert email failed: {e}")
        return False


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"::warning::storage_check.py failed: {type(e).__name__}: {e}")
