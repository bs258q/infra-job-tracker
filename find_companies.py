"""Find new companies to track with Parallel FindAll, one profile at a time.

python find_companies.py --profile infra                 weekly run: FindAll for the profile's [discovery]
                                                         search, excluding every company already tracked or
                                                         seen; companies whose job board works and has
                                                         matching roles go to companies/found/infra-<date>.toml
python find_companies.py --profile infra --preview       cheap FindAll preview (up to 10 candidates); writes nothing
python find_companies.py --profile infra --recheck-only  no Parallel call; retry earlier finds that had no
                                                         supported job board or no matching roles yet
python find_companies.py --profile infra --names "Nscale" "IREN=https://iren.com/careers"
                                                         check specific companies (no Parallel call)

Free sources run too: the YC directory's hiring companies matching the profile's `yc_tags`.

Needs PARALLEL_API_KEY. Every company FindAll returns is logged in state/<profile>/discovery.json so it
is never paid for twice. Closing the pull request that adds a company rejects it for good; delete its
entry from discovery.json to have it considered again.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ats
import discover
import tracker

ROOT = Path(__file__).parent
API = "https://api.parallel.ai/v1beta/findall"
YC_HIRING = "https://yc-oss.github.io/api/companies/hiring.json"
POLL_SECONDS = 30
RECHECK_DAYS = 84
# Days between free rechecks of earlier finds, by why they weren't added.
RECHECK_EVERY = {"no_board": 28, "no_roles": 14}
NOT_COMPANIES = ats.AGGREGATORS

# Replayed on every run (FindAll's stored schema is not a faithful copy of enrichment requests).
ENRICHMENT = {
    "processor": "base",
    "output_schema": {
        "type": "json",
        "json_schema": {
            "type": "object",
            "properties": {
                "careers_url": {
                    "type": "string",
                    "description": (
                        "URL of the company's public job board listing its open roles. Prefer the "
                        "applicant-tracking-system board itself, e.g. job-boards.greenhouse.io/<company>, "
                        "jobs.lever.co/<company>, jobs.ashbyhq.com/<company>, apply.workable.com/<company>, "
                        "ats.rippling.com/<company>, jobs.smartrecruiters.com/<company>, or "
                        "<company>.wd<N>.myworkdayjobs.com/<site>, over the company's own careers page. "
                        "Empty string if there is none."
                    ),
                },
                "example_role": {
                    "type": "string",
                    "description": "Title and location of one currently open role that satisfies the search.",
                },
            },
            "required": ["careers_url", "example_role"],
            "additionalProperties": False,
        },
    },
}


def api(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "x-api-key": os.environ.get("PARALLEL_API_KEY", "").strip(),
            "Content-Type": "application/json",
            "User-Agent": "infra-job-tracker/1.0",
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            # POSTs create billed work, so only reads are retried.
            if method == "GET" and (e.code == 429 or e.code >= 500) and attempt < 3:
                time.sleep(5 * 2**attempt)
                continue
            raise RuntimeError(f"Parallel {method} {path} failed ({e.code}): {detail}") from e
        except (urllib.error.URLError, TimeoutError):
            if method == "GET" and attempt < 3:
                time.sleep(5 * 2**attempt)
                continue
            raise
    raise AssertionError("unreachable")


def board_url(c: dict) -> str:
    """A URL that identifies a tracked company for FindAll's exclude list."""
    match c.get("ats"):
        case "greenhouse":
            return f"https://job-boards.greenhouse.io/{c['slug']}"
        case "lever":
            return f"https://jobs.lever.co/{c['slug']}"
        case "ashby":
            return f"https://jobs.ashbyhq.com/{c['slug']}"
        case "workday":
            return f"https://{c['host']}/{c['site']}"
        case "workable":
            return f"https://apply.workable.com/{c['slug']}"
        case "gem":
            return f"https://jobs.gem.com/{c['slug']}"
        case "smartrecruiters":
            return f"https://jobs.smartrecruiters.com/{c['slug']}"
        case "rippling":
            return f"https://ats.rippling.com/{c['slug']}/jobs"
        case "recruitee":
            return f"https://{c['slug']}.recruitee.com"
        case "breezy":
            return f"https://{c['slug']}.breezy.hr"
        case "yc":
            return f"https://www.ycombinator.com/companies/{c['slug']}/jobs"
        case "oracle":
            return f"https://{c['host']}/hcmUI/CandidateExperience/en/sites/{c['site']}"
        case "eightfold":
            return f"https://{c['host']}"
        case "amazon":
            return "https://www.amazon.jobs"
    return ""


def board_key(entry: dict) -> tuple[str, str]:
    return entry["ats"], (entry.get("slug") or entry.get("tenant") or entry.get("host") or "").lower()


