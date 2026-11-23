import { useState, useEffect, useMemo, useRef, lazy, Suspense } from 'react'
import { useToast } from './components/Toast'
import { ProfileModal } from './components/ProfileModal'
import { LoginForm } from './components/LoginForm'
import { parseTs } from './lib/time'
import { can, canViewPage, PAGE_VIEWS } from './lib/permissions'
import { ALL_PAGES, NAV, PALETTE_VIEWS, POLICE_TABS, TAB_PAGES, THREAT, VIEW_LABELS } from './lib/nav'
import { useTheme } from './hooks/useTheme'
import { useI18n } from './hooks/useI18n'
import { useSession } from './hooks/useSession'
import { useIdleLogout } from './hooks/useIdleLogout'
import { TwoFactor } from './components/TwoFactor'
import { useRoute } from './hooks/useRoute'
import { useDashboardData } from './hooks/useDashboardData'
import { useLiveStatus } from './hooks/useLiveStatus'
import { alertKey, useCriticalAlerts } from './hooks/useCriticalAlerts'
import { useShortcuts } from './hooks/useShortcuts'
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
const CommandMap = lazyPage(() => import('./pages/CommandMap'), 'CommandMap')
const ModelsData = lazyPage(() => import('./pages/ModelsData'), 'ModelsData')
const AccuracyView = lazyPage(() => import('./components/Governance'), 'AccuracyDashboard')
const DetectionCenter = lazyPage(() => import('./pages/DetectionCenter'), 'DetectionCenter')
const Triage = lazyPage(() => import('./pages/Triage'), 'Triage')
const Incidents = lazyPage(() => import('./pages/Incidents'), 'Incidents')
const Cameras = lazyPage(() => import('./pages/Cameras'), 'Cameras')
const Analytics = lazyPage(() => import('./pages/Analytics'), 'Analytics')
const EvidencePage = lazyPage(() => import('./pages/EvidencePage'), 'EvidencePage')
const Watchlist = lazyPage(() => import('./pages/Watchlist'), 'Watchlist')
const FaceRegistryPage = lazyPage(() => import('./pages/FaceRegistryPage'), 'FaceRegistryPage')
const Vehicles = lazyPage(() => import('./pages/Vehicles'), 'Vehicles')
const VehicleSearch = lazyPage(() => import('./pages/VehicleSearch'), 'VehicleSearch')
const Reports = lazyPage(() => import('./pages/Reports'), 'Reports')
const ResponseTimes = lazyPage(() => import('./pages/CommandReports'), 'ResponseTimes')
const Patterns = lazyPage(() => import('./pages/CommandReports'), 'Patterns')
const CameraUptime = lazyPage(() => import('./pages/CommandReports'), 'CameraUptime')
const Responder = lazyPage(() => import('./pages/Responder'), 'Responder')
const ShiftLog = lazyPage(() => import('./pages/ShiftLog'), 'ShiftLog')
const Roster = lazyPage(() => import('./pages/Roster'), 'Roster')
const Users = lazyPage(() => import('./pages/Users'), 'Users')
const Settings = lazyPage(() => import('./pages/Settings'), 'Settings')
const ZoneEditor = lazyPage(() => import('./pages/ZoneEditor'), 'ZoneEditor')

const PAGE_COMPONENTS = {
  overview: Overview, live: LiveMonitoring, map: MapPage, command: CommandMap,
  alerts: Triage, respond: Responder, incidents: Incidents, evidence: EvidencePage,
  vehicles: Vehicles, search: VehicleSearch,
  cameras: Cameras, models: ModelsData, zones: ZoneEditor, users: Users, settings: Settings,
}
const VIEW_COMPONENTS = {
  faces: FaceRegistryPage, watchlist: Watchlist, analytics: Analytics, detection: DetectionCenter, accuracy: AccuracyView,
  shift: ShiftLog, roster: Roster,
  reports: Reports, response: ResponseTimes, patterns: Patterns, uptime: CameraUptime,
}

