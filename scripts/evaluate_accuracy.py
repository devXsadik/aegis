#!/usr/bin/env python3
"""
Alert accuracy on labelled clips: recall, precision, false alerts/hour, time to detect, FPS.

Each clip is replayed the way a live camera is processed: frames are taken at video speed,
inference runs on the newest frame whenever it is free (at most `target_fps`), and a slow
frame makes the next ones drop. So the alerts and their timing are what an operator would
get. Alerts are captured in-process: nothing reaches the backend, the DB or the speaker.
A live camera also decodes, records and streams, so real FPS is a little lower than here.

Labels: data/eval/clips/manifest.yaml (see data/eval/clips/manifest.example.yaml)

    clips:
      - file: gate_sadik_walks_in.mp4
        events:                         # what should raise an alert, in clip seconds
          - {type: CRIMINAL_DETECTED, person: Sadik, start: 2.0, end: 9.5}
      - file: corridor_empty.mp4
        events: []                      # negative clip: every alert is a false alert

An alert counts for an event when it has the same type (and person, if the label names one)
and is raised between `start - early` and `end + late` (defaults 0.5 s and 3 s: confirmation
takes a few frames). Any other alert is a false alert.

Usage:
    python scripts/evaluate_accuracy.py
    python scripts/evaluate_accuracy.py --clips gate_sadik_walks_in.mp4 --late 5
"""

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CLIPS_DIR = ROOT / "data" / "eval" / "clips"


# ---------------------------------------------------------------------------
# Scoring (pure: unit-tested in tests/unit/test_evaluate_accuracy.py)
# ---------------------------------------------------------------------------
def _same_person(label, alert_person) -> bool:
    return not label or (alert_person or "").strip().lower() == str(label).strip().lower()


def score_clip(events: list, alerts: list, early: float = 0.5, late: float = 3.0) -> dict:
    """Match one clip's alerts ({t, type, person}) to its labelled events ({type, person?, start, end})."""
    matched_events = []
    for ev in events:
        hits = [a["t"] for a in alerts
                if a["type"] == ev["type"] and _same_person(ev.get("person"), a.get("person"))
                and ev["start"] - early <= a["t"] <= ev["end"] + late]
        matched_events.append({**ev, "detected": bool(hits),
                               "latency": max(0.0, min(hits) - ev["start"]) if hits else None})

    scored_alerts = []
    for a in alerts:
        windows = [ev for ev in events if a["type"] == ev["type"]
                   and ev["start"] - early <= a["t"] <= ev["end"] + late]
        true = any(_same_person(ev.get("person"), a.get("person")) for ev in windows)
        # Right moment, wrong name: the worst kind of false alert for a watchlist system.
        wrong_identity = bool(windows) and not true and a["type"] == "CRIMINAL_DETECTED"
        scored_alerts.append({**a, "true": true, "wrong_identity": wrong_identity})
    return {"events": matched_events, "alerts": scored_alerts}


def summarize(clip_results: list, total_seconds: float) -> dict:
    """Per alert type: recall over events, precision over alerts, false alerts per hour, latency."""
    types = sorted({e["type"] for c in clip_results for e in c["events"]}
                   | {a["type"] for c in clip_results for a in c["alerts"]})
    hours = max(total_seconds, 1e-9) / 3600
    out = {}
    for t in types:
        evs = [e for c in clip_results for e in c["events"] if e["type"] == t]
        als = [a for c in clip_results for a in c["alerts"] if a["type"] == t]
        detected = [e for e in evs if e["detected"]]
        true_alerts = sum(a["true"] for a in als)
        lat = sorted(e["latency"] for e in detected)
        out[t] = {
            "events": len(evs),
            "detected": len(detected),
            "recall": round(len(detected) / len(evs), 3) if evs else None,
            "alerts": len(als),
            "precision": round(true_alerts / len(als), 3) if als else None,
            "false_alerts": len(als) - true_alerts,
            "wrong_identity": sum(a["wrong_identity"] for a in als),
            "false_alerts_per_hour": round((len(als) - true_alerts) / hours, 1),
            "latency_median_s": round(statistics.median(lat), 2) if lat else None,
            "latency_max_s": round(lat[-1], 2) if lat else None,
        }
    return out


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
class _Recorder:
    """Stands in for dispatch_alert: keeps (clip time, type, person) instead of posting."""

    def __init__(self):
        self.now = 0.0
        self.alerts = []

    def __call__(self, alert_type, severity="critical", person_name=None, confidence=None, **_):
        self.alerts.append({"t": round(self.now, 2), "type": alert_type, "severity": severity,
                            "person": person_name, "confidence": confidence})


