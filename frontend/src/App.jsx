import { useState, useEffect, useCallback } from 'react'
import {
  login, clearToken, getToken, fetchAlerts, fetchSystemStatus,
  fetchKnownPersons, fetchEvidence, fetchMapCameras, fetchMapEvents,
  fetchIncidentReport, fetchCameras, fetchAnalyticsSummary,
  fetchAnalyticsTrends, fetchAnalyticsLocations, fetchVehiclePlates,
  fetchVehicleDetections, fetchAuditLogs, fetchMe, fetchStreamingCameras,
} from './services/api'
import { useWebSocket } from './hooks/useWebSocket'
import { useAutoAlerts } from './hooks/useAutoAlerts'
import { Icons, Pill } from './components/ui'
import { CommandPalette } from './components/CommandPalette'
import { NotificationDrawer } from './components/NotificationDrawer'
import { Copilot } from './components/Copilot'
import { Overview } from './pages/Overview'
import { LiveMonitoring } from './pages/LiveMonitoring'
import { MapPage } from './pages/MapPage'
import { DetectionCenter } from './pages/DetectionCenter'
import { AlertCenter } from './pages/AlertCenter'
import { Incidents } from './pages/Incidents'
import { Cameras } from './pages/Cameras'
import { Analytics } from './pages/Analytics'
import { EvidencePage } from './pages/EvidencePage'
import { Watchlist } from './pages/Watchlist'
import { Vehicles } from './pages/Vehicles'
import { Reports } from './pages/Reports'
import { Users } from './pages/Users'
import { Settings } from './pages/Settings'

const NAV = [
  {
    group: 'Operations',
    pages: [
      { id: 'overview', label: 'Executive Overview', icon: Icons.overview },
      { id: 'live', label: 'Live Monitoring', icon: Icons.live },
      { id: 'map', label: 'GIS Map', icon: Icons.map },
      { id: 'detection', label: 'AI Detection Center', icon: Icons.ai },
    ],
  },
  {
    group: 'Response',
    pages: [
      { id: 'alerts', label: 'Alert Center', icon: Icons.alert },
      { id: 'incidents', label: 'Incidents', icon: Icons.incident },
      { id: 'evidence', label: 'Evidence Center', icon: Icons.evidence },
    ],
  },
  {
    group: 'Intelligence',
    pages: [
      { id: 'watchlist', label: 'Watchlist', icon: Icons.watchlist },
      { id: 'vehicles', label: 'Vehicle Intelligence', icon: Icons.vehicle },
      { id: 'analytics', label: 'Analytics', icon: Icons.chart },
      { id: 'reports', label: 'Reports', icon: Icons.report },
    ],
  },
  {
    group: 'Administration',
    pages: [
      { id: 'cameras', label: 'Camera Management', icon: Icons.camera },
      { id: 'users', label: 'Users & Roles', icon: Icons.users },
      { id: 'settings', label: 'Settings', icon: Icons.settings },
    ],
  },
]
const ALL_PAGES = NAV.flatMap((g) => g.pages)

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
  overview: Overview, live: LiveMonitoring, map: MapPage, detection: DetectionCenter,
  alerts: AlertCenter, incidents: Incidents, evidence: EvidencePage,
  watchlist: Watchlist, vehicles: Vehicles, analytics: Analytics, reports: Reports,
  cameras: Cameras, users: Users, settings: Settings,
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
  }
}

