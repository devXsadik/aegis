import { Card, Stat, Icons, Tag, SEVERITY_TONE, timeAgo, Empty, Pill } from '../components/ui'
import { AreaChart, BarList, Donut } from '../components/charts'
import { MapPin } from '../components/MapPin'

export function Overview({ ctx }) {
  const { events, systemStatus, summary, trends, locations, threatLevel, cameras } = ctx

  const liveCams = Object.values(systemStatus?.cameras || {})
  const activeCameras = cameras.filter((c) => c.active).length
  const offlineCameras = cameras.length - activeCameras
  const criticalEvents = events.filter((e) => e.severity === 'critical')
  const trendData = trends.map((t) => t.events)
  const mapAlert = criticalEvents.find((e) => e.lat != null)

  const threatAccent = { critical: 'danger', high: 'warn', low: 'ok' }[threatLevel] || 'ok'

  return (
    <>
      <div className="grid grid-4" style={{ marginBottom: 14 }}>
        <Stat label="Active Cameras" value={`${activeCameras || liveCams.length}`} delta={`${offlineCameras} offline`} accent="primary" icon={Icons.camera} />
        <Stat label="AI Pipeline" value={systemStatus?.online ? 'ONLINE' : 'OFFLINE'} delta={systemStatus?.online ? 'All models loaded' : 'Start the pipeline'} accent={systemStatus?.online ? 'ok' : 'warn'} icon={Icons.ai} />
        <Stat label="Active Alerts" value={criticalEvents.length} delta={`${events.length} events this session`} accent={criticalEvents.length ? 'danger' : 'ok'} icon={Icons.alert} />
        <Stat label="Threat Level" value={threatLevel.toUpperCase()} delta="Auto-computed from live feeds" accent={threatAccent} icon={Icons.shield} />
      </div>

      <div className="grid grid-4" style={{ marginBottom: 14 }}>
        <Stat label="Today's Incidents" value={summary?.total_events ?? '—'} delta={`last ${summary?.period_hours ?? 24}h`} accent="purple" icon={Icons.incident} />
        <Stat label="Criminal Detections" value={summary?.criminal_detections ?? '—'} delta="auto-dispatched" accent="danger" icon={Icons.watchlist} />
        <Stat label="Weapon Detections" value={summary?.weapon_detections ?? '—'} delta="auto-dispatched" accent="warn" icon={Icons.alert} />
        <Stat label="Alerts Dispatched" value={summary?.alerts_triggered ?? '—'} delta="DB + WebSocket + GPS" accent="cyan" icon={Icons.dispatch} />
      </div>

      <div className="grid grid-23" style={{ marginBottom: 14 }}>
        <Card title="Incident Trend" sub="events per day, last 7 days">
          <AreaChart data={trendData.length ? trendData : [0]} label="Events / day" />
        </Card>
        <Card title="Detection Mix" sub={`last ${summary?.period_hours ?? 24}h`}>
          <Donut
            label={summary?.total_events ?? 0}
            sublabel="events"
            segments={[
              { label: 'Criminal', value: summary?.criminal_detections ?? 0, color: 'var(--danger)' },
              { label: 'Weapon', value: summary?.weapon_detections ?? 0, color: 'var(--orange)' },
              { label: 'Suspicious', value: summary?.suspicious_activities ?? 0, color: 'var(--warn)' },
              {
                label: 'Normal',
                value: Math.max(0, (summary?.total_events ?? 0) - (summary?.criminal_detections ?? 0) - (summary?.weapon_detections ?? 0) - (summary?.suspicious_activities ?? 0)),
                color: 'var(--ok)',
              },
            ]}
          />
        </Card>
      </div>

      <div className="grid grid-23">
        <Card title="Recent Detections" sub="live feed" actions={<Pill tone={ctx.wsConnected ? 'ok' : 'danger'}>{ctx.wsConnected ? 'Live' : 'Disconnected'}</Pill>}>
          {events.length === 0 && <Empty icon={Icons.eye}>No detections yet — start the pipeline: <code>./scripts/run_defense_demo.sh</code></Empty>}
          {events.slice(0, 8).map((evt, i) => (
            <div key={i} className={`row ${evt.severity === 'critical' ? 'crit' : ''}`}>
              <div>
                <b>{evt.msg}</b>
                <div className="meta">{evt.camera || '—'} · {timeAgo(evt.time)}</div>
              </div>
              <Tag tone={SEVERITY_TONE[evt.severity] || 'muted'}>{evt.severity}</Tag>
            </div>
          ))}
        </Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Card title="Detection Hotspots" sub="last 24h">
            <BarList items={locations.slice(0, 5).map((l) => ({ label: l.location || 'Unknown', value: l.events }))} />
          </Card>
          <Card title="Latest Threat Location">
            {mapAlert ? (
              <MapPin lat={mapAlert.lat} lng={mapAlert.lng} label={mapAlert.cameraName || mapAlert.camera} height={180} />
            ) : (
              <Empty icon={Icons.map}>GPS pin appears on criminal detection</Empty>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}
