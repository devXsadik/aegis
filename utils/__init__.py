import importlib

__all__ = [
    "logger", "save_evidence_db", "FrameSkipper", "ResourceMonitor", "ReportGenerator",
]

_modules = {
    "logger": "utils.system",
    "FrameSkipper": "utils.system",
    "ResourceMonitor": "utils.system",
    "save_evidence_db": "utils.data",
    "ReportGenerator": "utils.data",
}


def __getattr__(name):
    if name in _modules:
        return getattr(importlib.import_module(_modules[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
