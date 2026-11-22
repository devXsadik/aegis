# Running Aegis

What runs by itself, how to back up and restore, and how to put the dashboard behind HTTPS.

## What runs by itself (in the API process)

| Job | When | What |
|---|---|---|
| Maintenance | nightly, `MAINTENANCE_HOUR` (default 3 = 03:00 local) | delete recordings older than `DVR_RETENTION_HOURS` (48), capture stills older than `CAPTURE_RETENTION_DAYS` (7), purge evidence images older than `retention.evidence_days` (90, `config.yaml`), then back up |
| Health watch | every 30 s | a switched-on camera silent for `DETECTION_DOWN_SECONDS` (120) → `CAMERA_OFFLINE`; all silent → `DETECTION_DOWN` (critical). Both go to the security webhook and the dashboard; a `…_RESTORED` notice follows. Paused/stopped cameras never count |
| Escalation | every 30 s | unacknowledged watchlist/weapon alerts page backup officers after `ESCALATE_AFTER_SECONDS` (120) |

Evidence retention keeps the evidence record and its custody chain (a `PURGED` entry is added);
only the images go. Evidence attached to an open or investigating incident is kept whole.

## Backups

The database holds users, cameras, alerts, incidents, the shift log, face records and the
evidence and capture images, so one consistent copy of it is most of a backup. Each backup is a
folder in `data/backups/` (`BACKUP_DIR`):

```
20261123_0300/
  aegis.db  or  aegis.sql.gz   SQLite online copy, or pg_dump of PostgreSQL (needs the pg_dump client)
  config/                      config.yaml, cameras.yaml, models.yaml
  recordings/                  only with BACKUP_RECORDINGS=true
  backup.json                  contents, size, SHA-256 of the database copy
```

The newest `BACKUP_KEEP` (7) are kept. Admins see them and can back up now under
**Settings → Backups and clean-up** (`POST /api/v1/system/backups`). `BACKUP_ENABLED=false` turns
the nightly backup off. **Copy backups off this machine** (another disk, a NAS, cloud storage):
a backup on the same disk does not survive the disk.

### Restore

Stop the system first (`make stop`, or `docker compose down`).

- **SQLite** (local runs): check the copy, then put it in place.
  ```sh
  shasum -a 256 data/backups/20261123_0300/aegis.db    # must match database_sha256 in backup.json
  cp data/ai_sss.db data/ai_sss.before-restore.db       # keep the current one, just in case
  cp data/backups/20261123_0300/aegis.db data/ai_sss.db
  cp data/backups/20261123_0300/config/*.yaml config/
  ```
- **PostgreSQL**: restore into an empty database.
  ```sh
  gunzip -c data/backups/20261123_0300/aegis.sql.gz | psql "$DATABASE_URL"
  ```

Start again; `scripts/db_upgrade.py` (run by Docker and `setup.sh`) brings an older backup's
schema up to date.

## Encryption at rest — keep the key

Evidence stills, capture stills and enrolment photos are stored AES-GCM encrypted
(`ENCRYPT_AT_REST=true`, default), with the key derived from `ENCRYPTION_KEY` and
`ENCRYPTION_SALT` in `.env`. **If those two values are lost, the images cannot be read again**,
including from backups. Keep a copy of them somewhere safe and separate from the backups.
Images stored before encryption was on: `python scripts/encrypt_existing.py --dry-run`, then
without `--dry-run` (back up first).

## HTTPS

Run the dashboard behind a reverse proxy that holds the certificate; the Docker stack's nginx
already serves the dashboard and proxies `/api` (including WebSockets) to the backend.

1. Point a DNS name at the server, e.g. `aegis.example.org`.
2. Put a TLS-terminating proxy in front of port 8080. With [Caddy](https://caddyserver.com) the whole
   config is (certificate obtained and renewed automatically):
   ```
   aegis.example.org {
       reverse_proxy 127.0.0.1:8080
   }
   ```
   With nginx, a server block with `ssl_certificate` / `ssl_certificate_key` and
   ```nginx
   location / {
       proxy_pass http://127.0.0.1:8080;
       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;      # WebSockets (live alerts, status)
       proxy_set_header Connection "upgrade";
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-Proto https;
   }
   ```
3. In `.env`: `COOKIE_SECURE=true` (the session cookie is then only sent over HTTPS) and
   `CORS_ORIGINS=https://aegis.example.org`. Restart.
4. Do not publish ports 8000 (API) or 5432 (database) to the network; only the proxy's 443.

## PostgreSQL for local runs

SQLite is fine for a demo; with several cameras and the API writing at once it locks.

```sh
make db-up                               # PostgreSQL in Docker, on 127.0.0.1:5432 only
# .env: USE_SQLITE=false
#       DATABASE_URL=postgresql://aegis:<POSTGRES_PASSWORD>@localhost:5432/aegis
make db-copy                             # copy the existing SQLite data across (once)
./run.sh
```