def exclude_list(tracked: list[dict], ledger: dict) -> list[dict]:
    out = {c["name"].lower(): {"name": c["name"], "url": board_url(c)} for c in tracked if c["ats"] not in NOT_COMPANIES}
    for key, rec in ledger["companies"].items():
        out.setdefault(key, {"name": rec["name"], "url": rec.get("url") or rec.get("careers_url") or ""})
    return [e for e in out.values() if e["url"]]


def load_ledger(profile: str) -> dict:
    path = ROOT / "state" / profile / "discovery.json"
    return json.loads(path.read_text()) if path.exists() else {"runs": [], "companies": {}}


def save_ledger(profile: str, ledger: dict) -> None:
    path = ROOT / "state" / profile / "discovery.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n")


def _value(candidate: dict, field: str) -> str:
    return str(((candidate.get("output") or {}).get(field) or {}).get("value") or "").strip()


def record_from_candidate(candidate: dict, findall_id: str, conditions: list[dict], today: str) -> dict:
    citations = [c.get("url") for b in candidate.get("basis") or [] for c in b.get("citations") or []]
    why = _value(candidate, "example_role") or next(
        (_value(candidate, c["name"]) for c in conditions if _value(candidate, c["name"])), candidate.get("description") or ""
    )
    return {
        "name": candidate["name"].strip(),
        "url": candidate.get("url") or "",
        "careers_url": _value(candidate, "careers_url"),
        "why": re.sub(r"\s+", " ", why)[:200],
        "evidence": list(dict.fromkeys(u for u in citations if u))[:3],
        "findall_id": findall_id,
        "first_seen": today,
        "status": "new",
    }


def resolve_board(name: str, *urls: str, yc_slug: str = "") -> tuple[dict, str] | None:
    """The job board with the most open postings: boards at the given URLs, then the company's YC jobs
    page (certain identity, unlike a guess), then guessed slugs on every board in `discover.BOARDS`."""
    def best(entries: list[dict]) -> dict | None:
        counts = list(pool.map(lambda e: discover.count_jobs(name, e), entries))
        return entries[max(range(len(entries)), key=counts.__getitem__)] if any(counts) else None

    with ThreadPoolExecutor(max_workers=16) as pool:
        for url in filter(None, urls):
            if entry := best(discover.boards_at_url(url)):
                return entry, url
        if yc_slug and (entry := best([{"ats": "yc", "slug": yc_slug}])):
            return entry, f"https://www.ycombinator.com/companies/{yc_slug}/jobs"
        guesses = [{"ats": b, "slug": s} for s in discover.slug_candidates(name) for b in discover.BOARDS]
        if entry := best(guesses):
            return entry, "guessed from the company name"
    return None


def yc_records(disc: dict, known: set[str], today: str) -> list[dict]:
    """YC companies marked hiring in the YC directory (via yc-oss.github.io) that fit `yc_tags`."""
    tags = re.compile(disc["yc_tags"], re.I)
    regions = set(disc.get("yc_regions", ["United States of America", "America / Canada", "Remote"]))
    data = json.load(urllib.request.urlopen(urllib.request.Request(YC_HIRING, headers={"User-Agent": "infra-job-tracker/1.0"}), timeout=60))
    out = []
    for c in data:
        labels = (c.get("tags") or []) + (c.get("industries") or []) + [c.get("subindustry") or ""]
        if c["name"].lower() in known or not regions & set(c.get("regions") or []) or not any(tags.search(t) for t in labels):
            continue
        site = (c.get("website") or "").rstrip("/")
        out.append({
            "name": c["name"].strip(), "url": site, "careers_url": f"{site}/careers" if site else "",
            "yc_slug": c.get("slug") or "", "why": f"YC {c.get('batch', '')}: {c.get('one_liner') or ''}".strip(),
            "evidence": [f"https://www.ycombinator.com/companies/{c.get('slug')}"], "source": "yc",
            "first_seen": today, "status": "new",
        })
    return out


def name_records(names: list[str], today: str) -> list[dict]:
    """Records for `Name` or `Name=careers URL` entries given on the command line."""
    out = []
    for item in names:
        name, _, url = item.partition("=")
        out.append({"name": name.strip(), "url": "", "careers_url": url.strip(), "why": "added by name",
                    "evidence": [url.strip()] if url.strip() else [], "source": "manual", "first_seen": today, "status": "new"})
    return out


def matching_roles(name: str, entry: dict, cfg: dict) -> int:
    matches, _ = tracker.fetch_all([{"name": name, **entry}], tracker.Filters(cfg), cfg.get("search", {}).get("queries", []))
    return len(matches)


