/* Command reports: how fast incidents are answered, when and where they happen, camera uptime.
   Numbers come from GET /reports/response-times | patterns | camera-uptime (timeline-based). */
import { useEffect, useState } from 'react'
import { Card, Icons, Seg, Stat } from '../components/ui'
import { BarList } from '../components/charts'
import { Badge, EmptyState, ErrorState, SkeletonList } from '../components/ds'
import { fetchCameraUptime, fetchJurisdictions, fetchPatterns, fetchResponseTimes } from '../services/api'

const DAYS = [{ value: 7, label: '7 days' }, { value: 30, label: '30 days' }, { value: 90, label: '90 days' }]
const STAGE = [
  { id: 'dispatch', label: 'Officer assigned', hint: 'From the incident opening to the first officer assigned' },
  { id: 'acknowledge', label: 'Officer answered', hint: 'To the first “Seen it” / “On my way”' },
  { id: 'arrive', label: 'Officer on scene', hint: 'To the first officer on scene (or target located)' },
  { id: 'resolve', label: 'Resolved', hint: 'To the incident marked resolved' },
]
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function dur(s) {
  if (s == null) return '—'
  if (s < 60) return `${Math.round(s)} s`
  if (s < 3600) return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`.replace(' 0 s', '')
  const h = Math.floor(s / 3600)
  return `${h} h ${Math.round((s % 3600) / 60)} min`.replace(' 0 min', '')
}

function useReport(fn, deps) {
  const [state, setState] = useState({ data: null, error: '', key: null })
  const key = JSON.stringify(deps)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let off = false
    fn().then((data) => { if (!off) setState({ data, error: '', key }) })
      .catch((e) => { if (!off) setState({ data: null, error: e.message || 'Could not load the report', key }) })
    return () => { off = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt])
  return { ...state, loading: state.key !== key, retry: () => setAttempt((n) => n + 1) }
}

function AreaPicker({ value, onChange }) {
  const [areas, setAreas] = useState([])
  useEffect(() => { fetchJurisdictions(false).then((d) => setAreas(Array.isArray(d) ? d : d?.items || [])).catch(() => {}) }, [])
  if (!areas.length) return null
  return (
    <label className="chip-label rpt-area">
      Area
      <select className="input" value={value ?? ''} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">All areas</option>
        {areas.map((a) => <option key={a.id} value={a.id}>{a.name_en}{a.level && a.level !== 'thana' ? ` (${a.level})` : ''}</option>)}
      </select>
    </label>
  )
}

function Filters({ days, setDays, area, setArea, showArea = true }) {
  return (
    <div className="rpt-filters">
      <Seg value={days} onChange={setDays} options={DAYS} />
      {showArea && <AreaPicker value={area} onChange={setArea} />}
    </div>
  )
}

function Body({ r, children }) {
  if (r.loading) return <SkeletonList rows={4} label="Loading report" />
  if (r.error) return <ErrorState compact message={r.error} onRetry={r.retry} />
  return children
}

export function ResponseTimes() {
  const [days, setDays] = useState(30)
  const [area, setArea] = useState(null)
  const r = useReport(() => fetchResponseTimes(days, area), [days, area])
  const d = r.data
  return (
    <div className="stack-page">
      <Filters days={days} setDays={setDays} area={area} setArea={setArea} />
      <Body r={r}>
        {d && d.incidents === 0 && <EmptyState icon={Icons.clock} title="No incidents in this period">Response times appear once incidents are opened and officers answer them.</EmptyState>}
        {d && d.incidents > 0 && (
          <>
            <div className="grid grid-4">
              {STAGE.map((s) => (
                <Stat key={s.id} label={`${s.label} (median)`} value={dur(d.overall[s.id].median_s)}
                  delta={d.overall[s.id].n ? `90 % within ${dur(d.overall[s.id].p90_s)} · ${d.overall[s.id].n} incidents` : 'not reached yet'}
                  accent={s.id === 'arrive' ? 'warn' : 'primary'} icon={Icons.clock} />
              ))}
            </div>
            <Card title="By priority" sub={`${d.incidents} incidents in the last ${d.days} days · median, and the time 90 % were within`} flush>
              <div className="table-wrap table-stack">
                <table className="table">
                  <thead><tr><th scope="col">Priority</th>{STAGE.map((s) => <th key={s.id} scope="col" title={s.hint}>{s.label}</th>)}</tr></thead>
                  <tbody>
                    {['critical', 'high', 'medium', 'low'].filter((p) => d.by_priority[p]).map((p) => (
                      <tr key={p}>
                        <td className="cell-wide"><Badge tone={{ critical: 'danger', high: 'orange', medium: 'warn', low: 'muted' }[p]} size="sm">{p}</Badge></td>
                        {STAGE.map((s) => <td key={s.id} data-label={s.label}>{dur(d.by_priority[p][s.id].median_s)} <span className="muted">/ {dur(d.by_priority[p][s.id].p90_s)}</span></td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="By area" sub="Slowest arrival first. Areas with long arrival times may need more officers on duty" flush>
              <div className="table-wrap table-stack">
                <table className="table">
                  <thead><tr><th scope="col">Area</th><th scope="col">Incidents</th>{STAGE.map((s) => <th key={s.id} scope="col" title={s.hint}>{s.label}</th>)}</tr></thead>
                  <tbody>
                    {d.by_area.map((a) => (
                      <tr key={a.jurisdiction_id ?? 'none'}>
                        <td className="cell-wide"><b>{a.name}</b></td>
                        <td data-label="Incidents">{a.incidents}</td>
                        {STAGE.map((s) => <td key={s.id} data-label={s.label}>{dur(a[s.id].median_s)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}
      </Body>
    </div>
  )
}

function Heatmap({ grid }) {
  const max = Math.max(1, ...grid.flat())
  return (
    <div className="heat" role="table" aria-label="Incidents by weekday and hour">
      <div className="heat-row heat-head" role="row">
        <span role="columnheader" />
        {Array.from({ length: 24 }, (_, h) => <span key={h} role="columnheader" className="heat-h">{h % 3 === 0 ? String(h).padStart(2, '0') : ''}</span>)}
      </div>
      {grid.map((row, d) => (
        <div className="heat-row" role="row" key={d}>
          <span role="rowheader" className="heat-d">{WEEKDAYS[d]}</span>
          {row.map((n, h) => (
            <span key={h} role="cell" className="heat-cell" title={`${WEEKDAYS[d]} ${String(h).padStart(2, '0')}:00 — ${n} incident${n === 1 ? '' : 's'}`}
              style={{ '--a': n ? 0.15 + 0.85 * (n / max) : 0 }}>{n ? <span className="sr-only">{n}</span> : null}</span>
          ))}
        </div>
      ))}
    </div>
  )
}

export function Patterns() {
  const [days, setDays] = useState(30)
  const [area, setArea] = useState(null)
  const r = useReport(() => fetchPatterns(days, area), [days, area])
  const d = r.data
  const change = d && d.previous ? Math.round(((d.incidents - d.previous) / d.previous) * 100) : null
  return (
    <div className="stack-page">
      <Filters days={days} setDays={setDays} area={area} setArea={setArea} />
      <Body r={r}>
        {d && (
          <>
            <div className="grid grid-3">
              <Stat label="Incidents" value={d.incidents} delta={change == null ? `last ${d.days} days` : `${change > 0 ? '+' : ''}${change} % vs the ${d.days} days before`} accent={change > 0 ? 'danger' : 'ok'} icon={Icons.incident} />
              <Stat label="Busiest time" value={d.peak ? `${WEEKDAYS[d.peak.weekday]} ${String(d.peak.hour).padStart(2, '0')}:00` : '—'} delta={d.peak ? `${d.peak.count} incident${d.peak.count === 1 ? '' : 's'} in that hour` : 'no incidents yet'} icon={Icons.clock} />
              <Stat label="Most common" value={d.by_type[0]?.type?.replace(/_/g, ' ').toLowerCase() || '—'} delta={d.by_type[0] ? `${d.by_type[0].count} incident${d.by_type[0].count === 1 ? '' : 's'}` : ''} icon={Icons.alert} />
            </div>
            <Card title="When incidents happen" sub={`Weekday and hour, ${d.timezone} time. Darker = more incidents. Plan patrols and shifts around the dark cells`}>
              {d.incidents ? <Heatmap grid={d.grid} /> : <EmptyState compact icon={Icons.clock} title="No incidents in this period" />}
            </Card>
            <div className="grid grid-2">
              <Card title="Where" sub={`Incidents per area, with the change against the ${d.days} days before`} flush>
                {d.by_area.length === 0 ? <div style={{ padding: 16 }}><EmptyState compact icon={Icons.map} title="No incidents" /></div> : (
                  <ul className="rpt-areas">
                    {d.by_area.map((a) => (
                      <li key={a.jurisdiction_id ?? 'none'}>
                        <b>{a.name}</b>
                        <span>{a.incidents}</span>
                        {a.change_pct == null ? <span className="muted">new</span>
                          : <Badge tone={a.change_pct > 0 ? 'danger' : a.change_pct < 0 ? 'ok' : 'muted'} size="sm">{a.change_pct > 0 ? '+' : ''}{a.change_pct} %</Badge>}
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card title="What" sub="Most common incident types">
                <BarList items={d.by_type.map((t) => ({ label: t.type.replace(/_/g, ' ').toLowerCase(), value: t.count }))} emptyText="No incidents in this period" />
              </Card>
            </div>
          </>
        )}
      </Body>
    </div>
  )
}

export function CameraUptime() {
  const [days, setDays] = useState(7)
  const r = useReport(() => fetchCameraUptime(days), [days])
  const d = r.data
  const down = d?.cameras.filter((c) => c.down_now) || []
  return (
    <div className="stack-page">
      <Filters days={days} setDays={setDays} showArea={false} />
      <Body r={r}>
        {d && (
          <>
            <div className="grid grid-3">
              <Stat label="Camera uptime" value={d.fleet_uptime_pct == null ? '—' : `${d.fleet_uptime_pct} %`} delta={`active cameras, last ${d.days} days`} accent={d.fleet_uptime_pct >= 99 ? 'ok' : 'warn'} icon={Icons.camera} />
              <Stat label="Down now" value={down.length} delta={down.length ? down.slice(0, 3).map((c) => c.name).join(', ') : 'all reporting'} accent={down.length ? 'danger' : 'ok'} icon={Icons.alert} />
              <Stat label="Outages" value={d.cameras.reduce((s, c) => s + c.outages, 0)} delta="camera stopped reporting while switched on" icon={Icons.clock} />
            </div>
            <Card title="Per camera" sub="Worst first. Outages come from the health watch (camera offline / restored alerts)" flush>
              {d.cameras.length === 0 ? <div style={{ padding: 16 }}><EmptyState compact icon={Icons.camera} title="No cameras registered" /></div> : (
                <div className="table-wrap table-stack">
                  <table className="table">
                    <thead><tr><th scope="col">Camera</th><th scope="col">Uptime</th><th scope="col">Outages</th><th scope="col">Downtime</th><th scope="col">Longest</th><th scope="col">Now</th></tr></thead>
                    <tbody>
                      {d.cameras.map((c) => (
                        <tr key={c.camera_id}>
                          <td className="cell-wide"><b>{c.name}</b>{c.location && c.location !== c.name && <div className="muted">{c.location}</div>}</td>
                          <td data-label="Uptime">
                            <span className="rpt-meter"><span style={{ width: `${c.uptime_pct}%` }} className={c.uptime_pct >= 99 ? 'ok' : c.uptime_pct >= 95 ? 'warn' : 'bad'} /></span>
                            {' '}{c.uptime_pct} %
                          </td>
                          <td data-label="Outages">{c.outages}</td>
                          <td data-label="Downtime">{dur(c.downtime_s)}</td>
                          <td data-label="Longest">{dur(c.longest_outage_s)}</td>
                          <td data-label="Now">{!c.active ? <Badge tone="muted" size="sm">Switched off</Badge> : c.down_now ? <Badge tone="danger" size="sm">Down</Badge> : <Badge tone="ok" size="sm">Reporting</Badge>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </>
        )}
      </Body>
    </div>
  )
}
