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

## Phase 1 — Quick wins (1–2 days)

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

## Phase 2 — Make the UI easier for operators (1 week)

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

### 3.1 Measure before tuning
Nothing in `data/results/` today. For the defense and for every tuning change:
- Build a small labelled set (10–20 clips: entries, watchlist faces, weapons, falls, empty scenes).
- Run `scripts/evaluate_pipeline.py` and `scripts/evaluate_faces.py`; commit a results table
  (precision, recall, false alerts/hour, time-to-identify, FPS on the M2).
- Add a CI job that runs the eval on 1–2 tiny clips and fails on large regressions.

### 3.2 Cheaper vehicle detection
`vehicle_detection` uses a separate YOLOv8l (~2× person-model time). The person model is
COCO-trained and already sees cars/buses/trucks/motorbikes; `detector.py:18` throws them
away with `classes=[0]`. Detect `[0, 2, 3, 5, 7]` in one pass and split the results →
vehicles/ANPR for nearly free; keep YOLOv8l as an optional "accuracy" mode.

### 3.3 Learn from operator feedback
Triage decisions (confirmed / false positive) are stored. Use them:
- Per-camera, per-alert-type false-positive rate on the Analytics page.
- Suggested threshold per camera (e.g. raise `weapon_conf_threshold` where FP rate is high).
- Export false-positive crops as hard negatives for the weapon model.

### 3.4 Weapon false positives
Single-frame weapon hits are the main source of bad critical alerts in CCTV systems.
Confirm with N-of-M frames on the same track + minimum box size + "held near hand"
check using pose keypoints already computed (`test_weapon_confirm.py` exists — extend it).

### 3.5 Known gap: fighting
No fight detector (documented in AGENTS.md). Options, cheapest first:
1. Pose-based heuristic: two tracks within arm's length + high limb velocity for > 1 s → "possible altercation" (high, not critical).
2. Fine-tune ST-GCN on RWF-2000 / real CCTV fight clips using the existing ONNX path.
Only ship after 3.1 shows it beats a false-alert budget.

---

## Phase 4 — Robustness and security (1 week)

| Item | Where | Why |
|---|---|---|
| JWT in `localStorage` → httpOnly, SameSite cookie | `frontend/src/services/api.js:4` | XSS cannot steal the session |
| Stream/snapshot `?token=` → short-lived signed stream token | `backend/api/stream_routes.py:45,79` | long-lived JWT ends up in logs/history |
| In-process state (rate limiter, `_frames`, `_pipeline_status`) | `backend/middleware/rate_limiter.py`, `stream_routes.py:21`, `system_routes.py` | breaks with >1 uvicorn worker; move to Redis when `REDIS_URL` set (`ha.py` exists) |
| 94 `except Exception` blocks | backend/core/utils | audit: log with context or narrow; silent `pass` hides failures |
| Pipeline watchdog | `main.py` | restart a camera whose inference worker reports `failed`, surface it on dashboard |

---

## Phase 5 — Tests and CI (ongoing)

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
