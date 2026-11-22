import { useEffect, useState } from 'react'
import { fetchPendingHandover } from '../services/api'
import { Card, Stat, Icons, Tag, SEVERITY_TONE, timeAgo, Empty, Pill } from '../components/ui'
import { canViewPage } from '../lib/permissions'
import { AreaChart, BarList, Donut } from '../components/charts'
import { MapPin } from '../components/MapPin'
import { eventLabel } from '../lib/events'
import { parseTs } from '../lib/time'

const MODEL_LABELS = {
  weapon_detector: 'Weapon detection',
  vehicle_detector: 'Vehicle detection',
  human_detector: 'Person detection',
  pose_analyzer: 'Pose / fall checks',
  fire_detector: 'Fire & smoke detection',
}

/* First run: the few steps that make the system useful, ticked off as they happen.
   Shown to roles that can do them, until done or hidden. */
function SetupChecklist({ ctx, detecting }) {
  const [hidden, setHidden] = useState(() => {
    try { return localStorage.getItem('aegis_setup_hidden') === '1' } catch { return false }
  })
  const role = ctx.me?.role
  const steps = [
    { done: ctx.cameras.length > 0, title: 'Add a camera', text: 'A webcam on this computer, or a network camera by its address.', page: 'cameras', action: 'Add camera' },
    { done: detecting, title: 'Turn on detection', text: 'Run ./run.sh (or python main.py --multi) on the computer the cameras are connected to.' },
    { done: (ctx.knownPersons || []).length > 0, title: 'Enrol a person', text: 'Add clear, front-facing photos. Watchlist people raise an alert when a camera sees them.', page: 'faces', action: 'Enrol' },
    { optional: true, title: 'Draw zones', text: 'Restricted areas and counting lines for each camera.', page: 'zones', action: 'Open zones' },
  ].filter((s) => !s.page || canViewPage(role, s.page))
  const required = steps.filter((s) => !s.optional)
  if (hidden || !canViewPage(role, 'cameras') || required.every((s) => s.done)) return null
  const hide = () => {
    setHidden(true)
    try { localStorage.setItem('aegis_setup_hidden', '1') } catch { /* ignore */ }
  }
  return (
    <Card className="mb" title="Get started" sub={`${required.filter((s) => s.done).length} of ${required.length} done`}
      actions={<button type="button" className="btn btn-ghost btn-sm" onClick={hide}>Hide</button>}>
      <ol className="setup-steps">
        {steps.map((s) => (
          <li key={s.title} className={s.done ? 'done' : ''}>
            <span className="setup-mark" aria-hidden="true">{s.done ? <Icons.check /> : null}</span>
            <span className="setup-text">
              <b>{s.title}{s.optional && <small> · optional</small>}</b>
              <span>{s.done ? 'Done' : s.text}</span>
            </span>
            {!s.done && s.page && <button type="button" className="btn btn-sm" onClick={() => ctx.setPage(s.page)}>{s.action}</button>}
          </li>
        ))}
      </ol>
    </Card>
  )
}

function attentionItems(ctx, camList) {
  const items = []
  const sys = ctx.systemStatus
  if (ctx.reviewPending > 0) {
    items.push({ tone: 'warn', text: `${ctx.reviewPending} alert${ctx.reviewPending === 1 ? '' : 's'} waiting for review`, action: 'Review', page: 'alerts' })
  }
  // `online` stays true after the first heartbeat; cameras that stopped reporting drop out of `cameras`.
  if (sys && !Object.keys(sys.cameras || {}).length) {
    items.push({ tone: 'danger', text: 'Detection is off: no camera is being analysed', action: 'Live cameras', page: 'live' })
  }
  // Cameras switched on that send no video (paused ones are paused on purpose: not a problem).
  const down = camList.filter((c) => c.status === 'online' || c.status === 'offline').length
  if (down > 0) {
    items.push({ tone: 'warn', text: `${down} camera${down === 1 ? '' : 's'} not sending video`, action: 'Live cameras', page: 'live' })
  }
  Object.entries(sys?.models || {}).forEach(([key, status]) => {
    if (status === 'missing') {
      items.push({ tone: 'danger', text: `${MODEL_LABELS[key] || key} is OFF — model file not found`, action: 'Details', page: 'settings' })
    }
  })
  return items
}

