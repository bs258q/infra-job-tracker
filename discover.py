"""Find which public job board (Greenhouse / Lever / Ashby) a company uses.

Usage: python discover.py "Together AI" anthropic "Thinking Machines"
Prints companies.toml entries for every board that returns open jobs.
"""

from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor

import ats

BOARDS = ("greenhouse", "lever", "ashby")


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


def probe(name: str, board: str, slug: str):
    try:
        n = sum(1 for _ in ats.FETCHERS[board](name, slug=slug))
    except Exception:
        return None
    return (name, board, slug, n) if n else None


def main(names: list[str]) -> None:
    tasks = [(n, b, s) for n in names for s in slug_candidates(n) for b in BOARDS]
    with ThreadPoolExecutor(max_workers=24) as pool:
        hits = [h for h in pool.map(lambda t: probe(*t), tasks) if h]
    found = {h[0] for h in hits}
    for name, board, slug, n in sorted(hits, key=lambda h: (h[0].lower(), -h[3])):
        print(f'[[company]]  # {n} open jobs\nname = "{name}"\nats = "{board}"\nslug = "{slug}"\n')
    for name in names:
        if name not in found:
            print(f"# not found on greenhouse/lever/ashby: {name}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
