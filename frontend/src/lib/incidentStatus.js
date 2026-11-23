/* Incident status machine on the dashboard side. The server (GET /incidents/statuses) is the
   source of truth and enforces every rule again; FALLBACK mirrors it so the picker works before
   that answer arrives. Keep it in step with backend/services/incident_status.py. */

export const FALLBACK_SPEC = {
  statuses: [
    { id: 'new', label: 'New', color: 'danger', desc: 'Raised, nobody has looked yet.' },
    { id: 'acknowledged', label: 'Acknowledged', color: 'info', desc: 'An operator has seen it.' },
    { id: 'verified_match', label: 'Verified match', color: 'purple', desc: 'An operator confirmed the face / vehicle match.' },
    { id: 'officer_dispatched', label: 'Officer dispatched', color: 'cyan', desc: 'Officers are on their way.' },
    { id: 'in_progress', label: 'In progress', color: 'warn', desc: 'Being worked on.' },
    { id: 'target_located', label: 'Target located', color: 'orange', desc: 'Officers have found the person or vehicle.' },
    { id: 'resolved', label: 'Resolved', color: 'ok', desc: 'Handled; waiting to be closed.' },
    { id: 'closed', label: 'Closed', color: 'muted', desc: 'Finished. Needs a closing note.' },
    { id: 'false_alarm', label: 'False alarm', color: 'muted', desc: 'Not a real match or event. Needs a note; feeds accuracy stats.' },
  ],
  transitions: {
    new: ['acknowledged', 'verified_match', 'officer_dispatched', 'in_progress', 'false_alarm', 'closed'],
    acknowledged: ['verified_match', 'officer_dispatched', 'in_progress', 'false_alarm', 'closed'],
    verified_match: ['officer_dispatched', 'in_progress', 'target_located', 'false_alarm'],
    officer_dispatched: ['in_progress', 'target_located', 'resolved', 'false_alarm'],
    in_progress: ['officer_dispatched', 'target_located', 'resolved', 'false_alarm'],
    target_located: ['in_progress', 'resolved'],
    resolved: ['closed', 'in_progress'],
    closed: ['in_progress'],
    false_alarm: ['acknowledged'],
  },
  note_required: ['closed', 'false_alarm'],
  confirm_required: ['closed', 'false_alarm'],
  command_only_from: ['closed', 'false_alarm'],
}

const LEGACY = { open: 'new', investigating: 'in_progress' }
export const normalizeStatus = (s) => LEGACY[s] || s
export const OPEN_STATUSES = ['new', 'acknowledged', 'verified_match', 'officer_dispatched', 'in_progress', 'target_located']
const COMMAND = new Set(['admin', 'supervisor'])

/** Statuses `role` may pick next from `current`, each with { needsNote, needsConfirm }. */
export function nextOptions(spec, current, role) {
  const cur = normalizeStatus(current)
  const from = spec.transitions[cur] || []
  if (spec.command_only_from.includes(cur) && !COMMAND.has(role)) return []
  return spec.statuses
    .filter((s) => from.includes(s.id))
    .map((s) => ({
      ...s,
      needsNote: spec.note_required.includes(s.id) || spec.command_only_from.includes(cur),
      needsConfirm: spec.confirm_required.includes(s.id) || spec.command_only_from.includes(cur),
    }))
}

export function statusMeta(spec, id) {
  return spec.statuses.find((s) => s.id === normalizeStatus(id)) || { id, label: id, color: 'muted', desc: '' }
}