/** A page made of views: tabs for the ones this role may open, then the chosen view. */
function ViewSwitch({ pageId, view, onView, role, ctx }) {
  const views = PAGE_VIEWS[pageId].filter((v) => canViewPage(role, v))
  const current = views.includes(view) ? view : views[0]
  const Current = VIEW_COMPONENTS[current]
  if (!Current) return null          // role not known yet (profile loading), or no view allowed
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

/* The shell: session, navigation, live data and the alerts that pop up. Each concern lives in
   its hook (hooks/use*.js); this component wires them together and lays out the page. */
function App() {
  const { push: toast } = useToast()
  const { t, lang } = useI18n()
  const navLabel = (p) => (!p ? '' : lang === 'en' ? p.label : t(`nav.${p.id}`))
  const [theme, setTheme] = useTheme()
  const { page, view, setPage } = useRoute()
  const [reloadTick, setReloadTick] = useState(0)
  const [nowTick, setNowTick] = useState(() => Date.now())   // re-evaluates the 15-min window
  useEffect(() => {
    const t = setInterval(() => setNowTick(Date.now()), 30000)
    return () => clearInterval(t)
  }, [])

  const profileErrorRef = useRef(null)
  const session = useSession({ reloadTick, onProfileError: () => profileErrorRef.current?.() })
  const { authed, me } = session
  const role = me?.role
  const data = useDashboardData({ authed, role, page, reloadTick })
  useEffect(() => { profileErrorRef.current = data.profileFailed })
  const {
    events, setEvents, cameras, mapCameras, mapEvents, knownPersons, evidence, report, summary, trends,
    locations, plates, vehicleDetections, auditLogs, reviewPending, escalation, loadFailed, setLoadFailed,
    reloadKnownPersons, reloadCameras, reloadVehicles, refreshReviewCount,
  } = data
  const { systemStatus, streamingCams, apiDown, statusConnected, devices, power, setPower, camList } =
    useLiveStatus({ authed, role, cameras, reloadTick })
  const ops = authed && can(role, 'data.view')

  const [mapFocus, setMapFocus] = useState(null)      // {cameraId, lat, lng, t}: which camera the map should show
  const focusMap = (c) => setMapFocus({ cameraId: c.cameraId ?? c.camera_id, lat: c.lat, lng: c.lng, t: Date.now() })
  const alerts = useCriticalAlerts({ authed, me, page, nowTick, setEvents, onFocusMap: focusMap, toast })
  const { criticalAlerts, dropCritical, ackCritical, muteCamera, activeMuted, unmuteAll, captureEvent } = alerts

  const [clearedAt, setClearedAt] = useState(0)
  const [showPalette, setShowPalette] = useState(false)
  const [showProfile, setShowProfile] = useState(false)
  const [showNotifs, setShowNotifs] = useState(false)
  const [showCopilot, setShowCopilot] = useState(false)
  const [askQuery, setAskQuery] = useState('')        // question typed in the Home ask bar
  const [showAccount, setShowAccount] = useState(false)
  const [showSystem, setShowSystem] = useState(false)
  useShortcuts({
    palette: () => setShowPalette((v) => !v),
    notifications: () => setShowNotifs((v) => !v),
    answers: () => setShowCopilot((v) => !v),
    closeAll: () => { setShowPalette(false); setShowNotifs(false); setShowCopilot(false); setShowAccount(false); setShowSystem(false) },
  })

  // One camera kept on screen across pages (pinned from the Live wall).
  const [pinned, setPinnedState] = useState(() => { try { return localStorage.getItem('aegis_pin') || null } catch { return null } })
  const pinCamera = (id) => {
    setPinnedState(id)
    try { if (id) localStorage.setItem('aegis_pin', id); else localStorage.removeItem('aegis_pin') } catch { /* ignore */ }
  }
  const [liveFocus, setLiveFocus] = useState(null)    // {cameraId, t}: camera to open on the Live page
  // A camera picked anywhere (Home tiles, map) opens on the Live page.
  const openCamera = (cameraId) => { setLiveFocus({ cameraId, t: Date.now() }); setPage('live') }

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

  useIdleLogout(!!authed, session.signOut)
  if (authed === null) return <div className="login-screen" aria-busy="true" />
  if (!authed) {
    return <LoginForm theme={theme} setTheme={setTheme} notice={session.notice} onLogin={session.signIn} />
  }

  const wsConnected = alerts.connected
  const statusWsConnected = statusConnected
  const doSignOut = session.signOut
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
    openProfile: () => setShowProfile(true),
    showOnMap: (c) => { setMapFocus({ cameraId: c.camera_id, lat: c.lat, lng: c.lng, t: Date.now() }); setPage('map') },
    theme, setTheme,
  }

  // Server requires two-step sign-in (MFA_REQUIRED): nothing else works until it is on.
  if (me?.mfa_setup_required) {
    return (
      <main className="mfa-gate">
        <Card title="Turn on two-step sign-in" sub="Your organisation requires it for every account">
          <TwoFactor />
          <div className="ds-toolbar" style={{ marginTop: 12 }}>
            <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>I have turned it on</button>
            <button type="button" className="btn" onClick={doSignOut}>Sign out</button>
          </div>
        </Card>
      </main>
    )
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
          <h1>{navLabel(activePage)}</h1>
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
              <button type="button" className="pill pill-warn pill-btn" onClick={unmuteAll}
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
                  {lang === 'en' ? p.label.split(' ')[0] : navLabel(p)}
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


