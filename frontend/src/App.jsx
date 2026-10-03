import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  login, clearToken, getToken, fetchAlerts, fetchSystemStatus,
  fetchKnownPersons, fetchEvidence, fetchMapCameras, fetchMapEvents,
  fetchIncidentReport, fetchCameras, fetchAnalyticsSummary,
  fetchAnalyticsTrends, fetchAnalyticsLocations, fetchVehiclePlates,
  fetchVehicleDetections, fetchAuditLogs, fetchMe, fetchStreamingCameras,
  fetchReviewCount,
} from './services/api'
import { parseTs } from './lib/time'
import { useWebSocket } from './hooks/useWebSocket'
import { useAutoAlerts } from './hooks/useAutoAlerts'
import { Icons, Pill } from './components/ui'
import { CommandPalette } from './components/CommandPalette'
import { NotificationDrawer } from './components/NotificationDrawer'
import { Copilot } from './components/Copilot'
import { CriticalAlertBanner } from './components/CriticalAlertBanner'
import { Overview } from './pages/Overview'
import { LiveMonitoring } from './pages/LiveMonitoring'
import { MapPage } from './pages/MapPage'
import { DetectionCenter } from './pages/DetectionCenter'
import { Triage } from './pages/Triage'
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
      { id: 'alerts', label: 'Alert Triage', icon: Icons.alert },
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

const ROLE_PAGES = {
  viewer: new Set(['overview', 'live', 'map', 'alerts']),
  operator: new Set(['overview', 'live', 'map', 'detection', 'alerts', 'incidents', 'evidence', 'analytics', 'reports', 'cameras']),
  police: new Set(['overview', 'live', 'map', 'alerts', 'incidents']),
  investigator: new Set(['overview', 'alerts', 'incidents', 'evidence', 'watchlist', 'vehicles', 'analytics', 'reports']),
  supervisor: null,
  admin: null,
}

function filterNavByRole(role) {
  const allowed = ROLE_PAGES[role]
  if (!allowed) return NAV
  return NAV.map((g) => ({ ...g, pages: g.pages.filter((p) => allowed.has(p.id)) })).filter((g) => g.pages.length)
}

function pageFromHash() {
  const id = (window.location.hash || '#/overview').replace('#/', '').split('?')[0]
  return ALL_PAGES.some((p) => p.id === id) ? id : 'overview'
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
  overview: Overview, live: LiveMonitoring, map: MapPage, detection: DetectionCenter,
  alerts: Triage, incidents: Incidents, evidence: EvidencePage,
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
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
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
        {error && <div className="login-error" role="alert">{error}</div>}
        <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
        <button type="submit" className="btn btn-primary" disabled={loading || !username || !password}>{loading ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </div>
  )
}

