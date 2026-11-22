import { useState, useEffect, useCallback, useMemo, useRef, lazy, Suspense } from 'react'
import {
  login, signOut, currentUser, fetchAlerts, fetchSystemStatus,
  fetchKnownPersons, fetchEvidence, fetchMapCameras, fetchMapEvents,
  fetchIncidentReport, fetchCameras, fetchAnalyticsSummary,
  fetchAnalyticsTrends, fetchAnalyticsLocations, fetchVehiclePlates,
  fetchVehicleDetections, fetchAuditLogs, fetchMe, fetchStreamingCameras,
  fetchReviewCount, acknowledgeAlert, refreshSession, fetchCameraDevices, fetchCameraPower,
} from './services/api'
import { useToast } from './components/Toast'
import { ProfileModal } from './components/ProfileModal'
import { parseTs } from './lib/time'
import { useWebSocket } from './hooks/useWebSocket'
import { useAutoAlerts } from './hooks/useAutoAlerts'
import { can, canViewPage, PAGE_VIEWS } from './lib/permissions'
import { buildCamList } from './lib/cameras'
import { Card, Empty, Icons, Pill, Seg } from './components/ui'
import { CommandPalette } from './components/CommandPalette'
import { NotificationDrawer } from './components/NotificationDrawer'
import { Copilot } from './components/Copilot'
import { AccountMenu, AskBar, Clock } from './components/Workspace'
import { Sidebar } from './components/Sidebar'
import { PinnedCamera } from './components/PinnedCamera'
import { CriticalAlertBanner } from './components/CriticalAlertBanner'
import { SystemStatus } from './components/SystemStatus'
import { Overview } from './pages/Overview'

// Every other page loads on first visit: the sign-in bundle stays small and Leaflet comes with the map.
const lazyPage = (load, name) => lazy(() => load().then((m) => ({ default: m[name] })))
const LiveMonitoring = lazyPage(() => import('./pages/LiveMonitoring'), 'LiveMonitoring')
const MapPage = lazyPage(() => import('./pages/MapPage'), 'MapPage')
const DetectionCenter = lazyPage(() => import('./pages/DetectionCenter'), 'DetectionCenter')
const Triage = lazyPage(() => import('./pages/Triage'), 'Triage')
const Incidents = lazyPage(() => import('./pages/Incidents'), 'Incidents')
const Cameras = lazyPage(() => import('./pages/Cameras'), 'Cameras')
const Analytics = lazyPage(() => import('./pages/Analytics'), 'Analytics')
const EvidencePage = lazyPage(() => import('./pages/EvidencePage'), 'EvidencePage')
const Watchlist = lazyPage(() => import('./pages/Watchlist'), 'Watchlist')
const FaceRegistryPage = lazyPage(() => import('./pages/FaceRegistryPage'), 'FaceRegistryPage')
const Vehicles = lazyPage(() => import('./pages/Vehicles'), 'Vehicles')
const Reports = lazyPage(() => import('./pages/Reports'), 'Reports')
const Responder = lazyPage(() => import('./pages/Responder'), 'Responder')
const ShiftLog = lazyPage(() => import('./pages/ShiftLog'), 'ShiftLog')
const Users = lazyPage(() => import('./pages/Users'), 'Users')
const Settings = lazyPage(() => import('./pages/Settings'), 'Settings')
const ZoneEditor = lazyPage(() => import('./pages/ZoneEditor'), 'ZoneEditor')

