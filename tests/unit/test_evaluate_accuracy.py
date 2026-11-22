"""Scoring of the alert-accuracy evaluation (scripts/evaluate_accuracy.py)."""

from scripts.evaluate_accuracy import score_clip, summarize


def _alert(t, type_="CRIMINAL_DETECTED", person="Sadik"):
    return {"t": t, "type": type_, "person": person}


def test_alert_inside_window_detects_event_with_latency():
    ev = [{"type": "CRIMINAL_DETECTED", "person": "Sadik", "start": 2.0, "end": 9.0}]
    r = score_clip(ev, [_alert(3.5), _alert(8.0)])
    assert r["events"][0]["detected"] and r["events"][0]["latency"] == 1.5
    assert all(a["true"] for a in r["alerts"])


def test_late_grace_counts_confirmation_delay_but_not_beyond():
    ev = [{"type": "FALL_SUSPECTED", "start": 5.0, "end": 6.0}]
    assert score_clip(ev, [_alert(8.5, "FALL_SUSPECTED", None)], late=3.0)["events"][0]["detected"]
    r = score_clip(ev, [_alert(9.5, "FALL_SUSPECTED", None)], late=3.0)
    assert not r["events"][0]["detected"] and not r["alerts"][0]["true"]


def test_wrong_person_is_a_false_alert_and_flagged():
    ev = [{"type": "CRIMINAL_DETECTED", "person": "Sadik", "start": 0.0, "end": 10.0}]
    r = score_clip(ev, [_alert(4.0, person="Tarik")])
    assert not r["events"][0]["detected"]
    assert r["alerts"][0]["wrong_identity"] and not r["alerts"][0]["true"]


def test_person_match_ignores_case_and_unlabelled_person_matches_any():
    assert score_clip([{"type": "CRIMINAL_DETECTED", "person": "sadik", "start": 0, "end": 5}],
                      [_alert(1.0, person="Sadik ")])["events"][0]["detected"]
    assert score_clip([{"type": "CRIMINAL_DETECTED", "start": 0, "end": 5}],
                      [_alert(1.0, person="Tarik")])["events"][0]["detected"]


def test_negative_clip_every_alert_is_false():
    r = score_clip([], [_alert(1.0, "WEAPON_DETECTED", None)])
    assert r["alerts"][0]["true"] is False and r["alerts"][0]["wrong_identity"] is False


def test_summarize_recall_precision_and_rate():
    clip_a = score_clip([{"type": "WEAPON_DETECTED", "start": 0, "end": 5},
                         {"type": "WEAPON_DETECTED", "start": 20, "end": 25}],
                        [_alert(2.0, "WEAPON_DETECTED", None)])
    clip_b = score_clip([], [_alert(1.0, "WEAPON_DETECTED", None)])
    s = summarize([clip_a, clip_b], total_seconds=1800)["WEAPON_DETECTED"]
    assert (s["events"], s["detected"], s["recall"]) == (2, 1, 0.5)
    assert (s["alerts"], s["precision"], s["false_alerts"]) == (2, 0.5, 1)
    assert s["false_alerts_per_hour"] == 2.0
    assert s["latency_median_s"] == 2.0


def test_summarize_type_with_only_false_alerts_has_no_recall():
    s = summarize([score_clip([], [_alert(1.0, "FALL_SUSPECTED", None)])], 60)["FALL_SUSPECTED"]
    assert s["recall"] is None and s["precision"] == 0.0
