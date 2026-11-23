"""Every scoring case of spec 7.5, night colour weighting, and candidate suppression."""
from core.analysis.vehicle_match import DEFAULTS, explain, merge_config, score

ENTRY = {"plate": "ঢাকা মেট্রো-গ ১২-৩৪৫৬", "vehicle_type": "car", "color_primary": "white", "make_model": "toyota_axio"}
GOOD = {"vehicle_type": "car", "color": "white", "make_model": "Toyota Axio",
        "confidences": {"plate": 0.9, "type": 0.9, "color": 0.9, "model": 0.8}}


def test_plate_exact_and_attributes_agree_is_critical():
    r = score({**GOOD, "plate_text": "Dhaka Metro Ga 12-3456"}, ENTRY)
    assert (r.level, r.severity, r.label) == ("confirmed", "critical", "Confirmed vehicle match")
    assert explain(r) == {"type": "✓", "color": "✓", "model": "✓"}


def test_plate_exact_but_vehicle_differs_is_swapped_plate():
    r = score({**GOOD, "plate_text": "DHAKA METRO GA 12-3456", "vehicle_type": "pickup"}, ENTRY)
    assert r.level == "plate_mismatch" and r.severity == "high" and "fake/swapped" in r.label
    assert explain(r)["type"] == "✗"


def test_fuzzy_plate_with_attributes_is_probable():
    r = score({**GOOD, "plate_text": "DHAKA METRO GA 12-3458"}, ENTRY)
    assert (r.plate, r.level, r.severity) == ("fuzzy", "probable", "high")


def test_fuzzy_plate_only_is_possible():
    r = score({"plate_text": "DHAKA METRO GA 12-3458"}, ENTRY)
    assert (r.level, r.severity) == ("possible", "low")
    r = score({**GOOD, "plate_text": "DHAKA METRO GA 12-3458", "color": "red"}, ENTRY)
    assert r.level == "possible"                       # attributes disagree: no upgrade


def test_low_confidence_plate_read_is_not_exact():
    r = score({**GOOD, "plate_text": "DHAKA METRO GA 12-3456", "confidences": {**GOOD["confidences"], "plate": 0.3}}, ENTRY)
    assert r.plate == "fuzzy" and r.level == "probable"


def test_candidate_only_inside_lookout():
    read = {**GOOD, "plate_text": None, "reid": 0.85}
    outside = score(read, ENTRY, lookout=False)
    assert outside.level is None and "outside an active lookout" in outside.suppressed
    inside = score(read, ENTRY, lookout=True)
    assert (inside.level, inside.severity, inside.label) == ("candidate", "medium", "Candidate vehicle")


def test_candidate_needs_reid_and_model():
    assert score({**GOOD, "reid": 0.5}, ENTRY, lookout=True).level is None
    assert score({**GOOD}, ENTRY, lookout=True).suppressed.startswith("re-ID")
    assert score({**GOOD, "make_model": "Honda Civic", "reid": 0.9}, ENTRY, lookout=True).level is None
    # plate-less entries (type + colour only) can still be candidates inside a lookout
    entry = {"vehicle_type": "microbus", "color_primary": "white"}
    r = score({"vehicle_type": "microbus", "color": "white", "reid": 0.9}, entry, lookout=True)
    assert r.level == "candidate"


def test_night_colour_is_unreliable():
    read = {**GOOD, "plate_text": "DHAKA METRO GA 12-3456", "color": "grey"}
    day = score(read, ENTRY)
    night = score(read, ENTRY, night=True)
    assert day.level == "plate_mismatch"               # grey ≠ white by day: suspicious
    assert night.level == "confirmed"                  # at night a colour difference proves nothing
    assert explain(night)["color"] == "~"
    c_day = next(c for c in score({**GOOD, "plate_text": "DHAKA METRO GA 12-3456"}, ENTRY).checks if c.attribute == "color")
    c_night = next(c for c in score({**GOOD, "plate_text": "DHAKA METRO GA 12-3456"}, ENTRY, night=True).checks if c.attribute == "color")
    assert c_night.weight < c_day.weight
    # and colour cannot make a night-time candidate on its own
    entry = {"vehicle_type": "car", "color_primary": "white"}
    assert score({"vehicle_type": "car", "color": "grey", "reid": 0.9}, entry, night=True, lookout=True).level is None


def test_unknown_attributes_and_low_confidence():
    r = score({"plate_text": "DHAKA METRO GA 12-3456", "vehicle_type": "pickup", "confidences": {"type": 0.2}}, ENTRY)
    assert r.level == "confirmed"                       # a 20 % type guess cannot contradict a plate
    r = score({"plate_text": "KHULNA METRO KA 99-9999"}, ENTRY)
    assert r.level is None


def test_secondary_colour_and_model_spelling():
    entry = {**ENTRY, "color_secondary": "black"}
    r = score({**GOOD, "plate_text": "DHAKA METRO GA 12-3456", "color": "black", "make_model": "axio"}, entry)
    assert r.level == "confirmed"


def test_config_overrides():
    cfg = merge_config({"weights": {"plate": 0.9, "bogus": 1}, "reid_threshold": 0.5})
    assert cfg["weights"]["plate"] == 0.9 and "bogus" not in cfg["weights"] and cfg["reid_threshold"] == 0.5
    assert DEFAULTS["weights"]["plate"] == 0.55                     # defaults untouched
    assert score({**GOOD, "reid": 0.6}, ENTRY, cfg, lookout=True).level == "candidate"
