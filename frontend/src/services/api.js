const API_BASE = import.meta.env.VITE_API_URL || '/api/v1';

// The session is an httpOnly cookie set by the server at sign-in: scripts never see the token,
// and every request (fetch, <img>, MJPEG, WebSocket) carries it by itself.
// Older versions kept the token in localStorage; drop any copy left behind.
try { localStorage.removeItem('ai_sss_token') } catch { /* ignore */ }

async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !headers['Content-Type'] && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  const res = await fetch(`${API_BASE}${path}`, { credentials: 'include', ...options, headers });
  if (!res.ok) {
    if (res.status === 401 && !path.includes('/auth/login')) {
      // Dispatch auth_expired event instead of abruptly reloading
      window.dispatchEvent(new Event('auth_expired'));
    }
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const d = err.detail;
    throw new Error((typeof d === 'object' && d ? d.message : d) || 'Request failed');
  }
  // DELETE and some PUT routes answer with no body.
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new Error('The server sent a response the dashboard could not read');
  }
}

export async function login(username, password) {
  return apiFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
}

/** The signed-in user, or null. For start-up: a missing session is not "expired". */
export async function currentUser() {
  const res = await fetch(`${API_BASE}/auth/me`, { credentials: 'include' }).catch(() => null);
  return res?.ok ? res.json() : null;
}

export async function signOut() {
  await apiFetch('/auth/logout', { method: 'POST' }).catch(() => {});
}

/** Renew the session cookie. Ignored if it fails: the next real request reports expiry. */
export async function refreshSession() {
  try {
    await apiFetch('/auth/refresh', { method: 'POST' });
  } catch { /* handled by the 401 flow */ }
}

export async function fetchAlerts(limit = 20) {
  return apiFetch(`/alerts/?limit=${limit}`);
}

export async function fetchAlertsFiltered({ reviewStatus, dismissed, acknowledged, limit = 100 } = {}) {
  const q = new URLSearchParams({ limit });
  if (reviewStatus) q.set('review_status', reviewStatus);
  if (dismissed !== undefined) q.set('dismissed', dismissed);
  if (acknowledged !== undefined) q.set('acknowledged', acknowledged);
  return apiFetch(`/alerts/?${q}`);
}

export async function fetchAlertContext(alertId) {
  return apiFetch(`/alerts/${alertId}/context`);
}

export async function fetchReviewCount() {
  return apiFetch('/alerts/review-queue-count');
}

export async function searchEvents({ since, until, eventTypes, cameraId, limit = 500 } = {}) {
  const q = new URLSearchParams({ limit });
  if (since) q.set('since', since);
  if (until) q.set('until', until);
  if (eventTypes) q.set('event_types', eventTypes);
  if (cameraId) q.set('camera_id', cameraId);
  return apiFetch(`/events/search?${q}`);
}

export async function fetchThresholdSpecs() {
  return apiFetch('/config/thresholds/specs');
}

export async function fetchSystemStatus() {
  return apiFetch('/system/status');
}

export async function fetchCameras() {
  return apiFetch('/cameras/');
}

export async function fetchCameraPower() {
  return apiFetch('/cameras/power');
}

export async function setCameraPower(cameraId, on) {
  return apiFetch(`/cameras/${encodeURIComponent(cameraId)}/power`, {
    method: 'POST',
    body: JSON.stringify({ on }),
  });
}

export async function fetchCameraDevices() {
  return apiFetch('/cameras/devices');
}

export async function resolveIp(url) {
  return apiFetch(`/cameras/resolve-ip?url=${encodeURIComponent(url)}`);
}