def _quiet_pipeline(cfg, recorder):
    """A pipeline whose side effects (backend posts, evidence rows, alarm sound, captures) are off."""
    import core.pipeline.stages.output as output_mod
    import core.tracking.cross_camera as xcam
    import utils.alerts.notification_hub as hub_mod
    from core.app.factory import build_pipeline

    hub_mod.dispatch_alert = recorder
    output_mod.save_evidence_db = lambda *a, **k: None
    output_mod.publish_vehicle_detection = lambda *a, **k: None
    xcam._shared = None             # red subjects from the previous clip must not carry over

    pipeline, _, location = build_pipeline(cfg, str(ROOT))
    for stage in pipeline.stages:
        if isinstance(stage, output_mod.OutputStage):
            stage.notifications.alarm_callback = None
            stage.capturer.capture = lambda *a, **k: None
    return pipeline, location


def replay(path: Path, cfg: dict, clip_id: str) -> dict:
    import cv2

    recorder = _Recorder()
    pipeline, location = _quiet_pipeline(cfg, recorder)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    min_gap = 1.0 / float(cfg.get("target_fps", 8))

    pos = 0                 # index of the next frame cap.read() returns
    infer_ms = []
    start = time.perf_counter()
    next_at = 0.0
    while True:
        clip_t = time.perf_counter() - start
        if clip_t < next_at:
            time.sleep(next_at - clip_t)
            clip_t = next_at
        want = int(clip_t * src_fps)        # the newest frame a live camera would have now
        if n_frames and want >= n_frames:
            break
        while pos < want and cap.grab():
            pos += 1
        ok, frame = cap.read()
        if not ok:
            break
        pos += 1
        recorder.now = (pos - 1) / src_fps
        t0 = time.perf_counter()
        pipeline.run(frame, camera_id=f"eval_{clip_id}", camera_location=location)
        infer_ms.append((time.perf_counter() - t0) * 1000)
        next_at = clip_t + min_gap
    cap.release()
    duration = n_frames / src_fps if n_frames else time.perf_counter() - start
    return {
        "duration_s": round(duration, 2),
        "frames_inferred": len(infer_ms),
        "inference_fps": round(len(infer_ms) / max(duration, 1e-9), 2),
        "infer_ms_median": round(statistics.median(infer_ms), 1) if infer_ms else None,
        "infer_ms_p90": round(sorted(infer_ms)[int(0.9 * (len(infer_ms) - 1))], 1) if infer_ms else None,
        "alerts": recorder.alerts,
        "stages": pipeline.get_stats()["stages"],
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _machine() -> dict:
    info = {"platform": platform.platform(), "python": platform.python_version(),
            "processor": platform.processor() or platform.machine()}
    try:
        from core.detectors.device import resolve_device
        info["device"] = resolve_device("auto")
    except Exception:
        pass
    if sys.platform == "darwin":
        try:
            first = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5).stdout
            info["power"] = "AC" if "AC Power" in first else "battery"
        except Exception:
            pass
    return info


def _fmt(v, pct=False):
    if v is None:
        return "–"
    return f"{v:.0%}" if pct else str(v)


