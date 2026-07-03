const API_BASE = import.meta.env.VITE_API_URL || '/api/v1';

export function getToken() {
  return localStorage.getItem('ai_sss_token');
}

export function setToken(token) {
  localStorage.setItem('ai_sss_token', token);
}

export function clearToken() {
  localStorage.removeItem('ai_sss_token');
}

async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

export async function login(username, password) {
  const data = await apiFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  setToken(data.access_token);
  return data;
}

export async function fetchAlerts(limit = 20) {
  return apiFetch(`/alerts/?limit=${limit}`);
}

export async function fetchSystemStatus() {
  return apiFetch('/system/status');
}

export async function fetchCameras() {
  return apiFetch('/cameras/');
}

export async function fetchKnownPersons() {
  return apiFetch('/faces/known-persons');
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

export async function fetchMapEvents(hours = 24) {
  return apiFetch(`/map/events?hours=${hours}`);
}

export async function fetchIncidentReport(hours = 24) {
  return apiFetch(`/reports/incident?hours=${hours}`);
}

export function wsUrl(channel = 'alerts') {
  const base = import.meta.env.VITE_WS_URL
    || `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;
  const token = getToken();
  const qs = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${base}/api/v1/ws/${channel}${qs}`;
}