function LoginForm({ onLogin, theme, setTheme }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin123')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true); setError('')
    try {
      await onLogin(username, password)
    } catch (err) {
      setError(err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
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
        <h1><span className="brand-logo">AG</span> Aegis Command Center</h1>
        <p className="login-sub">AI Smart Surveillance · threat detection · GPS dispatch</p>
        {error && <div className="login-error">{error}</div>}
        <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        <button type="submit" className="btn btn-primary" disabled={loading}>{loading ? 'Signing in…' : 'Sign in'}</button>
        <p className="login-hint">Demo: <code>admin</code> / <code>admin123</code></p>
      </form>
    </div>
  )
}

function App() {
  const [authed, setAuthed] = useState(!!getToken())
  const [page, setPage] = useState('overview')
  const [theme, setThemeState] = useState(() => {
    try {
      return applyTheme(localStorage.getItem('ai_sss_theme') || 'dark')
    } catch {
      return applyTheme('dark')
    }
  })
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const [events, setEvents] = useState([])
  const [systemStatus, setSystemStatus] = useState(null)

  const [threatLevel, setThreatLevel] = useState('low')
  const [knownPersons, setKnownPersons] = useState([])
  const [evidence, setEvidence] = useState([])
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
  const [me, setMe] = useState(null)
  const [streamingCams, setStreamingCams] = useState([])

  const [showPalette, setShowPalette] = useState(false)
  const [showNotifs, setShowNotifs] = useState(false)
  const [showCopilot, setShowCopilot] = useState(false)

  const setTheme = (t) => {
    setThemeState(applyTheme(t))
  }
  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  const { handleAlert: handleAutoAlert } = useAutoAlerts(() => {
    setThreatLevel('critical')
  })

  const handleWsMessage = useCallback((data) => {
    if (data.alert_type === 'PIPELINE_HEARTBEAT') return
    const formatted = formatEvent(data)
    setEvents((prev) => [formatted, ...prev].slice(0, 200))
    handleAutoAlert(data)

    if (data.threat_score >= 50) setThreatLevel('high')
    if (data.severity === 'critical') setThreatLevel('critical')
  }, [handleAutoAlert])

  const { connected: wsConnected } = useWebSocket('alerts', handleWsMessage)

  const reloadVehicles = useCallback(() => {
    fetchVehiclePlates().then(setPlates).catch(() => {})
    fetchVehicleDetections().then(setVehicleDetections).catch(() => {})
  }, [])

  /* Initial data load + status polling */
  useEffect(() => {
    if (!authed) return
    fetchAlerts(50).then((alerts) => {
      const mapped = alerts.map((a) => formatEvent(a))
      setEvents(mapped)
      if (mapped.some((e) => e.severity === 'critical' && !e.dismissed)) setThreatLevel('critical')
    }).catch(() => {})

    fetchMe().then(setMe).catch(() => {})

    fetchCameras().then(setCameras).catch(() => {})
    fetchMapCameras().then(setMapCameras).catch(() => {})
    fetchMapEvents(24).then(setMapEvents).catch(() => {})
    fetchKnownPersons().then(setKnownPersons).catch(() => {})
    fetchEvidence(60).then(setEvidence).catch(() => {})
    fetchAnalyticsSummary(24).then(setSummary).catch(() => {})
    fetchAnalyticsTrends(7).then(setTrends).catch(() => {})
    fetchAnalyticsLocations(24).then(setLocations).catch(() => {})
    fetchIncidentReport(24).then(setReport).catch(() => {})
    fetchAuditLogs(50).then(setAuditLogs).catch(() => {})
    reloadVehicles()

    fetchSystemStatus().then(setSystemStatus).catch(() => {})
    fetchStreamingCameras().then((r) => setStreamingCams(r.cameras || [])).catch(() => {})
    const interval = setInterval(() => {
      fetchSystemStatus().then((s) => {
        setSystemStatus(s)
        const cams = Object.values(s.cameras || {})
        const maxThreat = Math.max(0, ...cams.map((c) => c.threat_score || 0))
        if (maxThreat >= 50) setThreatLevel('critical')
        else if (maxThreat >= 20) setThreatLevel('high')
      }).catch(() => {})
      fetchStreamingCameras().then((r) => setStreamingCams(r.cameras || [])).catch(() => {})
    }, 3000)
    return () => clearInterval(interval)
  }, [authed, reloadVehicles])

  /* Refresh page-specific data when navigating */
  useEffect(() => {
    if (!authed) return
    if (page === 'watchlist') fetchKnownPersons().then(setKnownPersons).catch(() => {})
    if (page === 'evidence' || page === 'watchlist') fetchEvidence(60).then(setEvidence).catch(() => {})
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
    if (page === 'users') fetchAuditLogs(50).then(setAuditLogs).catch(() => {})
    if (page === 'reports') fetchIncidentReport(24).then(setReport).catch(() => {})
  }, [authed, page, reloadVehicles])

  /* Keyboard shortcuts */
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setShowPalette((v) => !v)
      } else if (e.key === 'Escape') {
        setShowPalette(false); setShowNotifs(false); setShowCopilot(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const reloadCameras = useCallback(() => {
    fetchCameras().then(setCameras).catch(() => {})
  }, [])

  if (!authed) {
    return (
      <LoginForm
        theme={theme}
        setTheme={setTheme}
        onLogin={async (u, p) => { await login(u, p); setAuthed(true) }}
      />
    )
  }

  const criticalEvents = events.filter((e) => e.severity === 'critical')
  const pipelineOnline = systemStatus?.online
  const activePage = ALL_PAGES.find((p) => p.id === page)
  const PageComponent = PAGE_COMPONENTS[page] || Overview



  const ctx = {
    events, setEvents, systemStatus, threatLevel, wsConnected,
    knownPersons, evidence, mapCameras, mapEvents, cameras,
    report, summary, trends, locations,
    plates, vehicleDetections, auditLogs, reloadVehicles,
    me, streamingCams, reloadCameras,
    theme, setTheme,
  }



  return (
    <div className={`shell ${threatLevel === 'critical' ? 'threat-critical' : ''}`}>
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="brand">
          <span className="brand-logo">AG</span>
          <div>Aegis<small>COMMAND CENTER</small></div>
        </div>
        <div className="nav-scroll">
          {NAV.map((group) => (
            <div className="nav-group" key={group.group}>
              <div className="nav-group-label">{group.group}</div>
              {group.pages.map((p) => {
                const Icon = p.icon
                return (
                  <div
                    key={p.id}
                    className={`nav-item ${page === p.id ? 'active' : ''}`}
                    data-alert-nav={p.id === 'alerts' && criticalEvents.length > 0 ? 'true' : undefined}
                    onClick={() => { setPage(p.id); setSidebarOpen(false) }}
                  >
                    <Icon />
                    {p.label}
                    {p.id === 'alerts' && criticalEvents.length > 0 && (
                      <span className="nav-badge">{criticalEvents.length}</span>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
        <div className="sidebar-footer">
          <div className="session-chip">
            <span className="avatar">{(me?.username || 'AD').slice(0, 2).toUpperCase()}</span>
            <div className="who"><b>{me?.username || 'admin'}</b><span>{me?.role || 'operator'}</span></div>
            <button className="icon-btn" title="Sign out" onClick={() => { clearToken(); setAuthed(false) }}>
              <Icons.logout />
            </button>
          </div>
        </div>
      </aside>

      <main className="main">


        <header className="topbar">
          <button type="button" className="icon-btn hamburger" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="Menu">
            <Icons.menu />
          </button>
          <div className="topbar-title">
            <span className="crumb">Command Center</span>
            <h1>{activePage?.label}</h1>
          </div>
          <button
            type="button"
            className="searchbox"
            onClick={() => setShowPalette(true)}
            aria-label="Open command palette"
          >
            <Icons.search />
            <span>Search pages, actions, cameras…</span>
            <kbd>⌘K</kbd>
          </button>
          <div className="topbar-right">
            <div className="status-rail" aria-label="System status">

              <Pill tone={pipelineOnline ? 'ok' : 'muted'}>{pipelineOnline ? 'AI ONLINE' : 'AI STANDBY'}</Pill>
              <Pill tone={wsConnected ? 'info' : 'danger'}>{wsConnected ? 'LIVE' : 'NO LINK'}</Pill>
            </div>
            <div className="topbar-actions">
              <button type="button" className="icon-btn" title="AI Copilot" onClick={() => setShowCopilot(true)}><Icons.bot /></button>
              <button type="button" className="icon-btn" title="Notifications" onClick={() => setShowNotifs(true)} style={{ position: 'relative' }}>
                <Icons.bell />
                {criticalEvents.length > 0 && (
                  <span className="nav-badge" style={{ position: 'absolute', top: 2, right: 2 }}>{criticalEvents.length}</span>
                )}
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
          </div>
        </header>

        <div className="page">
          <PageComponent ctx={ctx} />
        </div>
      </main>

      {showPalette && (
        <CommandPalette
          pages={ALL_PAGES}
          actions={[
            { id: 'act-theme', label: `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`, icon: theme === 'dark' ? Icons.sun : Icons.moon, hint: 'Action', run: () => setTheme(theme === 'dark' ? 'light' : 'dark') },
            { id: 'act-copilot', label: 'Open AI Copilot', icon: Icons.bot, hint: 'Action', run: () => setShowCopilot(true) },
            { id: 'act-notifs', label: 'Open Notification Center', icon: Icons.bell, hint: 'Action', run: () => setShowNotifs(true) },
            { id: 'act-logout', label: 'Sign out', icon: Icons.logout, hint: 'Action', run: () => { clearToken(); setAuthed(false) } },
          ]}
          onNavigate={setPage}
          onClose={() => setShowPalette(false)}
        />
      )}
      {showNotifs && (
        <NotificationDrawer events={events} onClose={() => setShowNotifs(false)} onClear={() => { setEvents([]); setThreatLevel('low'); }} />
      )}
      {showCopilot && (
        <Copilot ctx={{ events, summary, cameras, threatLevel, locations }} onClose={() => setShowCopilot(false)} />
      )}
    </div>
  )
}

export default App


