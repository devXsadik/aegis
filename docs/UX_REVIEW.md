# Aegis dashboard — UX review and feature proposals

Review date: 2026-11-22. Every page was opened as an admin in Chrome at 1280×800, 1440×900 and
1920×1080, on a copy of the real database (5 cameras, no detection running).

## The core problem: the work gets a third of the screen

Three panels stay on screen on every page: cameras (left, 288 px), "Response" (right, 316 px)
and the live-video strip (top, 230–270 px). Then each page adds a large title, a description
line and a row of 2–4 stat cards before its real content.

| Screen | Area left for the page | Page content starts at |
|---|---:|---:|
| 1280×800 (most laptops) | 34 % | 466 px |
| 1440×900 | 29 % | 488 px |
| 1920×1080 | 39 % | 510 px |

On a laptop, the Alerts page shows the queue but the alert's snapshot and the Confirm /
Reject buttons are below the fold, inside a scrolling box inside the page. The map starts
below the fold on the Map page. The live-video strip shows on the Live page above the live
page's own video, and shows "Off" tiles 250 px tall when nothing streams.

## Why features are hard to find

1. **Navigation is split four ways.** Four tabs inside the centre panel (Home, Live, Alerts,
   Map); the other ten pages as coloured tiles in a panel called **"Response"** (which also
   holds Cameras, Users and Settings — not response tools); Users/Settings again in the
   avatar menu; everything in ⌘K. A new operator has no single list of what exists.
2. **Pages opened from the tiles appear as a fifth tab** after a separator, then vanish when
   you leave: the tab bar changes shape as you move.
3. **The coloured tiles look like buttons for actions**, not navigation; colour carries no
   meaning (the code says so) but users read it as status.
4. **Set-up pages sit beside daily work.** Users, Settings, Zones appear on every screen for
   admins, next to Incidents and Evidence.

## Numbers and words that disagree

The same screen shows different answers to the same question:

| Question | Answers on one screen |
|---|---|
| How many alerts need me? | Alerts tab badge **1** · bell **1** · "Open alerts **2** not handled" · "Review alerts (**1**)" |
| How many cameras? | Left panel **5** · Cameras page "**8** registered" · Live "0/**5**" · Map "5 of **8** placed" |
| Camera state words | Off · No signal · Paused · Offline · No video · Not live · Pipeline offline · Not reporting |

And jargon an operator should not need: *Redis / In-Process*, *High Availability*,
*embeddings*, *Pipeline offline*, *Lock to this device*, *ReID*.

## Visual quality

- **Every page starts the same way**: giant condensed title + grey sentence + 4 big stat
  cards. Pages look alike; the stat cards are rarely what the user came for.
- **Too many equal-weight boxes**: cards inside panels inside panels, all with the same
  radius, border and padding — no clear primary area.
- **Colour noise**: tinted tiles (orange, teal, purple, olive) + status pills + severity tags
  compete; the one colour that matters (red = critical) is not unique.
- **Large empty states** (black "Off" video tiles, "No snapshot was saved") take the most
  space on screen when there is least to show.

## Proposed layout (control-room standard: Genetec, Milestone, Verkada all work this way)

```
┌──────────┬──────────────────────────────────────────────────────────────┐
│ AEGIS    │ Alerts                      ● 1 needs action  ● Detection off  🔔  👤 │
│          ├──────────────────────────────────────────────────────────────┤
│ MONITOR  │                                                              │
│  Home    │                                                              │
│  Live    │                 the page, edge to edge                       │
│  Map     │                 (≈ 80 % of the screen)                       │
│ RESPOND  │                                                              │
│  Alerts 1│                                                              │
│  Incidents                                                              │
│  Evidence│                                                              │
│ INVESTIGATE                                                             │
│  People  │                                                              │
│  Vehicles│                                                              │
│  Analytics                                                              │
│  Reports │                                                              │
│ ──────── │                                                              │
│ Setup ▸  │  (Cameras, Zones, Users, Settings — collapsed group, admins)  │
└──────────┴──────────────────────────────────────────────────────────────┘
```

1. **One left sidebar** with every page, grouped Monitor / Respond / Investigate / Setup;
   collapses to icons (56 px); badges on Alerts and Incidents. Replaces the four tabs, the
   "Response" tiles and the duplicate avatar-menu links. Phones keep the bottom tab bar.