def assess(rec: dict, cfg: dict, tracked_names: set[str], tracked_boards: set[tuple[str, str]], today: str) -> bool:
    """Find the company's board and count roles matching the profile; True when it should be added."""
    rec["last_checked"] = today
    if rec["name"].lower() in tracked_names:
        rec["status"] = "duplicate"
        return False
    found = resolve_board(rec["name"], rec.get("careers_url", ""), rec.get("url", ""), yc_slug=rec.get("yc_slug", ""))
    if not found:
        rec["status"] = "no_board"
        return False
    entry, source = found
    rec.update(board=entry, board_source=source)
    if board_key(entry) in tracked_boards:
        rec["status"] = "duplicate"
        return False
    rec["matching_roles"] = matching_roles(rec["name"], entry, cfg)
    if not rec["matching_roles"]:
        rec["status"] = "no_roles"
        return False
    rec["status"] = "added"
    tracked_names.add(rec["name"].lower())
    tracked_boards.add(board_key(entry))
    return True


def run_findall(disc: dict, ledger: dict, exclude: list[dict], preview: bool, wait_minutes: float, save) -> tuple[dict, list[dict]] | None:
    """Matched candidates from a new run, or from the run a previous invocation left active."""
    record = next((r for r in ledger["runs"] if r.get("active")), None) if not preview else None
    if record:
        print(f"resuming FindAll run {record['findall_id']}", file=sys.stderr)
    else:
        body = {
            "objective": disc["objective"],
            "entity_type": disc.get("entity_type", "companies"),
            "match_conditions": disc["match_conditions"],
            "generator": "preview" if preview else disc.get("generator", "core"),
            "match_limit": 10 if preview else disc.get("match_limit", 25),
            "exclude_list": exclude,
        }
        run = api("POST", "/runs", body)
        record = {"findall_id": run["findall_id"], "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "generator": body["generator"], "match_limit": body["match_limit"], "active": True}
        print(f"started FindAll run {record['findall_id']} ({body['generator']}, up to {body['match_limit']} matches, "
              f"{len(exclude)} excluded)", file=sys.stderr)
        if not preview:
            ledger["runs"].append(record)
            save()
            try:
                api("POST", f"/runs/{record['findall_id']}/enrich", ENRICHMENT)
                record["enriched"] = True
            except Exception as e:
                print(f"warning: enrichment request failed, boards will be guessed from names: {e}", file=sys.stderr)
            save()

    findall_id = record["findall_id"]
    deadline = time.monotonic() + wait_minutes * 60
    while True:
        status = api("GET", f"/runs/{findall_id}")["status"]
        metrics = status.get("metrics") or {}
        print(f"  {status['status']}: {metrics.get('generated_candidates_count', 0)} candidates, "
              f"{metrics.get('matched_candidates_count', 0)} matched", file=sys.stderr)
        if not status.get("is_active"):
            break
        if time.monotonic() > deadline:
            print(f"FindAll run {findall_id} is still running; the next invocation picks it up.", file=sys.stderr)
            return None
        time.sleep(POLL_SECONDS)

    def matched() -> list[dict]:
        candidates = api("GET", f"/runs/{findall_id}/result").get("candidates") or []
        return [c for c in candidates if c.get("match_status") == "matched"]

    found = matched()
    # Enrichment output can land after the run reports completion.
    for _ in range(6):
        if not record.get("enriched") or all("careers_url" in (c.get("output") or {}) for c in found):
            break
        if time.monotonic() > deadline:
            break
        time.sleep(POLL_SECONDS)
        found = matched()
    record.update(active=False, status=status["status"], termination_reason=status.get("termination_reason"), matched=len(found))
    save()
    if status["status"] != "completed":
        print(f"FindAll run {findall_id} ended as {status['status']}; using its {len(found)} matches.", file=sys.stderr)
    return record, found


def write_found(profile: str, recs: list[dict], today: str) -> Path:
    path = ROOT / "companies" / "found" / f"{profile}-{today}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = [] if path.exists() else [
        f"# Found by Parallel FindAll for the {profile} profile on {today} (find_companies.py).\n"
        "# Delete an entry to stop tracking it; its record in state/" + profile + "/discovery.json keeps it from coming back.\n"
    ]
    for r in recs:
        parts.append(f"\n# {r['matching_roles']} matching roles when found. {r['why']}".rstrip() + "\n")
        if r.get("evidence"):
            parts.append(f"# Source: {r['evidence'][0]}\n")
        parts.append(discover.toml_entry(r["name"], r["board"]))
    with path.open("a") as f:
        f.write("".join(parts))
    return path