// Names are what an operator would call the page; `desc` is the one line shown under its title.
const NAV = [
  {
    group: 'Monitor',
    pages: [
      { id: 'overview', label: 'Home', desc: 'What needs you right now, and how the system is doing.', icon: Icons.overview },
      { id: 'live', label: 'Live cameras', desc: 'Watch every camera as it happens.', icon: Icons.live },
      { id: 'map', label: 'Map', desc: 'Where your cameras are and where alerts came from.', icon: Icons.map },
    ],
  },
  {
    group: 'Respond',
    pages: [
      { id: 'alerts', label: 'Alerts', desc: 'Go through alerts one at a time and decide what happens next.', icon: Icons.alert },
      { id: 'respond', label: 'Responders', desc: 'Alerts to go to: directions, and on my way / on scene / resolved.', icon: Icons.dispatch },
      { id: 'incidents', label: 'Incidents', desc: 'Cases opened from alerts, and where each one stands.', icon: Icons.incident },
      { id: 'evidence', label: 'Evidence', desc: 'Snapshots and clips saved from detections.', icon: Icons.evidence },
      { id: 'shift', label: 'Shift log', desc: 'Notes during the shift, and the handover to the next one.', icon: Icons.clock },
    ],
  },
  {
    group: 'Investigate',
    pages: [
      { id: 'faces', label: 'People', desc: 'Who the system can recognise, and where watchlist people were seen.', icon: Icons.users },
      { id: 'vehicles', label: 'Vehicles', desc: 'Number plates read by the cameras.', icon: Icons.vehicle },
      { id: 'analytics', label: 'Analytics', desc: 'Trends over time, and everything the cameras detected.', icon: Icons.chart },
      { id: 'reports', label: 'Reports', desc: 'Summaries you can print or export.', icon: Icons.report },
    ],
  },
  {
    group: 'Set up',
    pages: [
      { id: 'cameras', label: 'Cameras', desc: 'Add cameras and check that each one is streaming.', icon: Icons.camera },
      { id: 'zones', label: 'Zones', desc: 'Draw the areas and lines each camera should watch.', icon: Icons.zone },
      { id: 'users', label: 'Users', desc: 'Who can sign in and what they are allowed to do.', icon: Icons.users },
      { id: 'settings', label: 'Settings', desc: 'Detection, notification and system options.', icon: Icons.settings },
    ],
  },
]
const ALL_PAGES = NAV.flatMap((g) => g.pages)
// The pages used every shift: the phone's bottom tab bar (the sidebar has them all).
const TAB_PAGES = ['overview', 'live', 'alerts', 'map'].map((id) => ALL_PAGES.find((p) => p.id === id))
// Officers on the move start from their responder list.
const POLICE_TABS = ['respond', 'alerts', 'map', 'overview'].map((id) => ALL_PAGES.find((p) => p.id === id))
// Views inside a page (PAGE_VIEWS). An old link (#/watchlist, #/detection) opens its view.
const VIEW_LABELS = { faces: 'Registry', watchlist: 'Watchlist sightings', analytics: 'Trends', detection: 'Detection history' }
// Views the search palette lists by their old names, so "watchlist" still finds them.
const PALETTE_VIEWS = [
  { id: 'watchlist', label: 'Watchlist sightings', desc: 'Where watchlist people were seen (People page).', icon: Icons.watchlist },
  { id: 'detection', label: 'Detection history', desc: 'Everything the cameras detected (Analytics page).', icon: Icons.ai },
]
const VIEW_HOME = Object.fromEntries(Object.entries(PAGE_VIEWS).flatMap(([home, views]) => views.map((v) => [v, home])))
const THREAT = {
  low: { tone: 'ok', label: 'Threat level low' },
  high: { tone: 'warn', label: 'Threat level elevated' },
  critical: { tone: 'danger', label: 'Threat level critical' },
}

function routeFromHash() {
  const [path, query = ''] = (window.location.hash || '#/overview').replace('#/', '').split('?')
  const view = new URLSearchParams(query).get('view') || (VIEW_HOME[path] ? path : null)
  const id = VIEW_HOME[path] || path
  return ALL_PAGES.some((p) => p.id === id) ? { page: id, view } : { page: 'overview', view: null }
}

/** A page made of views: tabs for the ones this role may open, then the chosen view. */
function ViewSwitch({ pageId, view, onView, role, ctx }) {
  const views = PAGE_VIEWS[pageId].filter((v) => canViewPage(role, v))
  const current = views.includes(view) ? view : views[0]
  const Current = VIEW_COMPONENTS[current]
  return (
    <>
      {views.length > 1 && (
        <div className="view-switch">
          <Seg value={current} onChange={onView} options={views.map((v) => ({ value: v, label: VIEW_LABELS[v] }))} />
        </div>
      )}
      <Current ctx={ctx} />
    </>
  )
}

function normalizeTheme(t) {
  return t === 'light' ? 'light' : 'dark'
}

function applyTheme(t) {
  const theme = normalizeTheme(t)
  document.documentElement.setAttribute('data-theme', theme)
  document.documentElement.style.colorScheme = theme
  try { localStorage.setItem('ai_sss_theme', theme) } catch { /* ignore */ }
  return theme
}

const PAGE_COMPONENTS = {
  overview: Overview, live: LiveMonitoring, map: MapPage,
  alerts: Triage, respond: Responder, incidents: Incidents, evidence: EvidencePage, shift: ShiftLog,
  vehicles: Vehicles, reports: Reports,
  cameras: Cameras, zones: ZoneEditor, users: Users, settings: Settings,
}
const VIEW_COMPONENTS = {
  faces: FaceRegistryPage, watchlist: Watchlist, analytics: Analytics, detection: DetectionCenter,
}

function formatEvent(evt) {
  const type = evt.alert_type || evt.event_type || 'EVENT'
  const msg = evt.message || evt.person_name || evt.data?.criminal_name || type.replace(/_/g, ' ')
  return {
    id: evt.alert_id ?? evt.id ?? null,
    acknowledged: evt.acknowledged ?? false,
    dismissed: evt.dismissed ?? false,
    type, msg,
    severity: evt.severity || 'info',
    time: evt.timestamp,
    camera: evt.camera_location || evt.camera_id,
    cameraId: evt.camera_id,
    cameraName: evt.camera_name || evt.data?.camera_name,
    personName: evt.person_name,
    lat: evt.camera_lat ?? evt.data?.camera_lat,
    lng: evt.camera_lng ?? evt.data?.camera_lng,
    mapsUrl: evt.maps_url ?? evt.data?.maps_url,
    assignedOfficers: evt.assigned_officers ?? evt.data?.assigned_officers ?? [],
  }
}

