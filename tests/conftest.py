"""Let the suite run where dlib's model files are unavailable (stub face_recognition)."""
import sys
import types

try:
    import face_recognition  # noqa: F401
except Exception:  # ImportError, or RuntimeError when dlib models can't be opened
    sys.modules.pop("face_recognition", None)
    sys.modules["face_recognition"] = types.ModuleType("face_recognition")
