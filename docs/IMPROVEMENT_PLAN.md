# Aegis — Improvement Plan

Review date: 2026-11-22. Baseline at review time:

| Check | Result |
|---|---|
| `pytest tests/` | 229 passed, 2 skipped, 201 warnings (mostly `datetime.utcnow`) |
| `ruff check .` | clean |
| `npm run lint` / `npm run build` | clean; one 563 kB JS chunk (over the 500 kB warning) |
| CI coverage gate | 58 % (backend/core/utils); frontend has no tests |
| `data/results/`, `data/demo/clips/` | empty — no measured accuracy numbers in the repo |

The system is in good shape: modular 6-stage pipeline, shared models across cameras,
inference off the video thread, role-based UI, audit log, migrations checked in CI.
What follows is ordered by value per effort.

---

## Phase 1 — Quick wins (1–2 days) — done 2026-11-22

Result: preloads gated by role (`data.view`, `audit.view` in `lib/permissions.js`);
status poll 3 s → 10 s, heartbeats (now carrying `flags`) update cameras live over the
status socket; main JS chunk 563 kB → 302 kB (pages lazy-loaded, Leaflet only with Map);
`datetime.utcnow()` → `clock.utcnow()` (kept naive UTC on purpose: stored values are
naive, and mixing aware/naive raises); startup moved to `lifespan`, escalation task now
cancelled on shutdown. `seed_cameras()` kept at startup: it is an idempotent sync of
`cameras.yaml`. Test warnings 201 → 115 (rest come from libraries).

Found on the way: the `viewer` role can open Home/Live/Map/Alerts in the UI, but every
data endpoint and both sockets require an operational role, so a viewer sees nothing.
Decide: give viewers read access in the backend, or drop the role.

### 1.1 Stop loading data the user may not see
`frontend/src/App.jsx:328-360` fires 13 requests at sign-in for every role.
`/audit/` is `admin_only` (`backend/api/audit_routes.py:36`), so every non-admin gets
the banner "Some data could not be loaded (audit log)" on first load.
- Gate each preload with `canViewPage(me.role, …)` (wait for `fetchMe` first).
- Load page data on the page that uses it, not up front (already half done at `App.jsx:363`).

### 1.2 Cut polling, use the WebSocket you already open
The dashboard polls `/system/status` and `/stream/cameras` every 3 s, devices/power
every 5 s, review count every 15 s — **and** opens a `status` WebSocket whose handler is
a no-op (`App.jsx:306`). On the 8 GB dev Mac this competes with the pipeline.
- Push status/streaming/review-count over the `status` socket; keep a 30 s poll as fallback.

### 1.3 Code-split the dashboard
Lazy-load each page with `React.lazy` + `Suspense` (`PAGE_COMPONENTS`, `App.jsx:111`);
Leaflet only on Map. Target: first chunk < 250 kB.

### 1.4 Backend hygiene
- 46 `datetime.utcnow()` → `datetime.now(timezone.utc)` (removes most test warnings,
  avoids naive/aware comparison bugs).
- `@app.on_event("startup")` → FastAPI `lifespan` (`backend/main.py`).
- Move `seed_cameras()` out of API startup into `run.sh`/setup, or make it idempotent and logged.

---

## Phase 2 — Make the UI easier for operators (1 week) — done 2026-11-22

Result (checked in headless Chrome as admin and investigator, on a copy of the DB):
- Alerts: repeats (same type, camera, person, plate, each within 10 min) are one queue
  entry with "×N"; Confirm / Reject / Dispatch apply to all N. `I` creates an incident
  (J/K/V/D already existed). Critical pop-up has "Mute camera 10 min": pop-ups and sound
  stop for that camera, alerts still reach the queue; a top-bar chip shows mutes and unmutes.
- Navigation: Faces + Watchlist → **People** (Registry | Watchlist sightings);
  Analytics + Detection history → **Analytics** (Trends | Detection history). Old links
  and permissions keep working (`PAGE_VIEWS` in `lib/permissions.js`). The response panel
  lists every non-tab page by group (Respond / Investigate / Set up).