// Demo button on the sign-in page, only when both values are set at build time: local dev reads
// frontend/.env.development.local (gitignored); Docker passes DEMO_LOGIN_* from .env. The password
// ends up in the bundle, so this is for demos, never for a deployment others can reach.
const DEMO_LOGIN = import.meta.env.VITE_DEMO_USERNAME && import.meta.env.VITE_DEMO_PASSWORD
  ? { username: import.meta.env.VITE_DEMO_USERNAME, password: import.meta.env.VITE_DEMO_PASSWORD }
  : null

function LoginForm({ onLogin, theme, setTheme, notice }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(notice || '')
  const [loading, setLoading] = useState(false)

  const signIn = async (user, pass) => {
    setLoading(true); setError('')
    try {
      await onLogin(user, pass)
    } catch (err) {
      setError(err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    signIn(username, password)
  }

  return (
    <div className="login-screen">
      <button
        type="button"
        className="icon-btn login-theme-btn"
        title="Toggle theme"
        aria-label="Toggle theme"
        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      >
        {theme === 'dark' ? <Icons.sun /> : <Icons.moon />}
      </button>
      <form className="login-card" onSubmit={handleSubmit}>
        <span className="brand-logo" aria-hidden="true">
          <img src="/logo.svg" alt="" width="46" height="46" />
        </span>
        <h1>Sign in to Aegis</h1>
        <p className="login-sub">Your cameras, alerts and evidence in one place.</p>
        {error && <div className="login-error" role="alert">{error}</div>}
        <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
        <button type="submit" className="btn btn-primary" disabled={loading || !username || !password}>{loading ? 'Signing in…' : 'Sign in'}</button>
        {DEMO_LOGIN && (
          <button type="button" className="btn login-demo-btn" disabled={loading} onClick={() => signIn(DEMO_LOGIN.username, DEMO_LOGIN.password)}>Use the demo account</button>
        )}
      </form>
    </div>
  )
}

function App() {
  const { push: toast } = useToast()
  // null while the session cookie is checked at start-up (scripts cannot read it).
  const [authed, setAuthed] = useState(null)
  const [me, setMe] = useState(null)
  useEffect(() => {
    currentUser().then((u) => { if (u) setMe(u); setAuthed(!!u) })
  }, [])
  const doSignOut = () => { signOut(); setMe(null); setAuthed(false) }
  const [sessionNotice, setSessionNotice] = useState('')
  const [route, setRoute] = useState(routeFromHash)
  const { page, view } = route
  // `id` may be a view (watchlist, detection): it opens the page that holds it.
  const setPage = (id, nextView = null) => {
    const home = VIEW_HOME[id] || id
    const v = nextView || (VIEW_HOME[id] ? id : null)
    setRoute({ page: home, view: v })
    window.history.pushState(null, '', `#/${home}${v ? `?view=${v}` : ''}`)
  }
  const [theme, setThemeState] = useState(() => {
    try {
      return applyTheme(localStorage.getItem('ai_sss_theme') || 'dark')
    } catch {
      return applyTheme('dark')
    }
  })

  const [events, setEvents] = useState([])
  const [systemStatus, setSystemStatus] = useState(null)

  const [clearedAt, setClearedAt] = useState(0)
  const [nowTick, setNowTick] = useState(() => Date.now())   // re-evaluates the 15-min window
  const [reviewPending, setReviewPending] = useState(0)
  const [escalation, setEscalation] = useState({ after: 0, types: [] })   // backup paging limit, for queue timers
  const [knownPersons, setKnownPersons] = useState([])
  const [evidence, setEvidence] = useState([])
  const reloadKnownPersons = useCallback(
    () => fetchKnownPersons().then(setKnownPersons).catch(() => {}), [])
  const [mapCameras, setMapCameras] = useState([])
  const [mapEvents, setMapEvents] = useState([])
  const [cameras, setCameras] = useState([])
  const [report, setReport] = useState(null)
  const [summary, setSummary] = useState(null)
  const [trends, setTrends] = useState([])
  const [locations, setLocations] = useState([])
  const [plates, setPlates] = useState([])
  const [vehicleDetections, setVehicleDetections] = useState([])
  const [auditLogs, setAuditLogs] = useState([])
  const [streamingCams, setStreamingCams] = useState([])

  const [showPalette, setShowPalette] = useState(false)
  const [showProfile, setShowProfile] = useState(false)
  const [mapFocus, setMapFocus] = useState(null)      // {cameraId, lat, lng, t}: which camera the map should show
  const [showNotifs, setShowNotifs] = useState(false)
  const [showCopilot, setShowCopilot] = useState(false)
  const [askQuery, setAskQuery] = useState('')        // question typed in the Home ask bar
  const [showAccount, setShowAccount] = useState(false)
  const [showSystem, setShowSystem] = useState(false)
  // One camera kept on screen across pages (pinned from the Live wall).
  const [pinned, setPinnedState] = useState(() => { try { return localStorage.getItem('aegis_pin') || null } catch { return null } })
  const pinCamera = (id) => {
    setPinnedState(id)
    try { if (id) localStorage.setItem('aegis_pin', id); else localStorage.removeItem('aegis_pin') } catch { /* ignore */ }
  }
  const [liveFocus, setLiveFocus] = useState(null)    // {cameraId, t}: camera to open on the Live page
  // Sidebar: folded to icons on narrow screens unless the operator chose otherwise; set-up group folded.
  const [nav, setNav] = useState(() => {
    const base = { collapsed: window.innerWidth < 1100, setup: false }
    try { return { ...base, ...JSON.parse(localStorage.getItem('aegis_nav') || '{}') } } catch { return base }
  })
  const toggleNav = (key) => {
    const next = { ...nav, [key]: !nav[key] }
    setNav(next)
    try { localStorage.setItem('aegis_nav', JSON.stringify(next)) } catch { /* ignore */ }
  }
  // One card per (type, camera, person): two cameras alerting at once must both stay on screen.
  const [criticalAlerts, setCriticalAlerts] = useState([])
  const alertKey = (a) => `${a.type}|${a.cameraId ?? a.camera}|${a.personName ?? ''}`
  const dropCritical = (key) => setCriticalAlerts((list) => list.filter((a) => alertKey(a) !== key))

  // A camera that keeps firing on something known (a guard, a poster) can be muted for a while:
  // its alerts still reach the queue and the badge, they just stop popping up and ringing.
  const MUTE_MS = 10 * 60 * 1000
  const [muted, setMuted] = useState(() => {
    try { return JSON.parse(localStorage.getItem('aegis_muted_cams') || '{}') } catch { return {} }
  })
  const saveMuted = (next) => {
    setMuted(next)
    try { localStorage.setItem('aegis_muted_cams', JSON.stringify(next)) } catch { /* ignore */ }
  }
  const activeMuted = Object.fromEntries(Object.entries(muted).filter(([, m]) => m.until > nowTick))
  const muteCamera = (alert, now) => {
    const id = alert.cameraId ?? alert.camera
    saveMuted({ ...activeMuted, [id]: { until: now + MUTE_MS, name: alert.cameraName || alert.camera || id } })
    setCriticalAlerts((list) => list.filter((a) => (a.cameraId ?? a.camera) !== id))
    toast(`Pop-ups from ${alert.cameraName || alert.camera || id} muted for 10 minutes. Alerts still go to the queue.`, 'ok')
  }
  const mutedRef = useRef(muted)
  useEffect(() => { mutedRef.current = muted }, [muted])

  const setTheme = (t) => {
    setThemeState(applyTheme(t))
  }
  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  useEffect(() => {
    const onHash = () => { setRoute(routeFromHash()) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    const onAuthExpired = () => {
      setMe(null)
      setSessionNotice('Your session expired. Please sign in again.')
      setAuthed(false)
    }
    window.addEventListener('auth_expired', onAuthExpired)
    return () => window.removeEventListener('auth_expired', onAuthExpired)
  }, [])

  const { handleAlert: handleAutoAlert } = useAutoAlerts((alert) => {
    setCriticalAlerts((list) => [alert, ...list.filter((a) => alertKey(a) !== alertKey(alert))].slice(0, 4))
    // If the operator is already looking at the map, take them to the camera that raised the alert.
    if (page === 'map' && alert.lat != null && alert.lng != null) {
      setMapFocus({ cameraId: alert.cameraId, lat: alert.lat, lng: alert.lng, t: Date.now() })
    }
  })

  const [captureEvent, setCaptureEvent] = useState(null)   // newest capture-basket still
  const handleWsMessage = useCallback((data) => {
    if (data.alert_type === 'PIPELINE_HEARTBEAT') return
    // A still for the capture basket, not an alert: it must not ring or fill the event feed.
    if (data.alert_type === 'ALERT_CAPTURE') { if (data.capture) setCaptureEvent(data.capture); return }
    const formatted = formatEvent(data)
    setEvents((prev) => [formatted, ...prev].slice(0, 200))
    // A police officer is only paged for cameras assigned to them (unassigned alerts reach everyone).
    const assigned = data.assigned_officers || data.data?.assigned_officers || []
    if (me?.role === 'police' && assigned.length && !assigned.some((o) => o.id === me.id)) return
    if ((mutedRef.current[data.camera_id ?? data.camera_location]?.until || 0) > Date.now()) return
    handleAutoAlert(data)
  }, [handleAutoAlert, me])

  const { connected: wsConnected } = useWebSocket('alerts', handleWsMessage, authed && can(me?.role, 'data.view'))
  // A heartbeat updates its camera at once (fps, threat score, red-alert flags), between full polls.
  const streamingRef = useRef(streamingCams)
  useEffect(() => { streamingRef.current = streamingCams }, [streamingCams])
  const lastStreamCheck = useRef(0)
  const handleStatusMessage = useCallback((data) => {
    if (data.alert_type !== 'PIPELINE_HEARTBEAT' || !data.camera_id) return
    const id = data.camera_id
    setSystemStatus((s) => s && {
      ...s,
      online: true,
      last_heartbeat: data.timestamp ?? s.last_heartbeat,
      cameras: {
        ...s.cameras,
        [id]: {
          ...s.cameras?.[id],
          camera_location: data.camera_location,
          fps: data.fps,
          threat_score: data.threat_score,
          flags: data.flags ?? s.cameras?.[id]?.flags ?? [],
          infer_ms: data.infer_ms,
          ai_age_s: data.ai_age_s,
          last_seen: data.timestamp,
          sla: 'ok',
        },
      },
    })
    // A camera that just came up: fetch the streaming list now rather than at the next poll.
    if (!streamingRef.current.includes(id) && Date.now() - lastStreamCheck.current > 5000) {
      lastStreamCheck.current = Date.now()
      fetchStreamingCameras().then((r) => setStreamingCams(r.cameras || [])).catch(() => {})
    }
  }, [])
  const { connected: statusWsConnected } = useWebSocket('status', handleStatusMessage, authed && can(me?.role, 'data.view'))

  const reloadVehicles = useCallback(() => {
    fetchVehiclePlates().then(setPlates).catch(() => {})
    fetchVehicleDetections().then(setVehicleDetections).catch(() => {})
  }, [])

  /* Keep the session alive while the dashboard is open (a wall display must not log itself out) */
  useEffect(() => {
    if (!authed) return undefined
    refreshSession()
    const t = setInterval(refreshSession, 15 * 60 * 1000)
    const onVisible = () => { if (document.visibilityState === 'visible') refreshSession() }
    document.addEventListener('visibilitychange', onVisible)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onVisible) }
  }, [authed])

  /* Initial data load + status polling */
  const [loadFailed, setLoadFailed] = useState([])       // labels of preload requests that failed
  const [apiDown, setApiDown] = useState(false)          // status polling failed repeatedly
  const [reloadTick, setReloadTick] = useState(0)

  useEffect(() => {
    if (!authed) return
    fetchMe().then(setMe).catch(() => setLoadFailed((f) => [...new Set([...f, 'profile'])]))
  }, [authed, reloadTick])

  // Only ask for what this role may read: a 403 here used to show "Some data could not be loaded".
  const role = me?.role
  const ops = can(role, 'data.view')
  const sees = useCallback((...ids) => ids.some((id) => canViewPage(role, id)), [role])

  useEffect(() => {
    if (!authed || !role) return
    if (!ops) return
    const failed = new Set()
    const load = (label, promise, apply) => promise.then(apply).catch(() => {
      failed.add(label)
      setLoadFailed([...failed])
    })
    load('alerts', fetchAlerts(50), (alerts) => setEvents(alerts.map((a) => formatEvent(a))))
    load('cameras', fetchCameras(), setCameras)
    load('map cameras', fetchMapCameras(), setMapCameras)
    load('evidence', fetchEvidence(60), setEvidence)
    load('summary', fetchAnalyticsSummary(24), setSummary)
    load('trends', fetchAnalyticsTrends(7), setTrends)
    load('locations', fetchAnalyticsLocations(24), setLocations)
    if (sees('map')) load('map events', fetchMapEvents(24), setMapEvents)
    if (sees('faces', 'watchlist')) load('persons', fetchKnownPersons(), setKnownPersons)
    if (sees('reports', 'analytics', 'incidents')) load('report', fetchIncidentReport(24), setReport)
    if (can(role, 'audit.view')) load('audit log', fetchAuditLogs(50), setAuditLogs)
    if (sees('vehicles')) reloadVehicles()
  }, [authed, role, ops, sees, reloadVehicles, reloadTick])

  /* Status: heartbeats arrive on the status socket (see onStatusMessage); this full poll only
     picks up what heartbeats don't carry (offline cameras, model health, which cameras stream). */
  useEffect(() => {
    if (!authed || !ops) return undefined
    let misses = 0
    const poll = () => {
      fetchSystemStatus().then((s) => { misses = 0; setApiDown(false); setSystemStatus(s) }).catch(() => {
        misses += 1
        if (misses >= 2) setApiDown(true)
      })
      fetchStreamingCameras().then((r) => setStreamingCams(r.cameras || [])).catch(() => {})
    }
    poll()
    const interval = setInterval(poll, 10000)
    return () => clearInterval(interval)
  }, [authed, ops, reloadTick])

  /* Refresh page-specific data when navigating */
  useEffect(() => {
    if (!authed || !ops || !canViewPage(role, page)) return
    if (page === 'faces') fetchKnownPersons().then(setKnownPersons).catch(() => {})
    if (page === 'evidence' || page === 'faces') fetchEvidence(60).then(setEvidence).catch(() => {})
    if (page === 'map') {
      fetchMapCameras().then(setMapCameras).catch(() => {})
      fetchMapEvents(24).then(setMapEvents).catch(() => {})
    }
    if (page === 'analytics' || page === 'overview') {
      fetchAnalyticsSummary(24).then(setSummary).catch(() => {})
      fetchAnalyticsTrends(7).then(setTrends).catch(() => {})
      fetchAnalyticsLocations(24).then(setLocations).catch(() => {})
    }
    if (page === 'cameras') fetchCameras().then(setCameras).catch(() => {})
    if (page === 'vehicles') reloadVehicles()
    if (page === 'users' && can(role, 'audit.view')) fetchAuditLogs(50).then(setAuditLogs).catch(() => {})
    if (page === 'reports') fetchIncidentReport(24).then(setReport).catch(() => {})
  }, [authed, ops, role, page, reloadVehicles])

  /* Keyboard shortcuts */
  useEffect(() => {
    const onKey = (e) => {
      // Never hijack typing: plain-letter shortcuts must not fire inside form fields.
      const t = e.target
      const typing = t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)
      if (typing && !((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') && e.key !== 'Escape') return
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setShowPalette((v) => !v)
      } else if (e.key.toLowerCase() === 'n' && !e.metaKey && !e.ctrlKey) {
        setShowNotifs((v) => !v)
      } else if (e.key.toLowerCase() === 'c' && !e.metaKey && !e.ctrlKey) {
        setShowCopilot((v) => !v)
      } else if (e.key === 'Escape') {
        setShowPalette(false); setShowNotifs(false); setShowCopilot(false); setShowAccount(false); setShowSystem(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    const t = setInterval(() => setNowTick(Date.now()), 30000)
    return () => clearInterval(t)
  }, [])

  const refreshReviewCount = useCallback(() => {
    fetchReviewCount().then((r) => {
      setReviewPending(r.pending || 0)
      setEscalation({ after: r.escalate_after_seconds ?? 0, types: r.escalated_types || [] })
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!authed || !ops) return undefined
    refreshReviewCount()
    const t = setInterval(refreshReviewCount, 15000)
    return () => clearInterval(t)
  }, [authed, ops, refreshReviewCount])

  const reloadCameras = useCallback(() => {
    fetchCameras().then(setCameras).catch(() => {})
  }, [])

  // Cameras plugged into this computer right now. Polled, so plugging one in or out shows up by itself.
  // `power`: which cameras are switched on. Shared by every camera view so a stopped camera
  // reads "Off" everywhere, and polled so a change made elsewhere (or a new camera) shows up.
  const [devices, setDevices] = useState({ devices: [], unplugged: [] })
  const [power, setPower] = useState({})
  useEffect(() => {
    if (!authed || !can(me?.role, 'camera.power')) return undefined    // operational roles only (403 otherwise)
    const load = () => {
      fetchCameraDevices().then(setDevices).catch(() => {})
      fetchCameraPower().then(setPower).catch(() => {})
    }
    load()
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [authed, me?.role, cameras])
  const camList = useMemo(() => buildCamList(cameras, systemStatus, streamingCams, power, devices.unplugged),
    [cameras, systemStatus, streamingCams, power, devices.unplugged])
  // A camera picked anywhere (Home tiles, map) opens on the Live page.
  const openCamera = (cameraId) => { setLiveFocus({ cameraId, t: Date.now() }); setPage('live') }

  /* Page grids follow the centre panel's width (see .center[data-w] in index.css). */
  const centerRef = useRef(null)
  useEffect(() => {
    const el = centerRef.current
    if (!el) return undefined
    const ro = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width
      el.dataset.w = w < 700 ? 'sm' : w < 1040 ? 'md' : 'lg'
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [authed])

  /* Threat level is derived, so it falls back by itself once alerts are handled:
     unhandled alerts from the last 15 minutes, or a hot camera score from the pipeline. */
  const threatLevel = useMemo(() => {
    const cutoff = Math.max(nowTick - 15 * 60 * 1000, clearedAt)
    const live = events.filter((e) => {
      const t = parseTs(e.time)?.getTime() || 0
      return t >= cutoff && !e.acknowledged && !e.dismissed
    })
    const maxScore = Math.max(0, ...Object.values(systemStatus?.cameras || {}).map((c) => c.threat_score || 0))
    if (live.some((e) => e.severity === 'critical') || maxScore >= 50) return 'critical'
    if (live.some((e) => e.severity === 'high') || maxScore >= 20) return 'high'
    return 'low'
  }, [events, systemStatus, clearedAt, nowTick])

  if (authed === null) return <div className="login-screen" aria-busy="true" />
  if (!authed) {
    return (
      <LoginForm
        theme={theme}
        setTheme={setTheme}
        notice={sessionNotice}
        onLogin={async (u, p) => { await login(u, p); setSessionNotice(''); setAuthed(true) }}
      />
    )
  }

  const ackCritical = async (alert) => {
    try {
      await acknowledgeAlert(alert.alertId)
      dropCritical(alertKey(alert))
    } catch (e) {
      toast(e.message || 'Could not acknowledge', 'danger')
    }
  }

  const criticalEvents = events.filter((e) => e.severity === 'critical' && !e.acknowledged && !e.dismissed)
  const activePage = ALL_PAGES.find((p) => p.id === page)
  const PageComponent = PAGE_COMPONENTS[page]
  // One number for "alerts that need someone": every badge and summary uses it.
  const alertCount = reviewPending
  const allowed = !me || canViewPage(me.role, page)
  // While the profile loads (role unknown) show no pages instead of flashing the admin set.
  const tabPages = (me?.role === 'police' ? POLICE_TABS : TAB_PAGES).filter((p) => canViewPage(me?.role, p.id))
  const navGroups = NAV.map((g) => ({ ...g, pages: g.pages.filter((p) => canViewPage(me?.role, p.id)) })).filter((g) => g.pages.length)

  const ctx = {
    events, setEvents, systemStatus, threatLevel, wsConnected,
    knownPersons, reloadKnownPersons, evidence, mapCameras, mapEvents, cameras,
    report, summary, trends, locations,
    plates, vehicleDetections, auditLogs, reloadVehicles,
    me, streamingCams, reloadCameras, setPage, mapFocus, liveFocus, unplugged: devices.unplugged, power, setPower,
    reviewPending, refreshReviewCount, captureEvent, openCamera, camList, escalation, pinned, pinCamera,
    showOnMap: (c) => { setMapFocus({ cameraId: c.camera_id, lat: c.lat, lng: c.lng, t: Date.now() }); setPage('map') },
    theme, setTheme,
  }

  return (
    <div className={`shell ${threatLevel === 'critical' ? 'threat-critical' : ''} ${pinned && page !== 'live' && camList.some((c) => c.camera_id === pinned) ? 'has-pip' : ''}`}>
      {criticalAlerts.length > 0 && (
        <div className="critical-stack">
          {criticalAlerts.map((a, i) => (
            <CriticalAlertBanner key={alertKey(a)} alert={a} repeatSound={i === 0}
              onDismiss={() => dropCritical(alertKey(a))} onViewMap={() => {
                setMapFocus({ cameraId: a.cameraId, lat: a.lat, lng: a.lng, t: Date.now() })
                setPage('map'); dropCritical(alertKey(a))
              }} onOpenAlerts={() => { setPage('alerts'); dropCritical(alertKey(a)) }}
              onAcknowledge={() => ackCritical(a)} onMuteCamera={() => muteCamera(a, Date.now())} />
          ))}
        </div>
      )}
      <Sidebar
        groups={navGroups} page={page} setPage={setPage}
        badges={{ alerts: alertCount }} alerting={criticalEvents.length > 0}
        collapsed={nav.collapsed} onToggleCollapsed={() => toggleNav('collapsed')}
        setupOpen={nav.setup} onToggleSetup={() => toggleNav('setup')}
      />

      <div className="main-col">
      <header className="appbar">
        <span className="brand-logo appbar-logo" aria-hidden="true"><img src="/logo.svg" alt="" width="30" height="30" /></span>
        <div className="appbar-title">
          <h1>{activePage?.label}</h1>
          <p>{activePage?.desc}</p>
        </div>
        <div className="appbar-right">
          <div className="status-rail" aria-label="System status">
            <Pill tone={THREAT[threatLevel].tone}>{THREAT[threatLevel].label}</Pill>
            {ops && (
              <SystemStatus connected={wsConnected && statusWsConnected} status={systemStatus} camList={camList}
                open={showSystem} setOpen={setShowSystem} />
            )}
            {Object.keys(activeMuted).length > 0 && (
              <button type="button" className="pill pill-warn pill-btn" onClick={() => saveMuted({})}
                title={`Muted: ${Object.values(activeMuted).map((m) => `${m.name} (${Math.ceil((m.until - nowTick) / 60000)} min)`).join(', ')}. Click to unmute.`}>
                <span className="dot" />{Object.keys(activeMuted).length} camera{Object.keys(activeMuted).length === 1 ? '' : 's'} muted · Unmute
              </button>
            )}
          </div>
          <Clock />
          <button
            type="button"
            className="searchbox"
            onClick={() => setShowPalette(true)}
            aria-label="Search pages and actions"
          >
            <Icons.search />
            <span>Search</span>
            <kbd>⌘K</kbd>
          </button>
          <div className="row" style={{ gap: 2 }}>
            <button type="button" className="icon-btn" title="Quick answers (C)" aria-label="Quick answers" onClick={() => setShowCopilot(true)}><Icons.bot /></button>
            <button type="button" className="icon-btn has-badge" title="Notifications" aria-label="Notifications" onClick={() => setShowNotifs(true)}>
              <Icons.bell />
              {alertCount > 0 && <span className="nav-badge">{alertCount}</span>}
            </button>
            <button
              type="button"
              className="icon-btn"
              title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              aria-label="Toggle theme"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            >
              {theme === 'dark' ? <Icons.sun /> : <Icons.moon />}
            </button>
          </div>
          <AccountMenu
            me={me} open={showAccount} setOpen={setShowAccount}
            items={[
              { label: 'My account', icon: Icons.users, run: () => setShowProfile(true) },
              ...['users', 'settings'].filter((id) => canViewPage(me?.role, id)).map((id) => {
                const p = ALL_PAGES.find((x) => x.id === id)
                return { label: p.label, icon: p.icon, run: () => setPage(id) }
              }),
            ]}
            onSignOut={doSignOut}
          />
        </div>
      </header>

      <main className={`center ${page === 'overview' ? 'has-ask' : ''}`} ref={centerRef}>
          <div className="page" key={page}>
            {(apiDown || loadFailed.length > 0) && (
              <div className="conn-banner" role="status">
                <span>
                  {apiDown
                    ? 'Cannot reach the server. Showing the last data received and retrying.'
                    : `Some data could not be loaded (${loadFailed.join(', ')}).`}
                </span>
                <button className="btn btn-sm" onClick={() => { setLoadFailed([]); setReloadTick((t) => t + 1) }}>Retry now</button>
              </div>
            )}
            <div className="page-view">
              {allowed ? (
                <>
                  <Suspense fallback={<Empty icon={activePage?.icon || Icons.overview}>Loading…</Empty>}>
                    {PAGE_VIEWS[page]
                      ? <ViewSwitch pageId={page} view={view} onView={(v) => setPage(page, v)} role={me?.role} ctx={ctx} />
                      : <PageComponent ctx={ctx} />}
                  </Suspense>
                </>
              ) : (
                <Card title="You don't have access to this page" sub={`The ${me.role} role cannot open it`}>
                  <Empty icon={Icons.shield}>Ask an administrator if you need access.</Empty>
                </Card>
              )}
            </div>
          </div>

          {page === 'overview' && (
            <AskBar liveCount={camList.filter((c) => c.status === 'live').length} onAsk={(q) => { setAskQuery(q); setShowCopilot(true) }} />
          )}

          <nav className="tabbar" aria-label="Main">
            {tabPages.map((p) => {
              const Icon = p.icon
              return (
                <button
                  key={p.id}
                  type="button"
                  className={`tab ${page === p.id ? 'active' : ''}`}
                  aria-current={page === p.id ? 'page' : undefined}
                  data-alert-nav={p.id === 'alerts' && criticalEvents.length > 0 ? 'true' : undefined}
                  onClick={() => setPage(p.id)}
                >
                  <Icon />
                  {p.label.split(' ')[0]}
                  {p.id === 'alerts' && alertCount > 0 && <span className="nav-badge">{alertCount}</span>}
                </button>
              )
            })}
            <button type="button" className="tab" onClick={() => setShowPalette(true)}>
              <Icons.menu />
              More
            </button>
          </nav>
      </main>
      </div>

      {(() => {
        const cam = pinned && page !== 'live' && camList.find((c) => c.camera_id === pinned)
        return cam ? <PinnedCamera cam={cam} onOpen={() => openCamera(cam.camera_id)} onClose={() => pinCamera(null)} /> : null
      })()}

      {showPalette && (
        <CommandPalette
          pages={[...ALL_PAGES, ...PALETTE_VIEWS].filter((p) => canViewPage(me?.role, p.id))}
          actions={[
            { id: 'act-theme', label: `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`, icon: theme === 'dark' ? Icons.sun : Icons.moon, hint: 'Action', run: () => setTheme(theme === 'dark' ? 'light' : 'dark') },
            { id: 'act-copilot', label: 'Quick answers', icon: Icons.bot, hint: 'Action', run: () => setShowCopilot(true) },
            { id: 'act-notifs', label: 'Open notifications', icon: Icons.bell, hint: 'Action', run: () => setShowNotifs(true) },
            { id: 'act-profile', label: 'Change my password', icon: Icons.users, hint: 'Action', run: () => setShowProfile(true) },
            { id: 'act-logout', label: 'Sign out', icon: Icons.logout, hint: 'Action', run: doSignOut },
          ]}
          onNavigate={setPage}
          onClose={() => setShowPalette(false)}
        />
      )}
      {showProfile && <ProfileModal me={me} onClose={() => setShowProfile(false)} />}
      {showNotifs && (
        <NotificationDrawer events={events} onClose={() => setShowNotifs(false)} onClear={() => { setEvents([]); setClearedAt(Date.now()) }} />
      )}
      {showCopilot && (
        <Copilot ctx={{ events, summary, cameras, threatLevel, locations }} initialQuery={askQuery} onClose={() => { setShowCopilot(false); setAskQuery('') }} />
      )}
    </div>
  )
}

export default App


