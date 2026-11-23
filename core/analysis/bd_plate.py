"""Bangladesh number plates: parse Bangla or English text into one canonical form, so a
watchlist entry typed in English, one typed in Bangla, and an OCR read all compare equal.

    "ঢাকা মেট্রো-গ ১২-৩৪৫৬"      → DHAKA-METRO-GA-12-3456
    "Dhaka Metro Ga 12-3456"   → DHAKA-METRO-GA-12-3456
    "CTG METRO KHA 11 2233"    → CHATTOGRAM-METRO-KHA-11-2233

Format (BRTA): <district or metro city> [মেট্রো] - <class letter> <2-digit series>-<4-digit number>.
Fuzzy comparison (one character off, OCR look-alikes) lives in `plate_distance`."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
EN_TO_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")

# Class letters used on BD plates → unique Latin code. Retroflex/dental pairs kept apart.
CLASS_BN = {
    "ক": "KA", "খ": "KHA", "গ": "GA", "ঘ": "GHA", "ঙ": "NGA", "চ": "CHA", "ছ": "CHHA", "জ": "JA", "ঝ": "JHA",
    "ট": "TTA", "ঠ": "TTHA", "ড": "DDA", "ঢ": "DDHA", "ত": "TA", "থ": "THA", "দ": "DA", "ধ": "DHA", "ন": "NA",
    "প": "PA", "ফ": "PHA", "ব": "BA", "ভ": "BHA", "ম": "MA", "য": "YA", "র": "RA", "ল": "LA", "শ": "SHA",
    "স": "SA", "হ": "HA", "অ": "A", "ই": "I", "উ": "U", "এ": "E",
}
CLASS_EN = {v: k for k, v in CLASS_BN.items()}
# Common English spellings people type
CLASS_ALIASES = {"KO": "KA", "KHO": "KHA", "GO": "GA", "GHO": "GHA", "CHO": "CHA", "JO": "JA", "TO": "TA",
                 "THO": "THA", "DO": "DA", "DHO": "DHA", "NO": "NA", "PO": "PA", "PHO": "PHA", "FA": "PHA",
                 "BO": "BA", "BHO": "BHA", "VA": "BHA", "MO": "MA", "JA2": "YA", "RO": "RA", "LO": "LA",
                 "SHO": "SHA", "SO": "SA", "HO": "HA", "DDO": "DDA", "TTO": "TTA"}

# District / metro names. Key = canonical code; values = Bangla and English spellings.
CITIES = {
    "DHAKA": ["ঢাকা", "DHAKA", "DHK"],
    "CHATTOGRAM": ["চট্টগ্রাম", "চট্ট", "CHATTOGRAM", "CHITTAGONG", "CTG", "CHATTA"],
    "KHULNA": ["খুলনা", "KHULNA"],
    "RAJSHAHI": ["রাজশাহী", "RAJSHAHI"],
    "SYLHET": ["সিলেট", "SYLHET"],
    "BARISHAL": ["বরিশাল", "BARISHAL", "BARISAL"],
    "RANGPUR": ["রংপুর", "RANGPUR"],
    "MYMENSINGH": ["ময়মনসিংহ", "ময়মনসিংহ", "MYMENSINGH"],
    "GAZIPUR": ["গাজীপুর", "GAZIPUR"],
    "NARAYANGANJ": ["নারায়ণগঞ্জ", "নারায়ণগঞ্জ", "NARAYANGANJ"],
    "CUMILLA": ["কুমিল্লা", "CUMILLA", "COMILLA"],
    "BOGURA": ["বগুড়া", "বগুড়া", "BOGURA", "BOGRA"],
    "COXSBAZAR": ["কক্সবাজার", "COXSBAZAR", "COXS BAZAR", "COX'S BAZAR"],
    "JASHORE": ["যশোর", "JASHORE", "JESSORE"],
    "NOAKHALI": ["নোয়াখালী", "নোয়াখালী", "NOAKHALI"],
    "FENI": ["ফেনী", "FENI"],
    "TANGAIL": ["টাঙ্গাইল", "TANGAIL"],
    "NARSINGDI": ["নরসিংদী", "NARSINGDI"],
    "MUNSHIGANJ": ["মুন্সীগঞ্জ", "MUNSHIGANJ"],
    "MANIKGANJ": ["মানিকগঞ্জ", "MANIKGANJ"],
    "DINAJPUR": ["দিনাজপুর", "DINAJPUR"],
    "PABNA": ["পাবনা", "PABNA"],
    "KUSHTIA": ["কুষ্টিয়া", "কুষ্টিয়া", "KUSHTIA"],
    "BRAHMANBARIA": ["ব্রাহ্মণবাড়িয়া", "ব্রাহ্মণবাড়িয়া", "BRAHMANBARIA"],
}
METRO_WORDS = {"মেট্রো", "METRO", "MET"}

_CITY_LOOKUP = {}
for code, names in CITIES.items():
    for n in names:
        _CITY_LOOKUP[unicodedata.normalize("NFC", n).upper().replace(" ", "").replace("'", "")] = code

CITY_BN = {code: names[0] for code, names in CITIES.items()}


@dataclass(frozen=True)
class Plate:
    city: Optional[str]          # canonical city code, None if missing / unknown
    metro: bool
    cls: Optional[str]           # class letter code (GA, KHA…)
    series: Optional[str]        # 2 digits
    number: Optional[str]        # 4 digits

    @property
    def canonical(self) -> str:
        parts = [self.city or "?"]
        if self.metro:
            parts.append("METRO")
        parts += [self.cls or "?", self.series or "??", self.number or "????"]
        return "-".join(parts)

    @property
    def complete(self) -> bool:
        return bool(self.city and self.cls and self.series and self.number)

    @property
    def digits(self) -> str:
        return f"{self.series or ''}{self.number or ''}"

    def bangla(self) -> str:
        city = CITY_BN.get(self.city or "", self.city or "?")
        head = f"{city} মেট্রো" if self.metro else city
        cls = CLASS_EN.get(self.cls or "", "?")
        s = (self.series or "??").translate(EN_TO_BN_DIGITS)
        n = (self.number or "????").translate(EN_TO_BN_DIGITS)
        return f"{head}-{cls} {s}-{n}"


def _clean(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").translate(BN_DIGITS).upper()
    return re.sub(r"[\s\-_.:/|,]+", " ", t).strip()


def parse(text: str) -> Optional[Plate]:
    """Best-effort parse. Returns None when there is no 6-digit series+number to anchor on."""
    t = _clean(text)
    if not t:
        return None
    m = re.search(r"(\d{2})\s*(\d{4})(?!\d)", t)
    if not m:
        return None
    series, number = m.group(1), m.group(2)
    head = t[:m.start()].strip()
    tokens = head.split()
    metro = any(tok in METRO_WORDS for tok in tokens)
    tokens = [tok for tok in tokens if tok not in METRO_WORDS]

    cls = None
    if tokens:
        last = tokens[-1]
        # Bangla letter may be glued to the city word ("মেট্রোগ") or stand alone
        if last in CLASS_BN:
            cls = CLASS_BN[last]
            tokens = tokens[:-1]
        elif last in CLASS_EN:
            cls = last
            tokens = tokens[:-1]
        elif last in CLASS_ALIASES:
            cls = CLASS_ALIASES[last]
            tokens = tokens[:-1]
        elif last and last[-1] in CLASS_BN and len(last) > 1:
            cls = CLASS_BN[last[-1]]
            rest = last[:-1]
            if rest in METRO_WORDS or rest.endswith("মেট্রো"):
                metro = True
                rest = rest[: -len("মেট্রো")] if rest.endswith("মেট্রো") else ""
            tokens = tokens[:-1] + ([rest] if rest else [])

    city = None
    joined = "".join(tokens).replace("'", "")
    if joined.endswith("মেট্রো"):
        metro, joined = True, joined[: -len("মেট্রো")]
    if joined.endswith("METRO"):
        metro, joined = True, joined[: -len("METRO")]
    if joined in _CITY_LOOKUP:
        city = _CITY_LOOKUP[joined]
    else:
        for tok in tokens:
            if tok.replace("'", "") in _CITY_LOOKUP:
                city = _CITY_LOOKUP[tok.replace("'", "")]
                break
    return Plate(city=city, metro=metro, cls=cls, series=series, number=number)


def canonical(text: str) -> Optional[str]:
    """Canonical string, or None when the text holds no plate number at all."""
    p = parse(text)
    return p.canonical if p else None


# ——— Fuzzy comparison ———

# Digit look-alikes OCR confuses (both scripts end up as ASCII digits after translation).
DIGIT_CONFUSION = {frozenset(p) for p in (("0", "8"), ("1", "7"), ("3", "8"), ("5", "6"), ("6", "8"), ("2", "7"),
                                          ("4", "9"), ("0", "6"), ("5", "9"))}
CLASS_CONFUSION = {frozenset(p) for p in (("DA", "DDA"), ("DHA", "DDHA"), ("TA", "TTA"), ("THA", "TTHA"),
                                          ("BA", "BHA"), ("GA", "GHA"), ("KA", "KHA"), ("CHA", "CHHA"),
                                          ("JA", "JHA"), ("SA", "SHA"), ("PA", "PHA"))}


def plate_distance(a: Plate, b: Plate) -> float:
    """0 = same plate. Each differing digit costs 1 (0.5 if a known OCR confusion); a differing
    class letter 1 (0.5 if confusable); city / metro mismatches count only when both are known."""
    d = 0.0
    da, db = a.digits, b.digits
    if len(da) != len(db):
        return 99.0
    for x, y in zip(da, db):
        if x != y:
            d += 0.5 if frozenset((x, y)) in DIGIT_CONFUSION else 1.0
    if a.cls and b.cls and a.cls != b.cls:
        d += 0.5 if frozenset((a.cls, b.cls)) in CLASS_CONFUSION else 1.0
    if a.city and b.city and a.city != b.city:
        d += 1.0
    if a.city and b.city and a.metro != b.metro:
        d += 0.5
    return d


def compare(read: str, listed: str) -> str:
    """'exact' | 'fuzzy' (≤ 1 char off / OCR confusion) | 'none'. Missing parts of an OCR read
    (city or class not read) do not count against it, but the 6 digits must be there."""
    a, b = parse(read), parse(listed)
    if not a or not b:
        return "none"
    if a.canonical == b.canonical:
        return "exact"
    d = plate_distance(a, b)
    if d == 0:
        return "exact" if a.complete and b.complete else "fuzzy"
    return "fuzzy" if d <= 1.0 else "none"