function App() {
  const [authed, setAuthed] = useState(!!getToken())
  const [page, setPageState] = useState(pageFromHash())
  const setPage = (id) => {
    setPageState(id)
    window.history.pushState(null, '', `#/${id}`)
  }
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

  const [clearedAt, setClearedAt] = useState(0)
  const [nowTick, setNowTick] = useState(() => Date.now())   // re-evaluates the 15-min window
  const [reviewPending, setReviewPending] = useState(0)
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
  const [criticalBanner, setCriticalBanner] = useState(null)

  const setTheme = (t) => {
    setThemeState(applyTheme(t))
  }
  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  useEffect(() => {
    const onHash = () => setPageState(pageFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    const onAuthExpired = () => {
      clearToken()
      setAuthed(false)
    }
    window.addEventListener('auth_expired', onAuthExpired)
    return () => window.removeEventListener('auth_expired', onAuthExpired)
  }, [])

  const { handleAlert: handleAutoAlert } = useAutoAlerts((alert) => {
    setCriticalBanner(alert)
  })

  const handleWsMessage = useCallback((data) => {
    if (data.alert_type === 'PIPELINE_HEARTBEAT') return
    const formatted = formatEvent(data)
    setEvents((prev) => [formatted, ...prev].slice(0, 200))
    handleAutoAlert(data)
  }, [handleAutoAlert])

  const { connected: wsConnected } = useWebSocket('alerts', handleWsMessage, authed)
  const { connected: statusWsConnected } = useWebSocket('status', () => {}, authed)

  const reloadVehicles = useCallback(() => {
    fetchVehiclePlates().then(setPlates).catch(() => {})
    fetchVehicleDetections().then(setVehicleDetections).catch(() => {})
  }, [])

  /* Initial data load + status polling */
  useEffect(() => {
    if (!authed) return
    fetchAlerts(50).then((alerts) => {
      setEvents(alerts.map((a) => formatEvent(a)))
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
      fetchSystemStatus().then(setSystemStatus).catch(() => {})
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
      } else if (e.key.toLowerCase() === 'n' && !e.metaKey && !e.ctrlKey) {
        setShowNotifs((v) => !v)
      } else if (e.key.toLowerCase() === 'c' && !e.metaKey && !e.ctrlKey) {
        setShowCopilot((v) => !v)
      } else if (e.key === 'Escape') {
        setShowPalette(false); setShowNotifs(false); setShowCopilot(false)
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
    fetchReviewCount().then((r) => setReviewPending(r.pending || 0)).catch(() => {})
  }, [])

  useEffect(() => {
    if (!authed) return undefined
    refreshReviewCount()
    const t = setInterval(refreshReviewCount, 15000)
    return () => clearInterval(t)
  }, [authed, refreshReviewCount])

  const reloadCameras = useCallback(() => {
    fetchCameras().then(setCameras).catch(() => {})
  }, [])

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

  if (!authed) {
    return (
      <LoginForm
        theme={theme}
        setTheme={setTheme}
        onLogin={async (u, p) => { await login(u, p); setAuthed(true) }}
      />
    )
  }

  const criticalEvents = events.filter((e) => e.severity === 'critical' && !e.acknowledged && !e.dismissed)
  const pipelineOnline = systemStatus?.online
  const activePage = ALL_PAGES.find((p) => p.id === page)
  const PageComponent = PAGE_COMPONENTS[page] || Overview



  const ctx = {
    events, setEvents, systemStatus, threatLevel, wsConnected,
    knownPersons, evidence, mapCameras, mapEvents, cameras,
    report, summary, trends, locations,
    plates, vehicleDetections, auditLogs, reloadVehicles,
    me, streamingCams, reloadCameras, setPage,
    reviewPending, refreshReviewCount,
    theme, setTheme,
  }



  return (
    <div className={`shell ${threatLevel === 'critical' ? 'threat-critical' : ''}`}>
      <CriticalAlertBanner alert={criticalBanner} onDismiss={() => setCriticalBanner(null)} />
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="brand">
          <span className="brand-logo">AG</span>
          <div>Aegis<small>COMMAND CENTER</small></div>
        </div>
        <div className="nav-scroll">
          {filterNavByRole(me?.role || 'admin').map((group) => (
            <div className="nav-group" key={group.group}>
              <div className="nav-group-label">{group.group}</div>
              {group.pages.map((p) => {
                const Icon = p.icon
                return (
                  <button
                    key={p.id}
                    type="button"
                    className={`nav-item ${page === p.id ? 'active' : ''}`}
                    aria-current={page === p.id ? 'page' : undefined}
                    data-alert-nav={p.id === 'alerts' && criticalEvents.length > 0 ? 'true' : undefined}
                    onClick={() => { setPage(p.id); setSidebarOpen(false) }}
                  >
                    <Icon />
                    {p.label}
                    {p.id === 'alerts' && (reviewPending > 0 || criticalEvents.length > 0) && (
                      <span className="nav-badge" aria-label={`${reviewPending || criticalEvents.length} need attention`}>
                        {reviewPending || criticalEvents.length}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
        <div className="sidebar-footer">
          <div className="session-chip">
            <span className="avatar">{(me?.username || 'AD').slice(0, 2).toUpperCase()}</span>
            <div className="who"><b>{me?.username || 'admin'}</b><span>{me?.role || 'operator'}</span></div>
            <button className="icon-btn" title="Sign out" aria-label="Sign out" onClick={() => { clearToken(); setAuthed(false) }}>
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

              <Pill tone={pipelineOnline ? 'ok' : 'warn'}>{pipelineOnline ? 'AI online' : 'AI offline'}</Pill>
              <Pill tone={wsConnected && statusWsConnected ? 'ok' : 'danger'}>
                {wsConnected && statusWsConnected ? 'Live updates' : 'Reconnecting…'}
              </Pill>
            </div>
            <div className="topbar-actions">
              <button type="button" className="icon-btn" title="Command Assistant" aria-label="Command Assistant" onClick={() => setShowCopilot(true)}><Icons.bot /></button>
              <button type="button" className="icon-btn" title="Notifications" aria-label="Notifications" onClick={() => setShowNotifs(true)} style={{ position: 'relative' }}>
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
            { id: 'act-copilot', label: 'Open Command Assistant', icon: Icons.bot, hint: 'Action', run: () => setShowCopilot(true) },
            { id: 'act-notifs', label: 'Open Notification Center', icon: Icons.bell, hint: 'Action', run: () => setShowNotifs(true) },
            { id: 'act-logout', label: 'Sign out', icon: Icons.logout, hint: 'Action', run: () => { clearToken(); setAuthed(false) } },
          ]}
          onNavigate={setPage}
          onClose={() => setShowPalette(false)}
        />
      )}
      {showNotifs && (
        <NotificationDrawer events={events} onClose={() => setShowNotifs(false)} onClear={() => { setEvents([]); setClearedAt(Date.now()) }} />
      )}
      {showCopilot && (
        <Copilot ctx={{ events, summary, cameras, threatLevel, locations }} onClose={() => setShowCopilot(false)} />
      )}
    </div>
  )
}

export default App


