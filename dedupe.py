"""Canonical company and role identity, so one opening counts once across boards, locations, and reposts.

"Anthropic, PBC" / "Anthropic" and "Sr. SWE, Infra (Remote - US)" / "Senior Software Engineer - Infrastructure"
map to the same keys. Postings sharing a role key are one role: the dashboard shows them as one row,
emails list them once, and a repost under a new posting ID is not reported as new.
"""

from __future__ import annotations

import re
import unicodedata

import usgeo

_COMPANY_NOISE = re.compile(
    r"\b(inc|llc|ltd|limited|corp|corporation|co|company|pbc|plc|gmbh|technologies|technology|labs?|ai|hq|the)\b"
)
_WORKPLACE = re.compile(r"\b(remote|hybrid|on-?site|in-?office|wfh|anywhere|work from home|area|based|only|first)\b")
_ROLE_WORD = re.compile(
    r"engineer|developer|scientist|architect|manager|lead|platform|infrastructure|\binfra\b|systems?|software|"
    r"data|security|research|\bml\b|\bai\b|cloud|network|devops|reliability|\bsre\b|gpu|compiler|kernel|"
    r"inference|training|staff|senior|principal|backend|frontend|full.?stack|admin|consultant|analyst",
    re.I,
)
_REGION = re.compile(r"\b(bay area|nyc|sf|emea|apac|latam|europe|americas|north america)\b", re.I)
_SEPARATORS = re.compile(r"\s+[-|/@:]\s+|,\s*")
_ABBREVIATIONS = [
    (r"\bsr\b", "senior"), (r"\bsnr\b", "senior"), (r"\bjr\b", "junior"), (r"\bprin\b", "principal"),
    (r"\bengr?\b", "engineer"), (r"\bmgr\b", "manager"), (r"\bswe\b", "software engineer"),
    (r"\bsre\b", "site reliability engineer"), (r"\binfra\b", "infrastructure"), (r"\bml\b", "machine learning"),
    (r"\bk8s\b", "kubernetes"), (r"\bdev ops\b", "devops"), (r"\bmts\b", "member of technical staff"),
    (r"\biv\b", "4"), (r"\biii\b", "3"), (r"\bii\b", "2"), (r"&", " and "),
]


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def company_key(name: str) -> str:
    s = _ascii(name)
    s = re.sub(r"\(.*?\)", " ", s).replace("&", " and ")
    key = re.sub(r"[^a-z0-9]", "", _COMPANY_NOISE.sub(" ", s))
    return key or re.sub(r"[^a-z0-9]", "", s)


def _is_location(segment: str) -> bool:
    s = segment.strip(" -|,/@:()[]")
    if not s:
        return True
    if not re.sub(r"[^a-z]+", " ", _WORKPLACE.sub(" ", s.lower())).strip():
        return True
    if _ROLE_WORD.search(s):
        return False
    return usgeo.is_us(s) or bool(usgeo.NON_US.search(s)) or bool(_REGION.search(s))


def title_key(title: str) -> str:
    t = re.sub(r"[\u2010-\u2015]", "-", unicodedata.normalize("NFKC", title))
    t = _ascii(t)
    t = re.sub(r"\s*[(\[]([^()\[\]]*)[)\]]", lambda m: "" if _is_location(m.group(1)) else m.group(0), t)
    t = next((t[: m.start()] for m in _SEPARATORS.finditer(t) if _is_location(t[m.end():])), t)
    for pattern, repl in _ABBREVIATIONS:
        t = re.sub(pattern, repl, t)
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", t).split())


def role_key(company: str, title: str) -> str:
    return f"{company_key(company)}|{title_key(title)}"
