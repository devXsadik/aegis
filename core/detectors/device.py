"""Inference device selection."""

import threading

_cached = None

# Apple's Metal driver aborts the whole process ("A command encoder is already encoding
# to this command buffer") if two threads encode GPU work at once — even for different
# models. So every model on the MPS device must share ONE lock. Other devices only need
# a per-model lock because a single model instance is not thread-safe.
_MPS_LOCK = threading.RLock()


def lock_for(device: str):
    """Lock a model must hold while running inference on `device`."""
    return _MPS_LOCK if str(device).startswith("mps") else threading.Lock()


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
