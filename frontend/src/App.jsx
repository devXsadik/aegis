import { useState, useEffect, useCallback } from 'react'
import {
  login, clearToken, getToken, fetchAlerts, fetchSystemStatus,
  fetchKnownPersons, fetchEvidence, fetchMapCameras, fetchMapEvents,
  fetchIncidentReport,
} from './services/api'
import { useWebSocket } from './hooks/useWebSocket'
import { useAutoAlerts } from './hooks/useAutoAlerts'
import { CriticalAlertBanner } from './components/CriticalAlertBanner'
import { MapPin } from './components/MapPin'
import { CameraMapOverview } from './components/CameraMapOverview'

const TABS = [
  { id: 'live', label: 'Live Feeds' },
  { id: 'events', label: 'Event Logs' },
  { id: 'faces', label: 'Known Faces' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'map', label: 'Map' },
  { id: 'settings', label: 'Settings' },
]

const SEVERITY_CLASS = {
  critical: 'status-alert',
  high: 'status-alert',
  medium: 'status-warn',
  info: 'status-active',
}

function formatEvent(evt) {
  const type = evt.alert_type || evt.event_type || 'EVENT'
  const msg = evt.message || evt.person_name || evt.data?.criminal_name || type.replace(/_/g, ' ')
  return {
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

function LoginForm({ onLogin }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin123')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')
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
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>Ai-SSS Admin</h1>
        <p className="login-sub">Automated surveillance with GPS pinpoint alerts</p>
        {error && <div className="login-error">{error}</div>}
        <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <button type="submit" disabled={loading}>{loading ? 'Signing in…' : 'Sign in'}</button>
        <p className="login-hint">Demo: <code>python scripts/seed_demo.py</code> → admin / admin123</p>
      </form>
    </div>
  )
}

