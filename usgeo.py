"""US location matching: state detection and US-vs-elsewhere checks for free-form ATS location text."""

from __future__ import annotations

import re

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# Cities that often appear without a state.
CITIES = {
    "new york city": "NY", "nyc": "NY", "manhattan": "NY", "brooklyn": "NY", "san francisco": "CA",
    "los angeles": "CA", "san diego": "CA", "san jose": "CA", "palo alto": "CA", "seattle": "WA",
    "bellevue": "WA", "chicago": "IL", "boston": "MA", "cambridge, ma": "MA", "austin": "TX",
    "dallas": "TX", "houston": "TX", "denver": "CO", "boulder": "CO", "atlanta": "GA",
    "miami": "FL", "philadelphia": "PA", "pittsburgh": "PA", "phoenix": "AZ", "portland, or": "OR",
    "salt lake city": "UT", "minneapolis": "MN", "nashville": "TN", "raleigh": "NC",
    "charlotte": "NC", "detroit": "MI", "columbus": "OH", "indianapolis": "IN", "st. louis": "MO",
    "kansas city": "MO", "washington, d.c.": "DC", "washington dc": "DC", "reston": "VA",
    "arlington, va": "VA", "mclean": "VA", "jersey city": "NJ",
}

_NAME = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(STATES.values(), key=len, reverse=True)) + r")\b", re.I)
_NAME_TO_CODE = {n.lower(): c for c, n in STATES.items()}
# Codes are only trusted after a comma or a "US-" prefix ("Austin, TX", "US-CA-San Jose"), since bare
# two-letter words like OR / IN / ME are common English.
_CODE = re.compile(r"(?:,\s*|\bUSA?\s*[-,]\s*)(" + "|".join(STATES) + r")\b")
_CITY = re.compile(r"\b(" + "|".join(re.escape(c) for c in CITIES) + r")\b", re.I)

US_HINT = re.compile(r"\b(US|USA|U\.S\.A?\.?|United States( of America)?|North(ern)? America|Americas)\b", re.I)
WORLDWIDE = re.compile(r"\b(anywhere|worldwide|global)\b", re.I)
NON_US = re.compile(
    r"canada|ontario|toronto|vancouver|montr[eé]al|british columbia|quebec|alberta|calgary|ottawa|"
    r"(?<!new )mexico|brazil|argentina|colombia|costa rica|\bUK\b|united kingdom|england|london|ireland|dublin|"
    r"europe|\bEMEA\b|\bAPAC\b|\bLATAM\b|germany|france|spain|portugal|netherlands|poland|romania|"
    r"india|bangalore|bengaluru|hyderabad|pune|chennai|philippines|singapore|japan|australia|israel",
    re.I,
)


def states(text: str) -> set[str]:
    found = {_NAME_TO_CODE[m.lower()] for m in _NAME.findall(text)}
    found |= set(_CODE.findall(text))
    found |= {CITIES[m.lower()] for m in _CITY.findall(text)}
    # "Washington" alone is usually the state; "Washington, DC" is the city.
    if "DC" in found and not re.search(r"washington(?!,?\s*D\.?C)", text, re.I):
        found.discard("WA")
    return found


def is_us(segment: str) -> bool:
    """True when one location string (no ';' lists) points at the US."""
    if US_HINT.search(segment):
        return True
    if NON_US.search(segment):
        return False
    return bool(states(segment))


def is_remote_us(segment: str) -> bool:
    """Remote roles open to US candidates: 'Remote - US', 'Remote', 'Anywhere', 'Remote, Texas'."""
    if not re.search(r"remote|anywhere|worldwide", segment, re.I):
        return bool(re.fullmatch(r"\s*(US|USA|United States( of America)?)\s*", segment, re.I))
    if US_HINT.search(segment) or WORLDWIDE.search(segment) or states(segment):
        return True
    if NON_US.search(segment):
        return False
    # Plain "Remote" with nothing else.
    return not re.sub(r"[\W_]|remote|\b(job|position|role|work)\b", "", segment, flags=re.I)
