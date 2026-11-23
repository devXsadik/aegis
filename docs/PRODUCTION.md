# Running Aegis in production

What a real deployment needs beyond `docker compose up`. On start-up, with
`ENVIRONMENT=production`, the API logs a line per missing item ("Production check: …"), and admins
see the same list in `GET /api/v1/system/status` (`production_checks`).

## 1. Shape

```
             HTTPS (Caddy, --profile https)
                         │
                 web (nginx, dashboard)
                         │
      ┌──── API workers × API_WORKERS (one or more machines) ────┐
      │  shared through Redis: WebSocket fan-out, camera          │
      │  heartbeats, live frames, rate limits, one leader for     │
      │  background jobs (escalation, maintenance, tracking)      │
      └───────────────────────────────────────────────────────────┘
          │              │                 │
      PostgreSQL       Redis        S3 / MinIO (evidence, write-once;
      (+ standby)                    off-site backups)
          │
      pipeline / GPU workers (cameras), scripts/worker.py (queued ingest)
```

* `API_WORKERS=4` (or more machines behind a load balancer) needs `REDIS_URL`; without it the
  entrypoint falls back to one worker. Code: `backend/services/cluster.py`.
* Start-up work (schema upgrade, camera seeding) runs one worker at a time under a Redis lock.
* PostgreSQL: run a streaming-replication standby (or a managed database). SQLite is for one
  laptop only.

## 2. HTTPS

```sh
DOMAIN=aegis.example.gov.bd   # in .env; a public DNS name gets a Let's Encrypt certificate
COOKIE_SECURE=true            # default when ENVIRONMENT=production
CORS_ORIGINS=https://aegis.example.gov.bd
docker compose --profile https up -d
```

`docker/Caddyfile` adds HSTS and the usual security headers. Phone alerts (Web Push) and the
officer's location only work over HTTPS.

## 3. Evidence and backups off the server

```sh
docker compose --profile storage up -d          # MinIO + buckets (evidence with Object Lock)
EVIDENCE_STORE=s3
S3_ENDPOINT_URL=http://minio:9000
S3_BUCKET=aegis-evidence
S3_ACCESS_KEY=… S3_SECRET_KEY=…
S3_OBJECT_LOCK_DAYS=3650                        # nobody can delete or change a file for 10 years
BACKUP_S3_BUCKET=aegis-backups                  # the nightly backup is also copied here
```

Files are encrypted (AES-GCM, `ENCRYPTION_KEY`) before they leave the API, so the storage only sees
ciphertext. Off-site backups are sealed the same way: restore with
`python -m backend.services.backup unseal <file> > backup.tar.gz`. Keep `ENCRYPTION_KEY` and
`ENCRYPTION_SALT` in a safe separate from the backups: without them nothing can be restored.
Put MinIO on other disks / machines (or use a provider): a copy on the same disk is not a backup.

## 4. Secrets

Any secret can come from a file: `SECRET_KEY_FILE=/run/secrets/secret_key` (Docker / Kubernetes
secrets; `docker/entrypoint.sh` reads them). Rotate `INTERNAL_API_KEY` and camera tokens when staff
change; `SECRET_KEY` rotation signs everyone out.

## 5. Monitoring

* `SENTRY_DSN` — error reports with stack traces only: request bodies, cookies, query strings,
  user details and local variables are removed before sending (`backend/observability.py`).
* `LOG_FORMAT=json` — one JSON object per line with `request_id` (also in the `X-Request-ID`
  response header), for Loki / ELK / CloudWatch.
* Prometheus: `GET /api/v1/metrics` with `Authorization: Bearer $METRICS_TOKEN` — request rate,
  latency histogram per route, in-flight requests, camera FPS and heartbeat age, alerts by type.
  Scrape every API worker. Alert on: `aegis_pipeline_online == 0`, heartbeat age > 120 s, 5xx rate,
  p95 latency.
* An external uptime check on `https://…/health` (not from the same machine).

## 6. Security checks

CI runs `pip-audit`, `bandit`, `npm audit`, `gitleaks` and a Trivy image scan on every push
(`.github/workflows/ci.yml`). Before go-live: an external penetration test, `MFA_REQUIRED=true`,
`ADMIN_IP_ALLOWLIST` for admin accounts, and a restore drill from an off-site backup.

## 7. Capacity

`docs/LOAD_TEST.md` has the plan and the first numbers (one laptop). Run tests 2–7 there on the
target servers before connecting more than a pilot's worth of cameras.

## 8. Not software (yours to arrange)

* A legal basis and data-protection impact assessment for face and plate matching; retention
  periods approved by an oversight body.
* Accuracy measured on your own cameras (`scripts/evaluate_accuracy.py`, labelled clips in
  `data/eval/clips/`), including face matching across age, gender and skin tone, before
  identification alerts are used operationally.
* Trained models for your footage: weapon detector, plate detector + Bangla plate reader,
  vehicle types / colours (`training/README.md`), optionally an ArcFace-class face model.
* Data-sharing agreements before connecting the vehicle registry (`VEHICLE_REGISTRY_URL`),
  999 / CAD (`CAD_WEBHOOK`) or SMS (`SMS_WEBHOOK`).