def summary(profile: str, run: dict | None, added: list[dict], ledger: dict, path: Path | None) -> str:
    lines = [f"## {profile}", ""]
    if run:
        lines.append(f"FindAll run `{run['findall_id']}`: {run.get('matched', 0)} matches ({run.get('status')}).")
    if added:
        noun = "company" if len(added) == 1 else "companies"
        lines += ["", f"Adds {len(added)} {noun} in `{path.relative_to(ROOT)}`:", "",
                  "| Company | Board | Matching roles | Why | Source |", "|---|---|---|---|---|"]
        for r in added:
            board = f"{r['board']['ats']} `{r['board'].get('slug') or r['board'].get('site')}`"
            source = f"[link]({r['evidence'][0]})" if r.get("evidence") else ""
            why = r["why"].replace("|", "/")
            lines.append(f"| {r['name']} | {board} | {r['matching_roles']} | {why} | {source} |")
    else:
        lines += ["", "No new companies to add."]
    waiting = {s: sum(1 for r in ledger["companies"].values() if r["status"] == s) for s in ("no_board", "no_roles")}
    lines += ["", f"Waiting for a recheck: {waiting['no_board']} without a supported job board, "
              f"{waiting['no_roles']} with no matching roles yet.", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="infra")
    ap.add_argument("--preview", action="store_true", help="FindAll preview run; print candidates, write nothing")
    ap.add_argument("--recheck-only", action="store_true", help="skip Parallel; recheck earlier finds")
    ap.add_argument("--no-yc", action="store_true", help="skip the YC directory")
    ap.add_argument("--names", nargs="+", metavar="NAME[=URL]", help="check these companies instead of searching")
    ap.add_argument("--wait-minutes", type=float, default=60, help="how long to wait for the FindAll run")
    ap.add_argument("--summary", help="append a markdown summary (pull request body) to this file")
    args = ap.parse_args()

    cfg = tracker.load_profile(args.profile)
    disc = cfg.get("discovery")
    if not disc:
        print(f"[{args.profile}] no [discovery] section; nothing to do", file=sys.stderr)
        return
    today = date.today().isoformat()
    ledger = load_ledger(args.profile)
    tracked = tracker.load_companies(cfg)
    tracked_names = {c["name"].lower() for c in tracked}
    tracked_boards = {board_key(c) for c in tracked if c["ats"] not in NOT_COMPANIES}
    added: list[dict] = []

    def save() -> None:
        if not args.preview:
            save_ledger(args.profile, ledger)

    def consider(rec: dict, recheck: bool = False) -> None:
        key = rec["name"].lower()
        old = ledger["companies"].get(key)
        if old and not args.preview and not (recheck and old["status"] in RECHECK_EVERY):
            return
        if old:
            rec["first_seen"] = old["first_seen"]
        is_new = assess(rec, cfg, tracked_names, tracked_boards, today)
        board = rec.get("board") or {}
        print(f"  {rec['name'][:28]:<28} {rec['status']:<10} {board.get('ats', '-'):<10} "
              f"{board.get('slug') or board.get('site') or '-':<24} {rec.get('matching_roles', '-')}", file=sys.stderr)
        if args.preview:
            return
        ledger["companies"][key] = rec
        if is_new:
            added.append(rec)
        save()

    if not args.preview:
        cutoff = (date.today() - timedelta(days=RECHECK_DAYS)).isoformat()
        due = [
            r for r in ledger["companies"].values()
            if r["status"] in RECHECK_EVERY and r["first_seen"] >= cutoff
            and r.get("last_checked", "") <= (date.today() - timedelta(days=RECHECK_EVERY[r["status"]])).isoformat()
        ]
        if due:
            print(f"[{args.profile}] rechecking {len(due)} earlier finds", file=sys.stderr)
        added += [r for r in due if assess(r, cfg, tracked_names, tracked_boards, today)]
        save()

    if args.names:
        print(f"[{args.profile}] checking {len(args.names)} companies by name", file=sys.stderr)
        for rec in name_records(args.names, today):
            consider(rec, recheck=True)

    if disc.get("yc_tags") and not (args.no_yc or args.names or args.preview):
        recs = yc_records(disc, tracked_names | set(ledger["companies"]), today)
        print(f"[{args.profile}] checking {len(recs)} hiring YC companies not seen before", file=sys.stderr)
        for rec in recs:
            consider(rec)

    run = None
    if args.recheck_only or args.names:
        pass
    elif not os.environ.get("PARALLEL_API_KEY", "").strip():
        print(f"[{args.profile}] PARALLEL_API_KEY not set; skipping the FindAll search", file=sys.stderr)
    else:
        result = run_findall(disc, ledger, exclude_list(tracked, ledger), args.preview, args.wait_minutes, save)
        if result:
            run, candidates = result
            for cand in candidates:
                consider(record_from_candidate(cand, run["findall_id"], disc["match_conditions"], today))

    if args.preview:
        return
    path = write_found(args.profile, added, today) if added else None
    text = summary(args.profile, run, added, ledger, path)
    print(text)
    if args.summary:
        with open(args.summary, "a") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