- Status: "Detection on/off" + "Live" pills → one chip; its panel says what is wrong and
  what to do, per camera and per model. Detection now counts as on only while a camera is
  reporting (`online` stayed true forever after the first heartbeat). Models turned off in
  `config.yaml` read "Turned off", not "missing".
- Home: "Get started" checklist (camera → detection → enrol → zones), ticks itself off, hideable.
- "Assistant" renamed **Quick answers** (it is rule-based). Notifications, Quick answers and
  the search palette are now real dialogs (focus trap, Esc, focus returns) via `useDialog`.

Not done: role-tailored Home (2.1), light-theme contrast audit with axe (2.6).
The mute button was not exercised in the browser (needs a live critical alert).

### 2.1 One navigation model
Today there are four ways to move: centre tabs, left camera panel, right "response"
tool tiles, and ⌘K palette — plus a phone tab bar. 16 pages for an admin.
- Keep: centre tabs (Home, Live, Alerts, Map) + a single collapsible left sidebar with the
  grouped `NAV` (Watch / Respond / Investigate / Set up). Drop the duplicate tool tiles.
- Merge near-duplicates: **Faces + Watchlist** (watchlist = a filter on Faces);
  **Detection history + Analytics** (table + charts on one page).
- Role-tailored Home: viewer/police see alert queue + assigned cameras only.

### 2.2 Alert handling = the core workflow
- One-key triage on the Alerts page: `A` acknowledge, `D` dismiss/false-positive,
  `I` open incident, `J/K` next/previous.
- Group repeated alerts (same person + camera within N min) into one card with a count —
  reduces alarm fatigue from the 4-card critical stack.
- Per-camera "snooze 10 min" for known-noisy cameras.
- Feed "false positive" decisions back as data (see 3.3).

### 2.3 First-run experience
A setup checklist on Home when the system is empty: add a camera → enrol a face →
draw a zone → send a test alert. Each step links to its page and ticks itself off.

### 2.4 Clear system state
- Replace three status pills with one status chip that opens a panel: per-camera FPS,
  inference ms, last frame age, model health (`/health` already returns this).
- Show *why* detection is off (pipeline not running vs. camera off vs. model missing).

### 2.5 Honest assistant
`Copilot.jsx` is keyword matching, but is labelled "Ask the assistant". Either:
- rename to "Quick answers" with the fixed suggestions as buttons, or
- wire it to an LLM with read-only tools over the existing API (alerts, analytics,
  cameras) so answers cite real records.

### 2.6 Accessibility / polish
- Keyboard focus trap + return focus for modals and drawers.
- Respect `prefers-reduced-motion` for the critical banner pulse (partly done).
- Run axe on each page; fix contrast in light theme.

---

## Phase 3 — Make detection more reliable (1–2 weeks)

### 3.1 Measure before tuning — harness done 2026-11-22, waiting for labelled clips

`scripts/evaluate_accuracy.py` replays labelled clips at live speed (newest frame, at most
`target_fps`, slow frames make later ones drop), captures alerts in-process (no backend, DB
or alarm), and writes `data/results/accuracy_<date>.{json,md}`: recall, precision, false
alerts/hour, wrong-identity matches, time to detect, inference FPS. Labels go in
`data/eval/clips/manifest.yaml` (template: `manifest.example.yaml`); clip videos are
gitignored. Scoring is unit-tested (`tests/unit/test_evaluate_accuracy.py`).
Smoke run on an 8 s recording (M2, AC, MPS): 7 inference FPS, 43 ms median.

Found on the way: on this machine `models/weapon_yolo.pt` is missing (no weapon alerts at
all) and the action model is not exported (no ST-GCN falls/staggering). The smoke clip,
unlabelled, raised 2 `ANOMALY_DETECTED` in 8 s — check once real labels exist.

Still to do:
Nothing in `data/results/` today. For the defense and for every tuning change:
- Build a small labelled set (10–20 clips: entries, watchlist faces, weapons, falls, empty scenes).
- Run `scripts/evaluate_pipeline.py` and `scripts/evaluate_faces.py`; commit a results table
  (precision, recall, false alerts/hour, time-to-identify, FPS on the M2).