export async function addCamera(data) {
  return apiFetch('/cameras/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateCamera(cameraId, patch) {
  return apiFetch(`/cameras/${cameraId}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  });
}

export async function fetchKnownPersons() {
  return apiFetch('/faces/known-persons');
}

export function personImageUrl(imageId) {
  return `${API_BASE}/faces/images/${imageId}`;
}

export async function enrollPerson({ name, category, criminalStatus, threatLevel, notes, files }) {
  const fd = new FormData();
  fd.append('name', name);
  fd.append('category', category);
  fd.append('criminal_status', criminalStatus);
  fd.append('threat_level', String(threatLevel));
  if (notes) fd.append('notes', notes);
  files.forEach((f) => fd.append('files', f));
  return apiFetch('/faces/persons', { method: 'POST', body: fd });
}

export async function addPersonImages(personId, files) {
  const fd = new FormData();
  files.forEach((f) => fd.append('files', f));
  return apiFetch(`/faces/persons/${encodeURIComponent(personId)}/images`, { method: 'POST', body: fd });
}

export async function fetchPersonDetail(personId) {
  return apiFetch(`/faces/persons/${encodeURIComponent(personId)}`);
}

export async function updatePerson(personId, patch) {
  return apiFetch(`/faces/persons/${encodeURIComponent(personId)}`, { method: 'PATCH', body: JSON.stringify(patch) });
}

export async function deletePerson(personId) {
  return apiFetch(`/faces/persons/${encodeURIComponent(personId)}`, { method: 'DELETE' });
}

export async function deletePersonImage(imageId) {
  return apiFetch(`/faces/images/${imageId}`, { method: 'DELETE' });
}

export async function verifyFace(file, personId) {
  const fd = new FormData();
  fd.append('file', file);
  if (personId) fd.append('person_id', personId);
  return apiFetch('/faces/verify', { method: 'POST', body: fd });
}

export async function verifyEvidence(evidenceId) {
  return apiFetch(`/faces/verify-evidence/${evidenceId}`, { method: 'POST' });
}

export async function fetchFaceEncodings() {
  return apiFetch('/faces/');
}

export async function fetchEvidence(limit = 30) {
  return apiFetch(`/evidence/?limit=${limit}`);
}

export async function fetchMapCameras() {
  return apiFetch('/map/cameras');
}

export async function fetchMapEvents(hours = 24, types = '') {
  const q = new URLSearchParams({ hours: String(hours) });
  if (types) q.set('types', types);
  return apiFetch(`/map/events?${q}`);
}

export async function fetchIncidentReport(hours = 24) {
  return apiFetch(`/reports/incident?hours=${hours}`);
}

export async function fetchAnalyticsSummary(hours = 24) {
  return apiFetch(`/analytics/summary?hours=${hours}`);
}

export async function fetchAnalyticsTrends(days = 7) {
  return apiFetch(`/analytics/trends?days=${days}`);
}

export async function fetchAnalyticsLocations(hours = 24) {
  return apiFetch(`/analytics/locations?hours=${hours}`);
}

export async function fetchVehiclePlates(watchlistedOnly = false) {
  return apiFetch(`/vehicles/plates?watchlisted_only=${watchlistedOnly}`);
}

export async function addVehiclePlate(plateNumber, reason) {
  return apiFetch('/vehicles/plates', {
    method: 'POST',
    body: JSON.stringify({ plate_number: plateNumber, reason }),
  });
}

export async function fetchVehicleDetections(limit = 50) {
  return apiFetch(`/vehicles/detections?limit=${limit}`);
}

export async function fetchAuditLogs(limit = 100) {
  return apiFetch(`/audit/?limit=${limit}`);
}

export async function acknowledgeAlert(alertId, { acknowledged = true, dismissed = false, note = null } = {}) {
  return apiFetch(`/alerts/${alertId}/acknowledge`, {
    method: 'PUT',
    body: JSON.stringify({ acknowledged, dismissed, note }),
  });
}

export async function dispatchPolice(alertId) {
  return apiFetch(`/alerts/${alertId}/dispatch`, { method: 'POST' });
}

export async function fetchUsers() {
  return apiFetch('/auth/users');
}

export async function fetchCameraOfficerMap() {
  return apiFetch('/cameras/officers/all');
}

export async function setCameraOfficers(cameraId, userIds) {
  return apiFetch(`/cameras/${encodeURIComponent(cameraId)}/officers`, {
    method: 'PUT',
    body: JSON.stringify({ user_ids: userIds }),
  });
}

export async function createUser({ username, email, password, role, phone }) {
  return apiFetch('/auth/users', {
    method: 'POST',
    body: JSON.stringify({ username, email, password, role, phone: phone || null }),
  });
}

export async function updateUser(userId, patch) {
  return apiFetch(`/auth/users/${userId}`, { method: 'PATCH', body: JSON.stringify(patch) });
}

export async function changePassword(currentPassword, newPassword) {
  const res = await apiFetch('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  // The server revokes every older session on a password change and renews this one's cookie.
  return res;
}

export async function fetchAssignees() {
  return apiFetch('/auth/assignees');
}

export async function fetchMe() {
  return apiFetch('/auth/me');
}

export async function fetchStreamingCameras() {
  return apiFetch('/stream/cameras');
}

/* URL builders for <img> tags: the session cookie authenticates them, no token in the URL */
export function liveStreamUrl(cameraId) {
  return `${API_BASE}/stream/${encodeURIComponent(cameraId)}/live`;
}

export function snapshotUrl(cameraId) {
  return `${API_BASE}/stream/${encodeURIComponent(cameraId)}/snapshot`;
}

export async function fetchCameraGeometry(cameraId) {
  return apiFetch(`/cameras/${encodeURIComponent(cameraId)}/geometry`);
}

export async function saveCameraGeometry(cameraId, { zones, lines }) {
  return apiFetch(`/cameras/${encodeURIComponent(cameraId)}/geometry`, {
    method: 'PUT',
    body: JSON.stringify({ zones, lines }),
  });
}

export function evidenceImageUrl(evidenceId, kind = 'frame') {
  return `${API_BASE}/evidence/${evidenceId}/image?kind=${kind}`;
}

/* ---- Red-alert capture basket ---- */
export async function fetchCaptures(limit = 60) {
  return apiFetch(`/captures/?limit=${limit}`);
}

/* 'red' = red alerts only, 'suspicious' = suspicious people too */
export async function fetchCaptureScope() {
  return apiFetch('/captures/scope');
}

export async function setCaptureScope(scope) {
  return apiFetch('/captures/scope', { method: 'PUT', body: JSON.stringify({ scope }) });
}

export function captureImageUrl(captureId, width) {
  return `${API_BASE}/captures/${captureId}/image${width ? `?w=${width}` : ''}`;
}

/* ---- Incidents ---- */
export async function fetchIncidents({ status, priority, limit = 50 } = {}) {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (status) qs.set('status', status);
  if (priority) qs.set('priority', priority);
  return apiFetch(`/incidents/?${qs}`);
}
export async function fetchIncidentStats() {
  return apiFetch('/incidents/stats');
}
export async function fetchIncident(id) {
  return apiFetch(`/incidents/${id}`);
}
export async function updateIncident(id, patch) {
  return apiFetch(`/incidents/${id}`, { method: 'PUT', body: JSON.stringify(patch) });
}
export async function addIncidentNote(id, body) {
  return apiFetch(`/incidents/${id}/notes`, { method: 'POST', body: JSON.stringify({ body }) });
}
export async function createIncidentFromAlert(alertId) {
  return apiFetch(`/incidents/from-alert/${alertId}`, { method: 'POST' });
}
export async function createIncident(payload) {
  return apiFetch('/incidents/', { method: 'POST', body: JSON.stringify(payload) });
}

/* ---- Custody ---- */
export async function fetchCustody(evidenceId) {
  return apiFetch(`/custody/evidence/${evidenceId}`);
}
export async function verifyCustody(evidenceId) {
  return apiFetch(`/custody/evidence/${evidenceId}/verify`, { method: 'POST' });
}

/* ---- Recordings / timeline ---- */
export async function fetchRecordings({ cameraId, hours = 24 } = {}) {
  const qs = new URLSearchParams({ hours: String(hours) });
  if (cameraId) qs.set('camera_id', cameraId);
  return apiFetch(`/recordings/?${qs}`);
}
export async function fetchTimeline({ cameraId, hours = 24 } = {}) {
  const qs = new URLSearchParams({ hours: String(hours) });
  if (cameraId) qs.set('camera_id', cameraId);
  return apiFetch(`/recordings/timeline?${qs}`);
}
/** The clip is fetched and handed back as a blob URL (one request, then seekable locally). */
export async function openRecordingFile(clipId) {
  const res = await fetch(`${API_BASE}/recordings/${clipId}/file`, { credentials: 'include' });
  if (!res.ok) throw new Error(res.status === 404 ? 'Clip file is missing' : 'Could not open the clip');
  return URL.createObjectURL(await res.blob());
}

/* ---- Re-ID ---- */
export async function fetchReidPersons(hours = 24) {
  return apiFetch(`/reid/persons?hours=${hours}`);
}
export async function fetchReidVehicles(hours = 24) {
  return apiFetch(`/reid/vehicles?hours=${hours}`);
}

/* ---- Integrations ---- */
export async function fetchIntegrationStatus() {
  return apiFetch('/integrations/status');
}
export async function testIntegration(channel, message) {
  return apiFetch('/integrations/test', {
    method: 'POST',
    body: JSON.stringify({ channel, message }),
  });
}

/* ---- Calibration ---- */
export async function fetchCalibrationMetrics(hours = 168) {
  return apiFetch(`/calibration/metrics?hours=${hours}`);
}
export async function addCalibrationLabel(payload) {
  return apiFetch('/calibration/labels', { method: 'POST', body: JSON.stringify(payload) });
}

/* ---- Professional VMS ---- */
export async function fetchVmsStatus() {
  return apiFetch('/vms/status');
}
export async function fetchVmsTimeline({ cameraId, hours = 24, trigger } = {}) {
  const qs = new URLSearchParams({ hours: String(hours) });
  if (cameraId) qs.set('camera_id', cameraId);
  if (trigger) qs.set('trigger', trigger);
  return apiFetch(`/vms/timeline?${qs}`);
}
export async function fetchPtz(cameraId) {
  return apiFetch(`/vms/ptz/${encodeURIComponent(cameraId)}`);
}
export async function ptzMove(cameraId, { pan = 0, tilt = 0, zoom = 0 } = {}) {
  return apiFetch(`/vms/ptz/${encodeURIComponent(cameraId)}/move`, {
    method: 'POST', body: JSON.stringify({ pan, tilt, zoom }),
  });
}
export async function ptzStop(cameraId) {
  return apiFetch(`/vms/ptz/${encodeURIComponent(cameraId)}/stop`, { method: 'POST' });
}
export async function ptzHome(cameraId) {
  return apiFetch(`/vms/ptz/${encodeURIComponent(cameraId)}/home`, { method: 'POST' });
}
export async function ptzSetMode(cameraId, mode) {
  return apiFetch(`/vms/ptz/${encodeURIComponent(cameraId)}/mode`, {
    method: 'POST', body: JSON.stringify({ mode }),
  });
}
export async function ptzSavePreset(cameraId, name) {
  return apiFetch(`/vms/ptz/${encodeURIComponent(cameraId)}/presets`, {
    method: 'POST', body: JSON.stringify({ name }),
  });
}
export async function ptzGotoPreset(cameraId, name) {
  return apiFetch(`/vms/ptz/${encodeURIComponent(cameraId)}/presets/${encodeURIComponent(name)}/goto`, {
    method: 'POST',
  });
}
export async function openVmsPlayback(cameraId, isoTime) {
  const url = `${API_BASE}/vms/playback?camera_id=${encodeURIComponent(cameraId)}&t=${encodeURIComponent(isoTime)}`;
  const res = await fetch(url, { credentials: 'include' });
  if (!res.ok) throw new Error('No recording at this time');
  const blob = await res.blob();
  const seek = res.headers.get('X-Seek-Offset-Seconds');
  return { blobUrl: URL.createObjectURL(blob), seekOffset: seek ? Number(seek) : 0, segmentId: res.headers.get('X-Segment-Id') };
}

export function wsUrl(channel = 'alerts') {
  const base = import.meta.env.VITE_WS_URL
    || `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;
  return `${base}/api/v1/ws/${channel}`;
}




export async function fetchConfigThresholds() {
  return apiFetch('/config/thresholds/all');
}

export async function saveConfigThreshold(key, value) {
  return apiFetch(`/config/threshold.${key}`, {
    method: 'PUT',
    body: JSON.stringify({ value: String(value) }),
  });
}

export async function deleteCamera(cameraId) {
  return apiFetch(`/cameras/${encodeURIComponent(cameraId)}`, { method: 'DELETE' });
}

export async function deleteVehiclePlate(plate) {
  return apiFetch(`/vehicles/plates/${encodeURIComponent(plate)}`, { method: 'DELETE' });
}

export async function fetchLiveAnalytics() {
  return apiFetch('/analytics/live');
}

export async function fetchEvidenceBundle(evidenceIds = []) {
  return apiFetch(`/reports/evidence-bundle?ids=${encodeURIComponent(evidenceIds.join(','))}`);
}