export function Overview({ ctx }) {
  const { events, systemStatus, summary, trends, locations, threatLevel, cameras } = ctx

  const liveCams = Object.values(systemStatus?.cameras || {})
  const detecting = liveCams.length > 0
  const camList = ctx.camList || []
  const liveCount = camList.filter((c) => c.status === 'live').length
  const paused = cameras.filter((c) => !c.active).length + camList.filter((c) => c.status === 'off').length
  const criticalEvents = events.filter((e) => e.severity === 'critical')
  const openCritical = criticalEvents.filter((e) => !e.acknowledged && !e.dismissed)
  const trendData = trends.map((t) => t.events)
  const trendLabels = trends.map((t) => {
    const d = parseTs(`${t.date}T00:00:00`)
    return d ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' }) : t.date
  })
  const mapAlert = criticalEvents.find((e) => e.lat != null)

  // A handover written by someone else and not yet accepted: the first thing the next operator sees.
  const [handover, setHandover] = useState(null)
  const seesShift = canViewPage(ctx.me?.role, 'shift')
  useEffect(() => {
    if (!seesShift) return
    fetchPendingHandover().then(setHandover).catch(() => {})
  }, [seesShift])
  const attention = attentionItems(ctx, camList)
  if (handover && handover.username !== ctx.me?.username) {
    attention.unshift({ tone: 'warn', text: `Shift handover from ${handover.username} is waiting for you`, action: 'Read', page: 'shift' })
  }
  const threatAccent = { critical: 'danger', high: 'warn', low: 'ok' }[threatLevel] || 'ok'

  return (
    <>
      <SetupChecklist ctx={ctx} detecting={detecting} />

      <section className={`attention ${attention.length ? '' : 'clear'}`} aria-label="Needs attention">
        <h3>{attention.length ? 'Needs attention' : 'All clear'}</h3>
        {attention.length === 0 && <p className="muted">No alerts waiting, every camera sending video, all detection models ready.</p>}
        {attention.map((a) => (
          <div className={`attn-row tone-${a.tone}`} key={a.text}>
            <span>{a.text}</span>
            <button type="button" className="btn btn-sm" onClick={() => ctx.setPage(a.page)}>{a.action}</button>
          </div>
        ))}
      </section>

      <div className="section-label"><span>Right now</span></div>
      <div className="grid grid-4" style={{ marginBottom: 24 }}>
        <Stat
          label="Cameras live" value={`${liveCount} of ${cameras.length}`}
          delta={paused ? `${paused} paused` : 'All switched on'}
          accent={liveCount ? 'ok' : 'warn'} icon={Icons.camera}
        />
        <Stat label="Detection" value={detecting ? 'On' : 'Off'} delta={detecting ? `${liveCams.length} camera${liveCams.length === 1 ? '' : 's'} reporting` : 'Start a camera on Live cameras'} accent={detecting ? 'ok' : 'warn'} icon={Icons.ai} />
        <Stat label="Open critical alerts" value={openCritical.length} delta={`Not yet acknowledged · of the latest ${events.length} alerts`} accent={openCritical.length ? 'danger' : 'ok'} icon={Icons.alert} />
        <Stat label="Threat level" value={threatLevel[0].toUpperCase() + threatLevel.slice(1)} delta="From unreviewed alerts in the last 15 min" accent={threatAccent} icon={Icons.shield} />
      </div>

      <div className="section-label"><span>Detections</span><small>Last {summary?.period_hours ?? 24} hours</small></div>
      <div className="grid grid-4" style={{ marginBottom: 24 }}>
        <Stat label="Events" value={summary?.total_events ?? '—'} delta="Everything the cameras flagged" accent="primary" icon={Icons.incident} />
        <Stat label="Watchlist matches" value={summary?.criminal_detections ?? '—'} delta="Held until a person reviews them" accent="primary" icon={Icons.watchlist} />
        <Stat label="Weapon alerts" value={summary?.weapon_detections ?? '—'} delta="Confirmed across several frames" accent="primary" icon={Icons.alert} />
        <Stat label="Alerts raised" value={summary?.alerts_triggered ?? '—'} delta="Review them in Alerts" accent="primary" icon={Icons.dispatch} />
      </div>

      <div className="grid grid-23" style={{ marginBottom: 14 }}>
        <Card title="Events per day" sub="Last 7 days">
          <AreaChart data={trendData} labels={trendLabels} label="Events per day" emptyText="No events in the last 7 days" />
        </Card>
        <Card title="What was detected" sub={`Last ${summary?.period_hours ?? 24} hours`}>
          <Donut
            label={summary?.total_events ?? 0}
            sublabel="events"
            segments={[
              { label: 'Watchlist', value: summary?.criminal_detections ?? 0, color: 'var(--danger)' },
              { label: 'Weapon', value: summary?.weapon_detections ?? 0, color: 'var(--orange)' },
              { label: 'Suspicious', value: summary?.suspicious_activities ?? 0, color: 'var(--warn)' },
            ]}
          />
        </Card>
      </div>

      <div className="grid grid-23">
        <Card title="Latest detections" actions={<Pill tone={ctx.wsConnected ? 'ok' : 'danger'}>{ctx.wsConnected ? 'Live' : 'Offline'}</Pill>}>
          {events.length === 0 && <Empty icon={Icons.eye}>Nothing detected yet. Start the pipeline with <code>./run.sh</code></Empty>}
          {events.slice(0, 8).map((evt, i) => (
            <div key={evt.id ?? `${evt.type}-${evt.time}-${i}`} className={`row ${evt.severity === 'critical' ? 'crit' : ''}`}>
              <div>
                <b>{eventLabel(evt.type)}</b>
                <div className="meta">{evt.msg} · {evt.camera || '—'} · {timeAgo(evt.time)}</div>
              </div>
              <Tag tone={SEVERITY_TONE[evt.severity] || 'muted'}>{evt.severity}</Tag>
            </div>
          ))}
        </Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Card title="Busiest locations" sub="Last 24 hours">
            <BarList items={locations.slice(0, 5).map((l) => ({ label: l.location || 'Unknown', value: l.events }))} emptyText="No detections in the last 24 hours" />
          </Card>
          <Card title="Latest critical alert">
            {mapAlert ? (
              <MapPin lat={mapAlert.lat} lng={mapAlert.lng} label={mapAlert.cameraName || mapAlert.camera} height={180} />
            ) : (
              <Empty icon={Icons.map}>The camera's location shows here when a critical alert comes in.</Empty>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}