- Add a CI job that runs the eval on 1–2 tiny clips and fails on large regressions.

### 3.2 Cheaper vehicle detection — done 2026-11-22

`vehicle_detection: off | fast | accurate` (old `true` = accurate, `false` = off; default
now `fast`). Fast asks the person model for COCO cars/motorcycles/buses/trucks in the same
pass (`HumanDetector.detect_with_vehicles`). Measured on the M2 (MPS, AC power), median per frame:

| Input | People only | fast | accurate (+YOLOv8l) |
|---|---:|---:|---:|
| `bus.jpg` (street, 30 runs) | 20.6 ms | 20.4 ms | 92.9 ms |
| webcam recording (40 frames) | 18.1 ms | 19.1 ms | 73.2 ms |

Both modes find the same bus and 4 people in `bus.jpg`. Whole-pipeline smoke run
unchanged (7.3 inference FPS). Small or far vehicles are where accurate should win; check
with labelled road clips (3.1) before using it anywhere.

`vehicle_detection` uses a separate YOLOv8l (~2× person-model time). The person model is
COCO-trained and already sees cars/buses/trucks/motorbikes; `detector.py:18` throws them
away with `classes=[0]`. Detect `[0, 2, 3, 5, 7]` in one pass and split the results →
vehicles/ANPR for nearly free; keep YOLOv8l as an optional "accuracy" mode.

### 3.3 Learn from operator feedback
Triage decisions (confirmed / false positive) are stored. Use them:
- Per-camera, per-alert-type false-positive rate on the Analytics page.
- Suggested threshold per camera (e.g. raise `weapon_conf_threshold` where FP rate is high).
- Export false-positive crops as hard negatives for the weapon model.

### 3.4 Weapon false positives — code done 2026-11-22, thresholds not yet tuned

Before a hit counts towards the existing 3-of-5-frames confirmation, `WeaponScreen`
(`core/analysis/weapon_confirm.py`) drops boxes with a side under 14 px, and checks the
person's wrists (pose keypoints, now on `ctx.poses`): in hand → counts as before; wrists
visible but away from it, or no person at all → needs score ≥ 0.65; hands not visible →
counts as before (a hidden hand is no evidence either way). Holstered or dropped weapons the
model is sure of still alert. The alert text says "(in hand)" or "(not in hand: check for a
holster, bag or a look-alike object)". Settings under `weapon:` in `config.yaml`; 8 new tests.

Not measured: `models/weapon_yolo.pt` is missing on this machine, so no weapon detection
ran. Once it is back, record clips (held gun/knife, phone, umbrella, tool, holster) and tune
`unheld_min_score` and `min_box_side_px` with `scripts/evaluate_accuracy.py`.

Single-frame weapon hits are the main source of bad critical alerts in CCTV systems.
Confirm with N-of-M frames on the same track + minimum box size + "held near hand"
check using pose keypoints already computed (`test_weapon_confirm.py` exists — extend it).

### 3.5 Known gap: fighting
No fight detector (documented in AGENTS.md). Options, cheapest first:
1. Pose-based heuristic: two tracks within arm's length + high limb velocity for > 1 s → "possible altercation" (high, not critical).
2. Fine-tune ST-GCN on RWF-2000 / real CCTV fight clips using the existing ONNX path.
Only ship after 3.1 shows it beats a false-alert budget.

---

## Phase 4 — Robustness and security (1 week) — done 2026-11-22

- **Session cookie**: sign-in sets `aegis_session` (httpOnly, SameSite=Strict, `Secure` with
  `COOKIE_SECURE=true`). The dashboard no longer stores a token; images, MJPEG, recordings and
  WebSockets carry the cookie. `/auth/refresh` renews the cookie without exposing the token to
  scripts; new `/auth/logout`. Bearer headers still work for scripts and API clients (login
  still returns the token). Checked in headless Chrome: cookie unreadable from JS, survives
  reload, cleared on sign-out, no request URL contains a token.
- **No tokens in URLs**: `?token=` is no longer accepted anywhere. WebSockets also check
  `Origin` (own host or `CORS_ORIGINS`), since browsers send cookies on cross-site handshakes.
