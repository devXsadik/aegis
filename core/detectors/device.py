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


def configure_inference_threads(device: str) -> int:
    """Cap torch/OpenCV CPU threads.

    torch defaults to every core. With several camera threads, a browser, Docker's VM and
    the DB all competing, that oversubscribes the CPU: measured on this project, one
    YOLOv8s pass took 557 ms with 1 thread and 836 ms with 8. Not applied to GPUs.
    Override with TORCH_THREADS.
    """
    import os
    if str(device).startswith(("cuda", "mps")):
        return 0
    n = int(os.getenv("TORCH_THREADS", "") or max(1, min(2, (os.cpu_count() or 2) // 2)))
    try:
        import torch
        torch.set_num_threads(n)
        import cv2
        cv2.setNumThreads(n)
    except Exception:
        pass
    return n
