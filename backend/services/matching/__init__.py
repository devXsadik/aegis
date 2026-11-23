"""Matchers registered with the event router. Importing this package registers them all.

vehicle.py — plate + attributes + re-ID against the vehicle watchlist and active lookouts (Phase 7)
face.py    — face embeddings against the person watchlist (Phase 8)"""

from backend.services.matching import vehicle  # noqa: E402,F401  (registers the vehicle matcher)