2. **Remove the always-on right and top panels.** The open-alerts list lives on Home and the
   Alerts page; a critical alert still pops up and rings everywhere. Video lives on Live (and
   small tiles on Home). An optional "pin camera" picture-in-picture keeps one feed visible
   while working elsewhere.
3. **The camera list moves into the Live page** as its left column, where it is used.
4. **Compact page header**: page name in the top bar (one line), description as a tooltip.
   Stat cards only where they lead to an action, one compact row.
5. **One alert number** ("needs action" = pending review + unacknowledged critical) used by
   the sidebar badge, the bell and Home. **Four camera states** everywhere: Live, No video,
   Paused, Offline.
6. **Alerts page as a split view that fits the screen**: queue left, detail right with the
   action buttons pinned at the top of the detail (always visible), snapshot and video
   below, facts in a compact grid.
7. **Visual system**: one neutral surface colour for panels, colour reserved for status
   (red critical, amber warning, green ok, blue info); smaller, regular-weight titles;
   fewer borders, more spacing between groups than inside them.

Expected result: the work area goes from ~30 % to ~80 % of the screen; every feature is one
click from a sidebar that never changes shape.

## New features for surveillance operations

Ordered by value to an operator for the effort, given what the backend already has.

| # | Feature | Why it matters | Effort | Already there |
|---|---|---|---|---|
| 1 | **Play video from an alert** — "Watch 10 s before/after" in the alert detail | Operators judge an alert from motion, not one still; today the clip is only reachable from the Live page | S | Recording playback API (`/vms/playback`) |
| 2 | **Video wall** — 1/4/9/16 grids, saved layouts, camera tour (auto-cycle), alerting camera jumps to a "spot" tile | The main control-room screen; today Live is a list plus one player | M | MJPEG streams |
| 3 | **Camera tamper alerts** — lens covered, camera moved, blurred, too dark, frozen picture | Blinding or turning a camera is the first thing an intruder does; today it only shows as "no detections" | S–M | Frames already in the pipeline (OpenCV checks) |
| 4 | **Zone schedules** — arm a zone only after hours / weekends; per-zone sensitivity | Biggest cut in false alerts: intrusion at 3 am matters, at 3 pm it is staff | M | Zones + anomaly detector |
| 5 | **Alert timers and escalation on screen** — "unanswered 2:14", queue sorted by urgency, red when the escalation limit nears | Makes response time visible and measurable | S | Escalation loop, MTTA metric |
| 6 | **Shift handover** — operator log (notes with time + camera), auto shift summary (alerts handled, open incidents, cameras down), sign-off by next operator | Nothing is lost between shifts; required in most SOC/security operations | M | Audit log, incidents |
| 7 | **"Where was this person?"** — from any capture, find the same person on other cameras in a time window, shown as a timeline and on the map | Turns cross-camera tracking into an investigation tool | M | Appearance re-ID (`cross_camera.py`, `/reid`) |
| 8 | **Occupancy limits** — live people count per zone, alert above a set maximum | Crowd safety, fire-code limits, queues | S | Crowd threshold in anomaly detector |
| 9 | **Evidence package export** — clip + stills + chain-of-custody hashes + report as one signed ZIP/PDF for police or court | Evidence is only useful if it can be handed over intact | M | Custody records, SHA-256, reports |
| 10 | **Responder mobile view** (police role) — my assigned alerts, photo, map directions, "on my way / arrived / resolved" | Closes the loop from detection to response | M | Officer assignment, GPS, phone tab bar |

## Layout — done 2026-11-22

Measured again at the same sizes: the page now gets **72 % (1280×800), 75 % (1440×900),
81 % (1920×1080)** of the screen, up from 34 / 29 / 39 %, and content starts at the top.

- One sidebar (`components/Sidebar.jsx`): Monitor / Respond / Investigate, Set up folded at the
  bottom; collapses to icons (remembered); Alerts badge pulses on a critical alert. The four
  centre tabs, the "Response" tile panel, the left camera panel and the top video strip are gone.
- Page name and description in the top bar; the large title block is gone.
- Live cameras is now a **video wall** (All / 1 / 2×2 / 3×3, remembered; the alerting camera
  goes first; double-click or ⤢ for full screen; Start on paused tiles, Pause on hover).
  The camera list shows only when the wall shows fewer cameras than exist.
- One alert number (alerts waiting for review) on the sidebar, bell, phone tab bar and Home;
  the queue header says "2 entries · 3 alerts" when repeats are grouped.
