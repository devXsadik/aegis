# Aegis — what to improve next

Review date: 2026-11-23, after the UX rework and the feature rounds in `UX_REVIEW.md`.
State: 313 backend tests (72 % coverage), 16 frontend unit tests, 1 browser smoke test, lint clean.

## Cleanup done in this review

| Removed / changed | Why |
|---|---|
| `backend/init_db.py`, `backend/migrate.py` | Duplicates: `setup.sh` now calls `scripts/db_upgrade.py` (same as Docker, Alembic-aware) and `scripts/ingest_watchlist.py` directly |
| `frontend/src/components/CameraMapOverview.jsx` | Not used by any page |
| 8 functions in `services/api.js` | Never called (fetchFaceEncodings, fetchIncident, fetchRecordings, fetchTimeline, openRecordingFile, fetchReidVehicles, fetchVmsStatus, fetchEvidenceBundle) |
| 31 CSS rules (15 classes) | Classes no component renders since the layout rework |
| `ensure_incident_for_dispatch`, `draw_flash_effect` | Never called |
| `skills-lock.json` untracked + ignored | Belongs to the local design-skill install, not to Aegis |
| Test DBs, `.coverage`, `__pycache__`, `.DS_Store`, `frontend/dist` | Generated; recreated by tests/builds |
| **Bug:** logs went to `utils/logs/` | Logger resolved its path from its own folder; now uses `paths.LOGS_DIR` (`logs/`). Old log moved there. |

Kept on purpose: `presentation/` (190 MB of defense slides, report, images — not used by the
system, but yours to decide; see 13), `data/recordings/` (see 2), all `scripts/` (each is a
documented tool: setup, seed, evaluate, benchmark, deploy, retention).

## Fix first (risk of losing data or missing an incident)

1. **CI migration check fails.** `alembic check` reports two differences that predate the recent
   work: an index on `camera_officers.id` and the `face_encodings.image_id` foreign key. Add
   migration 0009 so the CI `migrations` job passes again.
2. **Retention is not scheduled.** Evidence retention (`scripts/retention_cron.py`) runs only by
   hand; recordings are purged only when the pipeline uploads a new segment. Add a daily
   background job in the backend (next to the escalation loop) for evidence, captures and
   recordings. **Note:** the 48 h rule will delete the ~1.2 GB of October recordings the next
   time detection runs — copy any you want to keep (they are useful labelled-clip material).
3. **No backups.** Nothing backs up the database or evidence. Add a nightly backup (SQLite
   `.backup` / `pg_dump` + evidence + captures), keep N days, and a written restore procedure.
4. **Silent detection failure.** When no camera reports (pipeline crashed, machine asleep) the
   dashboard shows it, but nobody is paged. Raise a `DETECTION_DOWN` alert to the same
   webhooks/SMS after ~2 minutes, and `DETECTION_RESTORED` when it comes back.
5. **Capture stills are stored unencrypted.** Zoomed face crops (`alert_captures.image_data`) are
   personal data; evidence stills are encrypted, these are not. Encrypt them the same way.
6. **Two detectors are off on this machine.** `models/weapon_yolo.pt` is missing (no weapon
   alerts at all) and the action model is not exported (no fall/staggering from ST-GCN). Restore
   the weapon model; run `scripts/export_action_model.py`.
7. **Viewer role is a dead end.** Viewers can open pages but every data request is refused.
   Decide: read-only access in the backend, or remove the role.

## Should do (accuracy and maintainability)

8. **Measure accuracy.** Label 10–20 clips and run `scripts/evaluate_accuracy.py`; then tune weapon
   (`weapon:`), tamper (`tamper:`) and face thresholds with numbers, not guesses.
9. **Operator feedback loop.** Rejected alerts already store a reason. Show false-alert rate per
   camera and alert type on Analytics and suggest thresholds per camera.
10. **Weakest test coverage:** `core/visualization/hud.py` (6 %), `backend/api/vms_routes.py`
    (43 %), `backend/api/incident_routes.py` (54 %), `core/recognition/face_worker.py` (25 %).
    Raise the CI gate to 72 % after.
11. **Split `App.jsx`** (~810 lines, ~40 pieces of state) into hooks: session, live status,
    alerts/notifications, navigation. Easier to change and to test.
12. **Split `index.css`** (~1,800 lines) per component/page, or move to CSS modules.
13. **Move `presentation/` out of the code repo** (190 MB makes every clone slow): a separate repo,
    a GitHub release, or Git LFS.
14. **PostgreSQL outside Docker too.** Local runs use SQLite, which locks under concurrent writes
    from the API and several cameras; Docker already uses PostgreSQL.

## Could do (new capability)

15. **Fight / assault detection** — the known gap (see AGENTS.md); start with the pose heuristic,
    ship only if the evaluation shows it beats a false-alert budget.
16. **Push notifications for responders** (web push / PWA) instead of SMS-only paging.
17. **Two-factor sign-in for admins and supervisors.**
18. **HTTPS deployment guide** (reverse proxy + `COOKIE_SECURE=true`).
19. **Floor plans** on the map for indoor sites, with cameras placed on them.

## Status (2026-11-23)

| # | Item | Status |
|---|---|---|
| 1 | Migration check | Done: 0009 (officer index, named FK); `alembic check` clean through 0013 |
| 2–3 | Retention, backups | Done: nightly maintenance in the API (`backend/services/maintenance.py`, `backup.py`); Settings → Backups and clean-up; restore steps in `docs/OPERATIONS.md` |
| 4 | Silent detection failure | Done: health watch → `CAMERA_OFFLINE` / `DETECTION_DOWN` (+ restored) |
| 5 | Encryption at rest | Done: evidence, capture and enrolment images (AES-GCM); `scripts/encrypt_existing.py` for older rows. Before this, **none** of them were encrypted |
| 6 | Detector models | Action and re-ID models exported/downloaded; **weapon model still missing** (custom-trained, not public) |
| 7 | Viewer role | Done: read-only wall display (Home, Live, Map, Alerts; no faces, evidence, media) |
| 8 | Measure accuracy | **Open: needs your labelled clips** (`data/eval/clips/`) |
| 9 | False-alert feedback | Done: Analytics → false-alert rate per type with a one-click threshold change |
| 10 | Test coverage | Done: 352 tests, 76 % (CI gate 75 %) |
| 11 | Split `App.jsx` | Done: 808 → 372 lines, 7 hooks |
| 12 | Split `index.css` | Done: `src/styles/01-…09-*.css`, same cascade (build output checked) |
| 13 | `presentation/` | Moved to `../aegis-presentation` (untracked here, still in git history) |
| 14 | PostgreSQL locally | Done: `make db-up`, `make db-copy` (`scripts/copy_database.py`) |
| 15 | Fight detection | Pose heuristic `core/analysis/fight.py`, **off** (`fight.enabled: false`) until measured (item 8) |
| 16 | Responder push | Done: Web Push, "Turn on phone alerts" on Responders; pushes carry no alert data |
| 17 | Two-factor sign-in | Done: TOTP (authenticator app), Home prompt for admins/supervisors, admin reset |
| 18 | HTTPS guide | Done: `docs/OPERATIONS.md` |
| 19 | Floor plans | Done: Map → Floor plans (admin upload, drag corners to fit); no rotation yet |
