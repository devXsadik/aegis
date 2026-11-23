"""Bangladesh plate parsing, canonical form and fuzzy comparison (Bangla + English)."""
import pytest

from core.analysis import bd_plate as bp


@pytest.mark.parametrize("text", [
    "ঢাকা মেট্রো-গ ১২-৩৪৫৬",
    "ঢাকা মেট্রো গ ১২ ৩৪৫৬",
    "ঢাকামেট্রো-গ১২-৩৪৫৬",
    "Dhaka Metro Ga 12-3456",
    "DHAKA METRO-GA 12-3456",
    "dhaka metro go 123456",
    "DHAKA-METRO-GA-12-3456",
])
def test_same_plate_many_spellings(text):
    assert bp.canonical(text) == "DHAKA-METRO-GA-12-3456"


def test_other_cities_and_classes():
    assert bp.canonical("চট্ট মেট্রো-খ ১১-২২৩৩") == "CHATTOGRAM-METRO-KHA-11-2233"
    assert bp.canonical("CTG METRO KHA 11 2233") == "CHATTOGRAM-METRO-KHA-11-2233"
    assert bp.canonical("গাজীপুর-হ ৫১-০০১২") == "GAZIPUR-HA-51-0012"
    assert bp.canonical("Cox's Bazar Ha 51-0012") == "COXSBAZAR-HA-51-0012"
    # retroflex vs dental letters stay distinct
    assert bp.canonical("ঢাকা মেট্রো-ড ১২-৩৪৫৬") == "DHAKA-METRO-DDA-12-3456"
    assert bp.canonical("ঢাকা মেট্রো-দ ১২-৩৪৫৬") == "DHAKA-METRO-DA-12-3456"


def test_partial_reads_and_garbage():
    p = bp.parse("গ ১২-৩৪৫৬")
    assert p.city is None and p.cls == "GA" and p.canonical == "?-GA-12-3456" and not p.complete
    assert bp.parse("no plate here") is None
    assert bp.parse("12-345") is None
    assert bp.parse("") is None


def test_bangla_rendering_round_trip():
    p = bp.parse("Dhaka Metro Ga 12-3456")
    assert p.bangla() == "ঢাকা মেট্রো-গ ১২-৩৪৫৬"
    assert bp.canonical(p.bangla()) == p.canonical


@pytest.mark.parametrize("read,listed,result", [
    ("ঢাকা মেট্রো-গ ১২-৩৪৫৬", "Dhaka Metro Ga 12-3456", "exact"),
    ("DHAKA METRO GA 12-3458", "DHAKA METRO GA 12-3456", "fuzzy"),     # one digit off (6↔8 confusion)
    ("DHAKA METRO GA 12-3459", "DHAKA METRO GA 12-3456", "fuzzy"),     # one digit off
    ("DHAKA METRO GHA 12-3456", "DHAKA METRO GA 12-3456", "fuzzy"),    # confusable class letter
    ("GA 12-3456", "DHAKA METRO GA 12-3456", "fuzzy"),                 # city not read
    ("DHAKA METRO GA 12-9999", "DHAKA METRO GA 12-3456", "none"),
    ("DHAKA METRO GA 99-3456", "DHAKA METRO GA 12-3456", "none"),
    ("KHULNA METRO GA 12-3456", "DHAKA METRO GA 12-3456", "fuzzy"),    # city differs only
    ("unreadable", "DHAKA METRO GA 12-3456", "none"),
])
def test_compare(read, listed, result):
    assert bp.compare(read, listed) == result
