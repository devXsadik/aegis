"""Vehicle watchlist scoring (spec 7.5). Pure: no DB, no models — easy to test and tune.

    result = score(read, entry, cfg, night=False, lookout=False)

`read`  — what the camera saw: plate_text, vehicle_type, color, color_secondary, make_model,
          confidences {plate, type, color, model}, reid (cosine similarity to the entry's photos).
`entry` — the watchlist vehicle: plate (any script), vehicle_type, color_primary, color_secondary,
          make_model.

Outcomes (level → alert severity):
  plate exact + attributes agree            → critical  "Confirmed vehicle match"
  plate exact + an attribute disagrees      → high      "Plate matches but vehicle differs — possible fake/swapped plate"
  plate fuzzy + attributes agree            → high      "Probable match"
  plate fuzzy, attributes unknown / differ  → low       "Possible match"
  no plate read + type, colour, model agree + re-ID ≥ threshold
                                            → medium    "Candidate vehicle"  — ONLY inside an active
                                              lookout (BOLO) or targeted search, never nationwide
  otherwise                                 → none

At night / on IR frames colour is unreliable: its weight drops to `night_color_weight` and a
colour disagreement no longer counts as "vehicle differs"."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.analysis import bd_plate

DEFAULTS = {
    "weights": {"plate": 0.55, "type": 0.12, "color": 0.13, "model": 0.12, "reid": 0.08},
    "night_color_weight": 0.03,
    "min_attr_confidence": 0.5,     # below this an attribute counts as "not known"
    "reid_threshold": 0.72,
    "candidate_min_score": 0.30,    # attribute-only score needed for a candidate
    "candidate_requires_model": True,
    "candidate_requires_reid": True,
}

LEVEL_SEVERITY = {"confirmed": "critical", "plate_mismatch": "high", "probable": "high", "possible": "low",
                  "candidate": "medium"}
LABELS = {
    "confirmed": "Confirmed vehicle match",
    "plate_mismatch": "Plate matches but vehicle differs — possible fake/swapped plate",
    "probable": "Probable match",
    "possible": "Possible match",
    "candidate": "Candidate vehicle",
}


@dataclass
class Check:
    attribute: str
    listed: Optional[str]
    seen: Optional[str]
    confidence: Optional[float]
    result: str           # match | mismatch | unknown | unreliable
    weight: float

    def as_dict(self):
        return {"attribute": self.attribute, "listed": self.listed, "seen": self.seen, "confidence": self.confidence,
                "result": self.result, "weight": round(self.weight, 3)}


@dataclass
class MatchResult:
    level: Optional[str]                       # see LABELS, or None
    score: float
    plate: str                                 # exact | fuzzy | none | unread
    checks: List[Check] = field(default_factory=list)
    suppressed: Optional[str] = None           # why a candidate was not raised

    @property
    def severity(self) -> Optional[str]:
        return LEVEL_SEVERITY.get(self.level) if self.level else None

    @property
    def label(self) -> Optional[str]:
        return LABELS.get(self.level) if self.level else None

    def as_dict(self) -> dict:
        return {"level": self.level, "label": self.label, "severity": self.severity, "score": round(self.score, 3),
                "plate": self.plate, "checks": [c.as_dict() for c in self.checks], "suppressed": self.suppressed}


def merge_config(overrides: Optional[dict]) -> dict:
    cfg = {**DEFAULTS, "weights": dict(DEFAULTS["weights"])}
    for k, v in (overrides or {}).items():
        if k == "weights" and isinstance(v, dict):
            cfg["weights"].update({wk: float(wv) for wk, wv in v.items() if wk in cfg["weights"]})
        elif k in cfg:
            cfg[k] = type(DEFAULTS[k])(v)
    return cfg


def _model_eq(listed: str, seen: str) -> bool:
    """'toyota_axio' vs 'Toyota Axio' vs 'axio': normalise and allow model-only reads."""
    a = listed.lower().replace("_", " ").replace("-", " ").split()
    b = seen.lower().replace("_", " ").replace("-", " ").split()
    return a == b or (len(b) >= 1 and b[-1] == a[-1] and (len(b) == 1 or b[0] == a[0]))


def _attr(name, listed, seen, conf, weight, min_conf, eq=None, unreliable=False) -> Check:
    if not listed or not seen or seen in ("unknown", "other"):
        return Check(name, listed, seen, conf, "unknown", weight)
    if conf is not None and conf < min_conf:
        return Check(name, listed, seen, conf, "unknown", weight)
    same = eq(listed, seen) if eq else listed == seen
    if unreliable:
        return Check(name, listed, seen, conf, "match" if same else "unreliable", weight)
    return Check(name, listed, seen, conf, "match" if same else "mismatch", weight)


def score(read: dict, entry: dict, cfg: Optional[dict] = None, *, night: bool = False,
          lookout: bool = False) -> MatchResult:
    cfg = cfg or merge_config(None)
    w = dict(cfg["weights"])
    if night:
        w["color"] = cfg["night_color_weight"]
    conf = read.get("confidences") or {}
    mc = cfg["min_attr_confidence"]

    # ——— plate ———
    listed_plate, seen_plate = entry.get("plate"), read.get("plate_text")
    if not seen_plate or not bd_plate.parse(seen_plate):
        plate = "unread"
    elif not listed_plate:
        plate = "none"
    else:
        plate = bd_plate.compare(seen_plate, listed_plate)
    if plate == "exact" and conf.get("plate") is not None and conf["plate"] < mc:
        plate = "fuzzy"                                  # a shaky read is not proof

    # ——— attributes ———
    color_seen = read.get("color")
    checks = [
        _attr("type", entry.get("vehicle_type"), read.get("vehicle_type"), conf.get("type"), w["type"], mc),
        _attr("color", entry.get("color_primary"), color_seen, conf.get("color"), w["color"], mc,
              eq=lambda a, b: a == b or b == entry.get("color_secondary"), unreliable=night),
        _attr("model", entry.get("make_model"), read.get("make_model"), conf.get("model"), w["model"], mc, eq=_model_eq),
    ]
    reid = read.get("reid")
    if reid is not None:
        ok = reid >= cfg["reid_threshold"]
        checks.append(Check("reid", None, f"{reid:.2f}", reid, "match" if ok else "mismatch", w["reid"]))

    known = [c for c in checks if c.result in ("match", "mismatch") and c.attribute != "reid"]
    mismatched = [c for c in known if c.result == "mismatch"]
    agree = bool(known) and not mismatched
    attr_score = sum(c.weight for c in checks if c.result == "match")
    plate_score = {"exact": w["plate"], "fuzzy": w["plate"] * 0.6}.get(plate, 0.0)
    total = plate_score + attr_score

    if plate == "exact":
        level = "plate_mismatch" if mismatched else "confirmed"
    elif plate == "fuzzy":
        level = "probable" if agree else "possible"
    else:
        level, suppressed = _candidate(checks, attr_score, cfg, lookout, entry)
        return MatchResult(level, total, plate, checks, suppressed)
    return MatchResult(level, total, plate, checks)


def _candidate(checks: List[Check], attr_score: float, cfg: dict, lookout: bool, entry: dict):
    by = {c.attribute: c for c in checks}
    need = ["type", "color"] + (["model"] if cfg["candidate_requires_model"] and entry.get("make_model") else [])
    if not all(by[a].result == "match" for a in need):
        return None, None
    if cfg["candidate_requires_reid"] and not (by.get("reid") and by["reid"].result == "match"):
        return None, "re-ID similarity missing or below threshold"
    if attr_score < cfg["candidate_min_score"]:
        return None, "attribute score below candidate threshold"
    if not lookout:
        return None, "attribute-only match outside an active lookout area"
    return "candidate", None


def explain(result: MatchResult) -> Dict[str, str]:
    """✓ / ✗ / ? per attribute for the alert card."""
    sym = {"match": "✓", "mismatch": "✗", "unknown": "?", "unreliable": "~"}
    return {c.attribute: sym[c.result] for c in result.checks}
