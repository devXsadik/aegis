#!/usr/bin/env bash
# Usage: entrypoint.sh api | pipeline | <any command>
set -euo pipefail
cd /app

# Docker / Kubernetes secrets: FOO_FILE=/run/secrets/foo sets FOO from that file, so secrets need
# not sit in .env or the container's environment listing.
for var in SECRET_KEY ENCRYPTION_KEY ENCRYPTION_SALT INTERNAL_API_KEY POSTGRES_PASSWORD DATABASE_URL \
           ADMIN_PASSWORD S3_ACCESS_KEY S3_SECRET_KEY SENTRY_DSN METRICS_TOKEN SMS_WEBHOOK; do
  file_var="${var}_FILE"
  if [ -n "${!file_var:-}" ]; then
    [ -r "${!file_var}" ] || { echo "[entrypoint] ERROR: $file_var=${!file_var} not readable" >&2; exit 1; }
    export "$var"="$(cat "${!file_var}")"
    unset "$file_var"
  fi
done

# Started as root so the app can run as whoever owns the mounted config/. On a Linux host
# that is the user who cloned the repo, whatever their uid: the dashboard can then write
# cameras.yaml and the file stays theirs. Docker Desktop (macOS/Windows) and rootless
# Docker report root as the owner: use `aegis` there, unless it cannot write the mount
# (rootless), where container root is already the unprivileged host user.
if [ "$(id -u)" = 0 ]; then
  uid="$(stat -c %u config)"; gid="$(stat -c %g config)"
  if [ "$uid" = 0 ]; then
    uid=1000; gid=1000
    setpriv --reuid 1000 --regid 1000 --clear-groups test -w config || uid=0
  fi
  if [ "$uid" != 0 ]; then
    chown "$uid:$gid" . data
    # models/ is here for the case where Docker created the missing host folder as root.
    for d in data/recordings data/results evidence logs utils/logs models "$HOME"; do
      [ "$(stat -c %u "$d")" = "$uid" ] || chown -R "$uid:$gid" "$d"
    done
    exec setpriv --reuid "$uid" --regid "$gid" --clear-groups "$0" "$@"
  fi
fi

role="${1:-api}"

wait_for_db() {
  echo "[entrypoint] waiting for the database…"
  for _ in $(seq 1 45); do
    if python - <<'PY' 2>/dev/null
from backend.db.database import engine
with engine.connect():
    pass
PY
    then echo "[entrypoint] database ready"; return 0; fi
    sleep 2
  done
  echo "[entrypoint] ERROR: database not reachable" >&2; return 1
}

case "$role" in
  api)
    wait_for_db
    python scripts/db_upgrade.py          # create/upgrade schema (Alembic-aware)
    python scripts/bootstrap_admin.py     # first start only: creates the admin account
    # Several workers need Redis (REDIS_URL): live state is shared there (backend/services/cluster.py).
    workers="${API_WORKERS:-1}"
    if [ "$workers" != "1" ] && [ -z "${REDIS_URL:-}" ]; then
      echo "[entrypoint] API_WORKERS=$workers needs REDIS_URL; starting 1 worker" >&2; workers=1
    fi
    exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers "$workers" --proxy-headers
    ;;
  pipeline)
    wait_for_db
    echo "[entrypoint] waiting for the API…"
    until curl -sf "${BACKEND_URL:-http://backend:8000}/health" >/dev/null; do sleep 3; done
    # Small ONNX models (face detector, gender/age, ST-GCN actions) into the mounted models/. Best effort.
    python - <<'PY' || true
from scripts.ensure_local_env import ensure_action_model, ensure_attribute_model, ensure_face_model
ensure_face_model()
ensure_attribute_model()
ensure_action_model()
PY
    # Optional single-file source (set PIPELINE_VIDEO=data/demo/clips/foo.mp4).
    # Default: multi-camera from config/cameras.yaml (webcam indexes use LOCAL_CAMERA_URL).
    if [ -n "${PIPELINE_VIDEO:-}" ]; then
      echo "[entrypoint] pipeline video → ${PIPELINE_VIDEO}"
      exec python main.py --video "${PIPELINE_VIDEO}" --no-display
    fi
    exec python main.py --multi --no-display
    ;;
  *)
    exec "$@"
    ;;
esac
