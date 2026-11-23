// One place that says what each role may see and do. The backend still enforces every rule;
// this keeps the UI honest (no buttons that only fail after a click).

export const ROLE_PAGES = {
  viewer: new Set(['overview', 'live', 'map', 'alerts']),
  operator: new Set(['overview', 'live', 'map', 'detection', 'alerts', 'incidents', 'evidence', 'shift', 'faces', 'analytics', 'reports', 'cameras', 'settings', 'search', 'command', 'accuracy', 'response', 'patterns', 'uptime', 'roster']),
  police: new Set(['overview', 'live', 'map', 'alerts', 'respond', 'incidents', 'shift', 'roster', 'settings']),
  investigator: new Set(['overview', 'alerts', 'incidents', 'evidence', 'faces', 'watchlist', 'vehicles', 'analytics', 'reports', 'settings', 'search']),
  ml_engineer: new Set(['settings', 'models']),
  auditor: new Set(['settings', 'accuracy', 'response', 'patterns', 'uptime']),
  supervisor: null,   // null = every page
  admin: null,
}

const ACTIONS = {
  // Live data (alerts, cameras, status, map, analytics): ROLES_OPS plus the read-only viewer.
  'data.view': ['operator', 'supervisor', 'admin', 'police', 'investigator', 'viewer'],
  // Stills, recordings and person searches: personal / investigative data (not the viewer).
  'media.view': ['operator', 'supervisor', 'admin', 'police', 'investigator'],
  'audit.view': ['admin'],
  'camera.manage': ['admin'],
  'camera.power': ['operator', 'supervisor', 'admin'],
  'ptz': ['operator', 'supervisor', 'admin', 'police'],
  'triage.act': ['operator', 'supervisor', 'admin', 'police', 'investigator'],
  'incident.edit': ['operator', 'supervisor', 'admin', 'police', 'investigator'],
  'evidence.label': ['operator', 'supervisor', 'admin', 'investigator'],
  'vehicle.edit': ['operator', 'supervisor', 'admin'],
  'user.manage': ['admin'],
}

// Pages that hold the views of two former pages: open if either view is.
// The view ids (watchlist, detection) keep their own entries above.
export const PAGE_VIEWS = {
  faces: ['faces', 'watchlist'],
  analytics: ['analytics', 'detection', 'accuracy'],
  reports: ['reports', 'response', 'patterns', 'uptime'],
  shift: ['shift', 'roster'],
}

function allows(role, id) {
  const allowed = ROLE_PAGES[role]
  return allowed === undefined ? false : allowed === null || allowed.has(id)
}

export function canViewPage(role, pageId) {
  if (!role) return false
  return (PAGE_VIEWS[pageId] || [pageId]).some((id) => allows(role, id))
}

export function can(role, action) {
  return !!role && (ACTIONS[action] || []).includes(role)
}