def to_markdown(report: dict) -> str:
    m = report["machine"]
    lines = [
        f"# Alert accuracy — {report['run_at']}",
        "",
        f"{len(report['clips'])} clips, {report['total_seconds'] / 60:.1f} min of video. "
        f"Machine: {m.get('processor')}, {m.get('device', '?')}, power {m.get('power', '?')}. "
        f"Match window: start − {report['early']} s … end + {report['late']} s.",
        "",
        "| Alert type | Events | Detected | Recall | Alerts | Precision | False | Wrong ID | False/h | Time to detect (median / max) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for t, s in report["summary"].items():
        lat = f"{_fmt(s['latency_median_s'])} s / {_fmt(s['latency_max_s'])} s" if s["latency_median_s"] is not None else "–"
        lines.append(f"| {t} | {s['events']} | {s['detected']} | {_fmt(s['recall'], True)} | {s['alerts']} "
                     f"| {_fmt(s['precision'], True)} | {s['false_alerts']} | {s['wrong_identity']} "
                     f"| {s['false_alerts_per_hour']} | {lat} |")
    lines += ["", "| Clip | Length | Inference FPS | ms (median / p90) | Events detected | False alerts |",
              "|---|---:|---:|---|---:|---:|"]
    for c in report["clips"]:
        det = sum(e["detected"] for e in c["events"])
        false = sum(not a["true"] for a in c["alerts"])
        lines.append(f"| {c['file']} | {c['duration_s']} s | {c['inference_fps']} "
                     f"| {_fmt(c['infer_ms_median'])} / {_fmt(c['infer_ms_p90'])} "
                     f"| {det}/{len(c['events'])} | {false} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(CLIPS_DIR / "manifest.yaml"))
    ap.add_argument("--clips", nargs="*", help="only these files from the manifest")
    ap.add_argument("--early", type=float, default=0.5, help="seconds before an event an alert still counts")
    ap.add_argument("--late", type=float, default=3.0, help="seconds after an event an alert still counts")
    ap.add_argument("--out", help="results folder (default data/results)")
    args = ap.parse_args()

    import yaml
    from paths import CONFIG_YAML, RESULTS_DIR
    from utils.config import expand_env, load_yaml

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        sys.exit(f"No manifest at {manifest_path}. Copy data/eval/clips/manifest.example.yaml and label your clips.")
    clips = yaml.safe_load(manifest_path.read_text()).get("clips") or []
    if args.clips:
        clips = [c for c in clips if c["file"] in set(args.clips)]
    if not clips:
        sys.exit("No clips to evaluate.")
    cfg = expand_env(load_yaml(str(CONFIG_YAML)))

    results = []
    for i, clip in enumerate(clips):
        path = manifest_path.parent / clip["file"]
        print(f"[{i + 1}/{len(clips)}] {clip['file']} …", flush=True)
        run = replay(path, cfg, clip_id=str(i))
        scored = score_clip(clip.get("events") or [], run["alerts"], args.early, args.late)
        results.append({"file": clip["file"], **{k: v for k, v in run.items() if k != "alerts"}, **scored})
        det = sum(e["detected"] for e in scored["events"])
        false = sum(not a["true"] for a in scored["alerts"])
        print(f"    {det}/{len(scored['events'])} events detected, {false} false alerts, "
              f"{run['inference_fps']} inference FPS", flush=True)

    total = sum(c["duration_s"] for c in results)
    report = {
        "run_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "manifest": str(manifest_path),
        "early": args.early, "late": args.late,
        "config": {k: cfg.get(k) for k in ("target_fps", "confidence_threshold", "weapon_conf_threshold",
                                           "face_tolerance", "rerecognize_every")},
        "machine": _machine(),
        "total_seconds": round(total, 1),
        "summary": summarize(results, total),
        "clips": results,
    }
    out_dir = Path(args.out) if args.out else RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"accuracy_{datetime.now():%Y%m%d_%H%M}"
    stem.with_suffix(".json").write_text(json.dumps(report, indent=1, default=str))
    md = to_markdown(report)
    stem.with_suffix(".md").write_text(md)
    print("\n" + md)
    print(f"Saved {stem}.json and .md")
    if report["machine"].get("power") == "battery":
        print("Note: on battery the Mac throttles; FPS numbers are only comparable on AC power.")
    sys.stdout.flush()
    os._exit(0)     # face worker subprocesses and daemon threads must not keep the script alive


if __name__ == "__main__":
    main()