function App() {
  const [authed, setAuthed] = useState(!!getToken())
  const [activeTab, setActiveTab] = useState('live')
  const [events, setEvents] = useState([])
  const [systemStatus, setSystemStatus] = useState(null)
  const [criticalAlert, setCriticalAlert] = useState(null)
  const [threatLevel, setThreatLevel] = useState('low')
  const [knownPersons, setKnownPersons] = useState([])
  const [evidence, setEvidence] = useState([])
  const [mapCameras, setMapCameras] = useState([])
  const [mapEvents, setMapEvents] = useState([])
  const [report, setReport] = useState(null)

  const { handleAlert: handleAutoAlert } = useAutoAlerts((alert) => {
    setCriticalAlert(alert)
    setThreatLevel('critical')
    setActiveTab('events')
  })

  const handleWsMessage = useCallback((data) => {
    if (data.alert_type === 'PIPELINE_HEARTBEAT') return
    const formatted = formatEvent(data)
    setEvents((prev) => [formatted, ...prev].slice(0, 100))
    handleAutoAlert(data)
    if (data.threat_score >= 50) setThreatLevel('high')
    if (data.severity === 'critical') setThreatLevel('critical')
  }, [handleAutoAlert])

  const { connected: wsConnected } = useWebSocket('alerts', handleWsMessage)

  useEffect(() => {
    if (!authed) return
    fetchAlerts(20).then((alerts) => {
      const mapped = alerts.map((a) => formatEvent({
        alert_type: a.alert_type, severity: a.severity, message: a.message,
        person_name: a.person_name, timestamp: a.timestamp, camera_location: a.camera_location,
      }))
      setEvents(mapped)
      if (mapped.some((e) => e.severity === 'critical')) setThreatLevel('critical')
    }).catch(() => {})

    const interval = setInterval(() => {
      fetchSystemStatus().then((s) => {
        setSystemStatus(s)
        const cams = Object.values(s.cameras || {})
        const maxThreat = Math.max(0, ...cams.map((c) => c.threat_score || 0))
        if (maxThreat >= 50) setThreatLevel('critical')
        else if (maxThreat >= 20) setThreatLevel('high')
      }).catch(() => {})
    }, 3000)
    fetchSystemStatus().then(setSystemStatus).catch(() => {})
    return () => clearInterval(interval)
  }, [authed])

  useEffect(() => {
    if (!authed) return
    if (activeTab === 'faces') fetchKnownPersons().then(setKnownPersons).catch(() => {})
    if (activeTab === 'evidence') fetchEvidence(40).then(setEvidence).catch(() => {})
    if (activeTab === 'map') {
      fetchMapCameras().then(setMapCameras).catch(() => {})
      fetchMapEvents(24).then(setMapEvents).catch(() => {})
    }
    if (activeTab === 'settings') fetchIncidentReport(24).then(setReport).catch(() => {})
  }, [authed, activeTab])

  if (!authed) return <LoginForm onLogin={async (u, p) => { await login(u, p); setAuthed(true) }} />

  const pipelineOnline = systemStatus?.online
  const cameras = systemStatus?.cameras || {}
  const cameraEntries = Object.entries(cameras)
  const primaryCamera = cameraEntries[0]?.[1]
  const criticalEvents = events.filter((e) => e.severity === 'critical')
  const mapAlert = criticalAlert || criticalEvents[0]

  const tabTitle = TABS.find((t) => t.id === activeTab)?.label || ''

  return (
    <div className={`dashboard-container ${threatLevel === 'critical' ? 'threat-critical' : ''}`}>
      <aside className="sidebar">
        <div className="sidebar-header">Ai-SSS Admin</div>
        <div className="sidebar-nav">
          {TABS.map((tab) => (
            <div
              key={tab.id}
              className={`nav-item ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
              {tab.id === 'events' && criticalEvents.length > 0 && (
                <span className="nav-badge">{criticalEvents.length}</span>
              )}
            </div>
          ))}
        </div>
        <button className="logout-btn" onClick={() => { clearToken(); setAuthed(false) }}>Sign out</button>
      </aside>

      <main className="main-content">
        <CriticalAlertBanner alert={criticalAlert} onDismiss={() => setCriticalAlert(null)} />

        <header className="topbar">
          <h2>{tabTitle}</h2>
          <div className="topbar-badges">
            <span className={`status-badge threat-${threatLevel}`}>Threat: {threatLevel.toUpperCase()}</span>
            <span className={`status-badge ${wsConnected ? 'status-active' : 'status-alert'}`}>
              WS {wsConnected ? 'Connected' : 'Disconnected'}
            </span>
            <span className={`status-badge ${pipelineOnline ? 'status-active' : 'status-warn'}`}>
              Pipeline {pipelineOnline ? 'Online' : 'Offline'}
            </span>
          </div>
        </header>

        {activeTab === 'live' && (
          <div className="dashboard-grid">
            <div className="panel" style={{ gridRow: '1 / span 2' }}>
              <div className="panel-header">{primaryCamera?.camera_location || 'Main Entrance'}</div>
              <div className="panel-body">
                <div className={`camera-feed ${threatLevel === 'critical' ? 'feed-alert' : ''}`}>
                  {pipelineOnline ? (
                    <div className="feed-active">
                      <div className={`feed-pulse ${threatLevel === 'critical' ? 'pulse-alert' : ''}`} />
                      <p>Auto-monitoring — criminal alerts + GPS on any camera</p>
                      <p className="feed-meta">FPS: {primaryCamera?.fps ?? '—'} · Threat: {primaryCamera?.threat_score ?? 0}</p>
                    </div>
                  ) : (
                    <p>Start: <code>./scripts/run_defense_demo.sh</code></p>
                  )}
                </div>
              </div>
            </div>
            <div className="panel">
              <div className="panel-header">Recent Alerts</div>
              <div className="panel-body">
                {events.slice(0, 6).map((evt, i) => (
                  <div key={i} className={`log-entry ${evt.severity === 'critical' ? 'log-critical' : ''}`}>
                    <span>{evt.msg}</span>
                    <span className={`status-badge ${SEVERITY_CLASS[evt.severity]}`}>{evt.severity}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="panel">
              <div className="panel-header">📍 Detection Location</div>
              <div className="panel-body">
                {mapAlert?.lat != null ? (
                  <MapPin lat={mapAlert.lat} lng={mapAlert.lng} label={mapAlert.cameraName || mapAlert.camera} />
                ) : (
                  <p className="empty-state">Map shows on criminal detection</p>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'events' && (
          <div className="panel">
            <div className="panel-header">Auto-Dispatched Events ({events.length})</div>
            <div className="panel-body">
              {events.map((evt, i) => (
                <div key={i} className={`log-entry ${evt.severity === 'critical' ? 'log-critical' : ''}`}>
                  <div>
                    <strong>{evt.type}</strong>
                    <div className="event-time">{evt.time} · {evt.camera}</div>
                    <div>{evt.msg}</div>
                    {evt.lat != null && (
                      <div className="event-gps">📍 {Number(evt.lat).toFixed(5)}, {Number(evt.lng).toFixed(5)}</div>
                    )}
                  </div>
                  <span className={`status-badge ${SEVERITY_CLASS[evt.severity]}`}>{evt.severity}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === 'faces' && (
          <div className="panel">
            <div className="panel-header">Watchlist — Known Persons ({knownPersons.length})</div>
            <div className="panel-body">
              {knownPersons.length === 0 ? (
                <p className="empty-state">No persons in DB. Run: <code>python scripts/ingest_watchlist.py</code></p>
              ) : (
                knownPersons.map((p) => (
                  <div key={p.id} className="log-entry">
                    <div>
                      <strong>{p.name}</strong> ({p.person_id})
                      <div className="event-time">{p.category} · Threat {p.threat_level}</div>
                    </div>
                    <span className={`status-badge ${p.criminal_status === 'active' ? 'status-alert' : 'status-active'}`}>
                      {p.criminal_status}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {activeTab === 'evidence' && (
          <div className="panel">
            <div className="panel-header">Evidence Records ({evidence.length})</div>
            <div className="panel-body">
              {evidence.length === 0 ? (
                <p className="empty-state">No evidence yet — triggers on criminal/suspicious detection</p>
              ) : (
                evidence.map((ev) => (
                  <div key={ev.id} className={`log-entry ${ev.is_criminal ? 'log-critical' : ''}`}>
                    <div>
                      <strong>{ev.person_name || `Track ${ev.track_id}`}</strong>
                      <div className="event-time">{ev.timestamp} · {ev.camera_location}</div>
                      <div>{ev.category} {ev.is_criminal && '· CRIMINAL'}</div>
                    </div>
                    <span className={`status-badge ${ev.is_criminal ? 'status-alert' : 'status-active'}`}>
                      {ev.category}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {activeTab === 'map' && (
          <div className="panel">
            <div className="panel-header">Camera Map & Detection Pins</div>
            <div className="panel-body">
              <CameraMapOverview cameras={mapCameras} events={mapEvents} />
            </div>
          </div>
        )}

        {activeTab === 'settings' && (
          <div className="panel">
            <div className="panel-header">System & Reports</div>
            <div className="panel-body settings-body">
              <p><strong>Run demo:</strong> <code>./scripts/run_defense_demo.sh</code></p>
              <p><strong>Evaluate:</strong> <code>python scripts/evaluate_pipeline.py --video data/demo/clips/sample.mp4 --frames 200 --output data/results/eval.json</code></p>
              {report && (
                <div className="report-box">
                  <h4>24h Incident Report</h4>
                  <p>Total events: {report.summary?.total_events}</p>
                  <p>Criminal detections: {report.summary?.criminal_detections}</p>
                  <p>Weapon detections: {report.summary?.weapon_detections}</p>
                  <p>Alerts triggered: {report.summary?.alerts_triggered}</p>
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default App
