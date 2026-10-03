"""Inference device selection."""

_cached = None


def resolve_device(pref: str = "auto") -> str:
    """'auto' → cuda:0 if available, else mps, else cpu. Explicit values pass through."""
    global _cached
    if pref and pref != "auto":
        return pref
    if _cached is None:
        try:
            import torch
            if torch.cuda.is_available():
                _cached = "cuda:0"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                _cached = "mps"
            else:
                _cached = "cpu"
        except Exception:
            _cached = "cpu"
    return _cached