- **In-process state**: kept in-process (every launcher runs one API worker; Redis for 5 fps
  frames would only add latency). The backend logs an error at start if `WEB_CONCURRENCY` > 1.
- **Watchdog**: a hung inference (not a crash) used to leave video and heartbeats flowing
  while nothing was analysed. Now heartbeats carry `infer_ms` and `ai_age_s`; the status
  panel shows "AI 45 ms" per camera, or "Detection is stuck on …" after 15 s; after
  `INFERENCE_STALL_SECONDS` (120) the pipeline exits with code 75 and `run.sh` restarts it.
- **Silent failures**: DVR recording and live-stream publishing errors were swallowed; now
  logged (first, then every 200th). JSON-parse fallbacks narrowed to the errors they expect.
  The remaining silent handlers are deliberate fallbacks (cleanup, optional features).
- 6 new tests (cookie, refresh, logout, WebSocket origin/cookie, stall detection, loop restart).

| Item | Where | Why |
|---|---|---|
| JWT in `localStorage` → httpOnly, SameSite cookie | `frontend/src/services/api.js:4` | XSS cannot steal the session |
| Stream/snapshot `?token=` → short-lived signed stream token | `backend/api/stream_routes.py:45,79` | long-lived JWT ends up in logs/history |
| In-process state (rate limiter, `_frames`, `_pipeline_status`) | `backend/middleware/rate_limiter.py`, `stream_routes.py:21`, `system_routes.py` | breaks with >1 uvicorn worker; move to Redis when `REDIS_URL` set (`ha.py` exists) |
| 94 `except Exception` blocks | backend/core/utils | audit: log with context or narrow; silent `pass` hides failures |
| Pipeline watchdog | `main.py` | restart a camera whose inference worker reports `failed`, surface it on dashboard |

---

## Phase 5 — Tests and CI (ongoing) — first round done 2026-11-22

- Backend coverage 66 % → 70.4 %; CI gate 58 → 68. New: `test_output_stage.py` (every alert
  path: watchlist, weapon confirm + in-hand screen, fall, suspicious, plates, zone anomalies,
  evidence throttle; output stage 10 % → 89 %), `test_alert_routes.py` (queues, context,
  confirm/reject/dispatch with fake channels; 46 % → 99 %), `test_stream_routes.py`,
  `test_recognition_stage.py` (2-vote rule, crops, back-off).
- Bug found by the new tests: an alert's "Recent on this camera" list dropped every event not
  tied to an alert (`alert_id != x` is never true for NULL). Fixed (`alert_routes.py`).
- `pytest.ini`: a DeprecationWarning raised by `backend`/`core`/`utils` now fails the run.
- Frontend: Vitest 5.1.0 (`npm test`, 12 tests on `src/lib`: permissions, repeat grouping,
  camera list, timestamps). Playwright 1.64.1 smoke (`npm run e2e`): sign in → "×2" watchlist
  entry → confirm both → incident from the other alert → reload keeps the cookie session →
  sign out. Runs against `scripts/e2e_server.py` (temp SQLite, every webhook/SMS blanked).
- CI: Node 20 → 22 (Vitest 5 needs it; frontend Docker image too), `npm test` step, new `e2e` job.

Next round: `incident_routes.py` (54 %), `vms_routes.py` (43 %), `hud.py` (6 %), then gate 72.

- Frontend: Vitest for `lib/` (permissions, cameras, time) + one Playwright smoke:
  sign in → see a seeded alert → acknowledge → incident created.
- Raise coverage gate 58 → 70 % in steps of 4 %, starting with `alert_dispatcher.py`,
  `capture_routes.py`, `camera_worker.py`.
- Add `pytest -W error::DeprecationWarning` once 1.4 is done.

---

## Suggested order

1. Phase 1 (all) — small, safe, visible.
2. 3.1 measurement — needed to judge everything after it.
3. 2.2 alert workflow + 2.1 navigation — biggest UX gain.
4. 3.2, 3.4 — accuracy/performance.
5. Phase 4, then 2.3–2.6, 3.3, 3.5.

Not verified in this review: visual design in a browser, real-camera FPS, Docker stack.