- One set of camera words everywhere: Live · No video · Paused · Offline. Home no longer
  calls paused cameras "offline"; "AI pipeline is not reporting" → "Detection is off".
- Main JS bundle 311 → 274 kB (Live page now loads on first visit too).
- Playwright smoke updated for the sidebar and passing.

Not done yet: pinned picture-in-picture camera, visual-system pass (colour/borders),
stat-card trim on Analytics/Cameras/Users.

## Features 1, 3, 5 — done 2026-11-23

- **Play video from an alert** (feature 1): "Watch video from 10 s before" (or `P`) in the alert
  details plays the recording cued to 10 s before the alert. Found and fixed on the way: the DVR
  records MPEG-4 Part 2 (`mp4v`), which no browser plays, so recorded video never played in the
  dashboard (the Live page's Recordings "Play" too). Recording stays `mp4v` (H.264 costs ~3× the
  CPU per frame: 19 vs 6.5 ms at 960 px); a segment is converted to H.264 the first time someone
  plays it and cached as `<name>.web.mp4` (`backend/services/playable.py`; ffmpeg, or OpenCV's
  H.264 writer as fallback; ffmpeg added to the Docker image). Originals are untouched for evidence.
- **Alert timers** (feature 5): every waiting alert shows "waiting 2:14", live. Watchlist and
  weapon alerts turn amber at half the backup-paging limit and red when it is reached
  (`ESCALATE_AFTER_SECONDS`, now returned by `/alerts/review-queue-count`); others turn amber
  after 10 min. The details say when backup officers will be / were paged. Queues are sorted
  most severe first, then longest waiting first.
- **Camera tamper alerts** (feature 3): `core/analysis/tamper.py` checks each camera's raw
  picture once a second for covered, blurred, moved and frozen; raises `CAMERA_TAMPER` (high).
  The move check ignores areas where people are and compares contrast-equalised views, so
  people close to the lens and auto-exposure do not count. Replayed on ~97 min of the dev
  webcams' real recordings: 0 false alerts; the 4 alerts it raised were real (camera turned
  three times, carried once). Settings under `tamper:` in `config.yaml`.

## Remaining features — done 2026-11-23

All checked in headless Chrome on a copy of the database (two users at once where it matters).

- **Zone schedules and occupancy limits** (4, 8): per zone "Active hours" (days + from/until,
  overnight allowed; local time of the pipeline computer) and "Max people". Off hours a zone
  counts but raises nothing; over the limit raises `OCCUPANCY_LIMIT` once per crossing. Live
  counts ("Lobby 7 / 12", "off hours") on Analytics. Stored in the camera's geometry JSON.
- **Camera tour** (2): 1 / 2×2 / 3×3 layouts step through every camera every 10 s; the alerting
  camera stays on screen.
- **Shift log and handover** (6): new page with notes (optionally per camera), a live shift
  summary, "Hand over the shift" (notes + summary snapshot) and "Accept handover" by the next
  operator (not the author). Home shows a waiting handover first. Table `shift_entries`,
  migration 0008.
- **Where was this person?** (7): face matches, look-alike tracking and capture stills merged
  into visits per camera in time order, with the gap between them and a map jump. Opens from
  alert details, Watchlist sightings and People cards.
- **Evidence package** (9): ZIP per incident (case + timeline, alert, decrypted stills with
  custody chains, captures, original recordings), SHA-256 manifest, HMAC signature
  (`EVIDENCE_SIGNING_KEY`, else derived from `SECRET_KEY`), EXPORTED custody record.
  "Check a package" verifies it. Checked with curl + `shasum -c` (headless Chrome blocks downloads).
- **Responder view** (10): police (and operators) get "Responders": serious alerts for their
  assigned cameras (all if none), still, directions, and On my way → On scene → Resolved.
  Each step goes on the incident timeline and to the control room's notifications live;
  Resolved resolves the incident and acknowledges the alert. Police phones open on it.
- **Pinned camera**: pin a tile on the Live wall; a small live picture follows you on every
  other page (smaller / open / unpin), remembered on this device, hidden on phones.

## Suggested order

1. **Layout** (sidebar, remove side/top panels, compact headers, one alert number, four
   camera states, Alerts split view). Largest gain; touches `App.jsx`, `Workspace.jsx`,
   `index.css` and every page header.
2. **Features 1, 5, 3** — small, and each makes the Alerts page or camera health better.
3. **Video wall (2)**, then **zone schedules (4)**.
4. **Shift handover (6), person search (7), evidence export (9), responder view (10).**
