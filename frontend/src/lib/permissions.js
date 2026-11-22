// One place that says what each role may see and do. The backend still enforces every rule;
// this keeps the UI honest (no buttons that only fail after a click).

export const ROLE_PAGES = {
  viewer: new Set(['overview', 'live', 'map', 'alerts']),
  operator: new Set(['overview', 'live', 'map', 'detection', 'alerts', 'incidents', 'evidence', 'faces', 'analytics', 'reports', 'cameras']),
  police: new Set(['overview', 'live', 'map', 'alerts', 'incidents']),
  investigator: new Set(['overview', 'alerts', 'incidents', 'evidence', 'faces', 'watchlist', 'vehicles', 'analytics', 'reports']),
  supervisor: null,   // null = every page
  admin: null,
}

const ACTIONS = {
  // Alerts, cameras, status, evidence, analytics: the backend's ROLES_OPS (operator_or_admin).
  'data.view': ['operator', 'supervisor', 'admin', 'police', 'investigator'],
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
  analytics: ['analytics', 'detection'],
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
