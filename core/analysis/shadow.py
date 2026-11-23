"""Shadow runs: a candidate model answers every live request next to production, but only the
production answer is used. Agreement per head (and the candidate's confidence) is counted here so
the registry can show "the new model agrees 91 % with production on type, 76 % on colour" from
real cameras before anyone promotes it. Counts live in this process and reset on restart."""

from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_stats: dict = defaultdict(lambda: {"samples": 0, "heads": defaultdict(lambda: {"agree": 0, "n": 0, "conf_sum": 0.0}),
                                    "examples": []})
MAX_EXAMPLES = 20


def record(task: str, live: dict, cand: dict, keys=("vehicle_type", "color", "make_model")) -> None:
    with _lock:
        s = _stats[task]
        s["samples"] += 1
        diffs = {}
        for k in keys:
            if cand.get(k) is None:
                continue
            h = s["heads"][k]
            h["n"] += 1
            same = live.get(k) == cand.get(k)
            h["agree"] += int(same)
            h["conf_sum"] += float((cand.get("confidences") or {}).get({"vehicle_type": "type", "make_model": "model"}.get(k, k), 0.0))
            if not same:
                diffs[k] = {"production": live.get(k), "shadow": cand.get(k)}
        if diffs:
            s["examples"] = ([{"diff": diffs}] + s["examples"])[:MAX_EXAMPLES]


def summary(task: str) -> dict:
    with _lock:
        s = _stats.get(task)
        if not s:
            return {"samples": 0, "heads": {}, "examples": []}
        return {"samples": s["samples"],
                "heads": {k: {"agreement": round(h["agree"] / h["n"], 3) if h["n"] else None, "n": h["n"],
                              "mean_confidence": round(h["conf_sum"] / h["n"], 3) if h["n"] else None}
                          for k, h in s["heads"].items()},
                "examples": list(s["examples"])}


def reset(task: str) -> None:
    with _lock:
        _stats.pop(task, None)


def reload() -> None:
    """Forget cached shadow nets (a new one was installed or removed)."""
    try:
        from core.analysis import vehicle_attrs
        vehicle_attrs._shadow_net.cache_clear()
        vehicle_attrs._attr_labels.cache_clear()
    except Exception:
        pass
