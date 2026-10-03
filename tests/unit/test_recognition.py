import numpy as np

from core.recognition.face_recognizer_db import FaceRecognizerDB
from core.recognition.voting import IdentityVoter


def test_voter_needs_agreement():
    v = IdentityVoter(window=4, min_votes=2)
    v.add(1, "A")
    assert v.confirmed(1) is None
    v.add(1, "B")
    assert v.confirmed(1) is None
    v.add(1, "A")
    assert v.confirmed(1) == "A"
    v.add(1, None)                       # failed reads never count
    v.prune(set())
    assert v.confirmed(1) is None


def test_match_rejects_far_and_ambiguous():
    r = FaceRecognizerDB(tolerance=0.45, min_margin=0.04)
    assert r.match(np.array([0.6]), ["A"]) is None                       # beyond tolerance
    assert r.match(np.array([0.30, 0.32]), ["A", "B"]) is None           # too close to call
    name, dist, margin = r.match(np.array([0.30, 0.50, 0.31]), ["A", "B", "A"])
    assert name == "A" and margin > 0.15                                 # same person ≠ rival


def test_cache_refreshes_after_ttl(monkeypatch):
    calls = []
    r = FaceRecognizerDB(loader=lambda: calls.append(1) or ([], []), cache_ttl=60)
    r._load_encodings(); r._load_encodings()
    assert len(calls) == 1
    r._loaded_at -= 61
    r._load_encodings()
    assert len(calls) == 2
