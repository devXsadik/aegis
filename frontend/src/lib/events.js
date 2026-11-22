/* Event/alert taxonomy shared by Triage, Detection Center and Overview. */
import { parseTs } from './time'

export const EVENT_META = {
  CRIMINAL_DETECTED: { label: 'Watchlist match', group: 'faces', icon: 'watchlist' },
  PERSON_TRACKED: { label: 'Tracked across cameras', group: 'faces', icon: 'eye' },
  WEAPON_DETECTED: { label: 'Weapon detected', group: 'weapon', icon: 'alert' },
  SUSPICIOUS_VEHICLE: { label: 'Watchlisted vehicle', group: 'vehicle', icon: 'vehicle' },
  SUSPICIOUS_BEHAVIOR: { label: 'Suspicious behavior', group: 'behavior', icon: 'eye' },
  ANOMALY_DETECTED: { label: 'Zone anomaly', group: 'behavior', icon: 'eye' },
  INTRUSION: { label: 'Restricted-zone entry', group: 'behavior', icon: 'shield' },
  FIRE_SMOKE_DETECTED: { label: 'Fire / smoke', group: 'fire', icon: 'fire' },
  FALL_SUSPECTED: { label: 'Possible fall', group: 'fall', icon: 'users' },
  CAMERA_TAMPER: { label: 'Camera tampered', group: 'camera', icon: 'camera' },
}

export const GROUPS = [
  { id: 'all', label: 'All' },
  { id: 'faces', label: 'Watchlist' },
  { id: 'weapon', label: 'Weapons' },
  { id: 'vehicle', label: 'Vehicles' },
  { id: 'behavior', label: 'Behavior' },
  { id: 'fire', label: 'Fire & smoke' },
  { id: 'fall', label: 'Falls' },
  { id: 'camera', label: 'Camera tamper' },
]

export function eventLabel(type = '') {
  const t = String(type).toUpperCase()
  return EVENT_META[t]?.label || t.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase())
}

export function eventGroup(type = '') {
  return EVENT_META[String(type).toUpperCase()]?.group || 'other'
}

export function eventIconKey(type = '') {
  return EVENT_META[String(type).toUpperCase()]?.icon || 'eye'
}

export const REVIEW_LABEL = {
  pending: 'Needs review',
  confirmed: 'Confirmed',
  rejected: 'Rejected',
  not_required: '',
}

export const REJECT_REASONS = [
  { value: 'false_detection', label: 'False detection' },
  { value: 'known_person', label: 'Known / authorised person' },
  { value: 'duplicate', label: 'Duplicate of another alert' },
  { value: 'test', label: 'Test or drill' },
  { value: 'other', label: 'Other' },
]

/* API alert row → UI model */
export function fromAlertRow(a) {
  return {
    id: a.id,
    type: a.alert_type,
    severity: a.severity || 'info',
    time: a.timestamp,
    camera: a.camera_location || a.camera_id,
    cameraId: a.camera_id,
    trackId: a.track_id,
    personName: a.person_name,
    plate: a.plate_number,
    msg: a.message,
    acknowledged: a.acknowledged,
    dismissed: a.dismissed,
    reviewStatus: a.review_status || 'not_required',
    reviewNote: a.review_note,
    escalatedAt: a.escalated_at,
  }
}

/** "0:45", "12:03", "2 h 05 min": how long an alert has been waiting. */
export function waitLabel(seconds) {
  const s = Math.max(0, Math.floor(seconds))
  if (s >= 3600) return `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')} min`
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/* How urgent a waiting alert is. Watchlist and weapon alerts page backup officers after
   `escalation.after` seconds: amber from half that, red once reached. Others turn amber
   after 10 minutes. null for resolved alerts. */
export function waitUrgency(item, nowMs, escalation = {}) {
  if (item.acknowledged || item.dismissed) return null
  const waited = (nowMs - (parseTs(item.since ?? item.time)?.getTime() || nowMs)) / 1000
  const limit = escalation.after || 0
  if (limit > 0 && (escalation.types || []).includes(item.type)) {
    return waited >= limit ? 'danger' : waited >= limit / 2 ? 'warn' : 'ok'
  }
  return waited >= 600 ? 'warn' : 'ok'
}

/* Repeats of one alert (same type, camera, person and plate, each within `windowMs` of the
   next) become one queue entry, so a person standing in view is one decision, not twenty.
   The entry is the newest alert; `repeats` holds every id in the run (itself included). */
export function groupRepeats(items, windowMs = 10 * 60 * 1000) {
  const at = (it) => parseTs(it.time)?.getTime() || 0
  const open = new Map()
  const groups = []
  for (const it of [...items].sort((a, b) => at(b) - at(a))) {
    const key = `${it.type}|${it.cameraId ?? it.camera}|${it.personName ?? ''}|${it.plate ?? ''}`
    const run = open.get(key)
    if (run && run.oldest - at(it) <= windowMs) {
      run.item.repeats.push(it.id)
      run.item.since = it.time
      run.oldest = at(it)
      continue
    }
    const item = { ...it, repeats: [it.id], since: it.time }
    open.set(key, { item, oldest: at(it) })
    groups.push(item)
  }
  return groups
}

/* Plain-language "why did this fire" — shown to operators so they can judge it. */
export const EXPLAIN = {
  CRIMINAL_DETECTED: 'A face matched an enrolled person in at least 2 frames. A match is a lead, not an identification — compare the snapshot with the enrolled photos before confirming.',
  PERSON_TRACKED: 'This person looks like someone who raised a watchlist or weapon alert earlier, here or on another camera. The match is on clothing and build, not the face, so similar clothes can match — compare the captures before acting.',
  WEAPON_DETECTED: 'A weapon-like object was seen on the same person in at least 3 of the last 5 processed frames. Tiny detections are ignored, and one that is not in a hand needs a higher score; the details say whether it was in hand. Check the snapshot: tools, phones and umbrellas are common false positives.',
  FIRE_SMOKE_DETECTED: 'Fire or smoke was seen in at least 5 of the last 8 frames. Steam, fog and bright lights can look similar.',
  CAMERA_TAMPER: 'The camera picture changed in a way people do not cause: it went dark or uniform (covered), lost its sharpness (smeared or knocked out of focus), now shows a different steady view (turned or knocked), or stopped changing (frozen). Check the camera itself, and the recording just before, for who did it.',
  FALL_SUSPECTED: 'A person was upright, then stayed horizontal for 2 seconds or more. They may be resting or exercising — check the camera.',
  INTRUSION: "A person's feet entered a zone marked restricted for this camera.",
  ANOMALY_DETECTED: 'A zone rule fired (crowding or long dwell time).',
  SUSPICIOUS_BEHAVIOR: 'Movement or posture matched a behaviour rule (loitering, rapid or erratic movement, raised arms). These rules are heuristics and do produce false alarms.',
  SUSPICIOUS_VEHICLE: 'A plate read matched the vehicle watchlist. OCR misreads are common — verify the plate in the snapshot.',
}
