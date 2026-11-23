"""Let the suite run where dlib's model files are unavailable (stub face_recognition)."""
import os
import sys
import types

# Test-only secrets, so a bare `pytest` works without a .env (CI sets its own).
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci-only-32chars")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-32-chars!!")
os.environ.setdefault("ENCRYPTION_SALT", "test-salt-value")
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key-for-ci")

# Never touch the developer's database: .env may set USE_SQLITE / DATABASE_URL, and load_dotenv
# does not override values already set here. One throwaway SQLite file per test session.
import tempfile  # noqa: E402
_TEST_DB_DIR = tempfile.mkdtemp(prefix="aegis_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_DIR}/test.db"
os.environ["USE_SQLITE"] = "0"
# …and never the real config/cameras.yaml: the API writes cameras it creates into this file.
import shutil  # noqa: E402
_cams = os.path.join(_TEST_DB_DIR, "cameras.yaml")
shutil.copy(os.path.join(os.path.dirname(__file__), "..", "config", "cameras.yaml"), _cams)
os.environ["AEGIS_CAMERAS_YAML"] = _cams
os.environ["AEGIS_UPLOADS_DIR"] = os.path.join(_TEST_DB_DIR, "uploads")
os.environ["AEGIS_DATASETS_DIR"] = os.path.join(_TEST_DB_DIR, "datasets")
os.environ["AEGIS_MODEL_STORE"] = os.path.join(_TEST_DB_DIR, "registry")
os.environ["AEGIS_MODELS_DIR"] = os.path.join(_TEST_DB_DIR, "models_live")

try:
    import face_recognition  # noqa: F401
except BaseException:  # ImportError, RuntimeError (dlib models), or SystemExit (quit())
    sys.modules.pop("face_recognition", None)
    sys.modules["face_recognition"] = types.ModuleType("face_recognition")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _signed_out_clients(request):
    """Login also sets the dashboard's session cookie. A module-level TestClient would carry it
    into the next test and make "requires auth" checks pass, so every test starts signed out."""
    from starlette.testclient import TestClient
    for value in vars(request.module).values():
        if isinstance(value, TestClient):
            value.cookies.clear()
    yield
