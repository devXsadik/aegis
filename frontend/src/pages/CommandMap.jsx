/* Live command-centre map (spec 11): cameras coloured by status, cameras on a lookout, target
   trails with direction arrows and times, predicted path to the next cameras, officer positions,
   recent alerts; filter by division / district / thana. Click a camera for its live view, a trail
   point for its snapshot. Refreshes every 10 s and on every incident change. */
import { useCallback, useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Card, Icons, timeAgo } from '../components/ui'
import { Badge, EmptyState, ErrorState } from '../components/ds'
import { CameraStatusBadge } from '../components/CameraRegistry'
import { fetchCommandMap, fetchJurisdictions, liveStreamUrl } from '../services/api'
import { useWebSocket } from '../hooks/useWebSocket'
import { eventLabel } from '../lib/events'

const LAYER = {
  cameras: { label: 'Cameras', icon: Icons.camera },
  tracks: { label: 'Target paths', icon: Icons.dispatch },
  officers: { label: 'Officers', icon: Icons.users },
  alerts: { label: 'Alerts', icon: Icons.alert },
}

const TILE_URL = import.meta.env.VITE_MAP_TILES || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || '#888'
const STATUS_COLOR = { online: '--ok', degraded: '--warn', offline: '--danger', disabled: '--text-3', unknown: '--text-3' }
const SEV_COLOR = { critical: '--danger', high: '--orange', medium: '--warn', low: '--ok', info: '--primary' }
const ARROW = { N: '↑', NE: '↗', E: '→', SE: '↘', S: '↓', SW: '↙', W: '←', NW: '↖' }
const TRACK_COLORS = ['--danger', '--purple', '--cyan', '--orange', '--warn']

function cone(lat, lng, heading, fov = 60, r = 0.0012) {
  const pts = [[lat, lng]]
  for (let a = heading - fov / 2; a <= heading + fov / 2; a += fov / 8) {
    const rad = (a * Math.PI) / 180
    pts.push([lat + r * Math.cos(rad), lng + (r * Math.sin(rad)) / Math.cos((lat * Math.PI) / 180)])
  }
  return pts
}

/* Follow mode: the camera that last saw the target, then the cameras it should reach next (with the
   expected arrival window), live. Moves along by itself as the target is seen on the next camera. */
function FollowWall({ track, online, onClose }) {
  const mins = (s) => (s == null ? '?' : Math.max(0, Math.round(s / 60)))
  const tiles = [
    { camera_id: track.last_camera, name: track.trail?.[track.trail.length - 1]?.label || track.last_camera, role: 'Last seen', when: `${timeAgo(track.last_seen)}` },
    ...track.predicted.slice(0, 5).map((p) => ({ camera_id: p.camera_id, name: p.name, role: `Next (ring ${p.ring})`,
      when: p.eta_from_s != null ? `expected in ${mins(p.eta_from_s)}–${mins(p.eta_to_s)} min` : '' })),
  ].filter((t, i, all) => t.camera_id && all.findIndex((x) => x.camera_id === t.camera_id) === i)
  return (
    <section className="follow-wall" aria-label={`Following ${track.label}`}>
      <header>
        <div>
          <h2>Following {track.label}</h2>
          <span className="meta">{track.direction ? `Moving ${track.direction} · ` : ''}{track.lookout ? `Lookout ${track.lookout} · ` : ''}updates by itself when the target is seen again</span>
        </div>
        <button type="button" className="btn btn-sm" onClick={onClose}><Icons.close /> Stop following</button>
      </header>
      <div className="follow-tiles">
        {tiles.map((t, i) => (
          <figure key={t.camera_id} className={`follow-tile ${i === 0 ? 'main' : ''}`}>
            {online.has(t.camera_id)
              ? <img src={liveStreamUrl(t.camera_id)} alt={`Live view from ${t.name}`} />
              : <div className="follow-off"><Icons.camera /><span>No live video from this camera</span></div>}
            <figcaption><Badge tone={i === 0 ? 'danger' : 'orange'} size="sm">{t.role}</Badge> <b>{t.name}</b> <span className="muted">{t.when}</span></figcaption>
          </figure>
        ))}
      </div>
    </section>
  )
}

export function CommandMap({ ctx }) {
  const host = useRef(null)
  const map = useRef(null)
  const layers = useRef({})
  const fitted = useRef(false)
  const [data, setData] = useState(null)
  const [following, setFollowing] = useState(null)        // track id shown on the video wall
  const [error, setError] = useState('')
  const [areas, setAreas] = useState([])
  const [area, setArea] = useState('')
  const [show, setShow] = useState({ cameras: true, tracks: true, officers: true, alerts: true })
  const [picked, setPicked] = useState(null)        // {type: 'camera'|'point', ...}
  const [tick, setTick] = useState(0)

  useEffect(() => { fetchJurisdictions(false).then(setAreas).catch(() => {}) }, [])
  useEffect(() => {
    let off = false
    fetchCommandMap(area).then((d) => { if (!off) { setData(d); setError('') } }).catch((e) => { if (!off) setError(e.message) })
    return () => { off = true }
  }, [area, tick])
  useEffect(() => { const t = setInterval(() => setTick((n) => n + 1), 10000); return () => clearInterval(t) }, [])
  const onLive = useCallback(() => setTick((n) => n + 1), [])
  useWebSocket('incidents', onLive, !!ctx?.me)

  useEffect(() => {
    const m = L.map(host.current, { preferCanvas: true }).setView([23.78, 90.40], 12)
    L.tileLayer(TILE_URL, { maxZoom: 19, attribution: '© OpenStreetMap contributors' }).addTo(m)
    for (const k of ['cameras', 'tracks', 'officers', 'alerts']) layers.current[k] = L.layerGroup().addTo(m)
    map.current = m
    const t = setTimeout(() => m.invalidateSize(), 150)
    return () => { clearTimeout(t); m.remove() }
  }, [])

  useEffect(() => {
    const m = map.current
    if (!m || !data) return
    Object.values(layers.current).forEach((g) => g.clearLayers())
    const bounds = []
    if (show.cameras) {
      data.cameras.forEach((c) => {
        const color = css(STATUS_COLOR[c.status] || '--text-3')
        if (c.heading != null) L.polygon(cone(c.lat, c.lng, c.heading, c.fov || 60), { color, weight: 1, fillOpacity: 0.12 }).addTo(layers.current.cameras)
        if (c.on_lookout) L.circleMarker([c.lat, c.lng], { radius: 14, color: css('--orange'), weight: 3, fill: false, className: 'lookout-ring' }).addTo(layers.current.cameras)
        L.circleMarker([c.lat, c.lng], { radius: 7, color: '#fff', weight: 2, fillColor: color, fillOpacity: 1 })
          .bindTooltip(`${c.name} · ${c.status}${c.on_lookout ? ' · on lookout' : ''}`)
          .on('click', () => setPicked({ type: 'camera', ...c }))
          .addTo(layers.current.cameras)
        bounds.push([c.lat, c.lng])
      })
    }
    if (show.tracks) {
      data.tracks.forEach((t, i) => {
        const color = css(TRACK_COLORS[i % TRACK_COLORS.length])
        const pts = t.trail.filter((p) => p.lat != null)
        if (pts.length > 1) L.polyline(pts.map((p) => [p.lat, p.lng]), { color, weight: 4 }).addTo(layers.current.tracks)
        pts.forEach((p, j) => {
          L.marker([p.lat, p.lng], {
            icon: L.divIcon({ className: 'trail-pin', html: `<span style="background:${color}">${ARROW[p.direction] || (j + 1)}</span>`, iconSize: [22, 22] }),
          }).bindTooltip(`${t.label} · ${p.label} · ${new Date(p.at).toLocaleTimeString()}${p.direction ? ` · ${p.direction}` : ''}${p.consistent === false ? ' · implausible' : ''}`)
            .on('click', () => setPicked({ type: 'point', track: t, ...p }))
            .addTo(layers.current.tracks)
        })
        const last = pts[pts.length - 1]
        if (last) {
          t.predicted.filter((p) => p.lat != null).forEach((p) => {
            L.polyline([[last.lat, last.lng], [p.lat, p.lng]], { color, weight: 2, dashArray: '6 6', opacity: 0.8 })
              .bindTooltip(`Predicted: ${p.name} · ETA ${Math.round(p.eta_from_s / 60)}–${Math.round(p.eta_to_s / 60)} min`)
              .addTo(layers.current.tracks)
          })
          bounds.push([last.lat, last.lng])
        }
      })
    }
    if (show.officers) {
      data.officers.forEach((o) => {
        L.marker([o.lat, o.lng], { icon: L.divIcon({ className: 'officer-pin', html: `<span>${(o.name || '?').split(' ').map((w) => w[0]).join('').slice(0, 2)}</span>`, iconSize: [26, 26] }) })
          .bindTooltip(`${o.rank ? `${o.rank} ` : ''}${o.name} · ${o.duty_status.replace('_', ' ')} · ${timeAgo(o.seen)}`)
          .addTo(layers.current.officers)
      })
    }
    if (show.alerts) {
      data.alerts.forEach((a) => {
        L.circleMarker([a.lat, a.lng], { radius: 4, color: css(SEV_COLOR[a.severity] || '--warn'), fillOpacity: 0.9 })
          .bindTooltip(`${eventLabel(a.type)} · ${timeAgo(a.at)}`).addTo(layers.current.alerts)
      })
    }
    if (!fitted.current && bounds.length) {
      m.fitBounds(L.latLngBounds(bounds).pad(0.2), { maxZoom: 15 })
      fitted.current = true
    }
  }, [data, show])

  return (
    <div className="cmd">
      <div className="cmd-bar">
        <select className="input" value={area} onChange={(e) => { setArea(e.target.value); fitted.current = false }} aria-label="Area">
          <option value="">All areas</option>
          {areas.map((a) => <option key={a.id} value={a.id}>{a.level === 'thana' ? '— ' : a.level === 'district' ? '· ' : ''}{a.name_en}</option>)}
        </select>
        <div className="inc-chipset" role="group" aria-label="Layers">
          <span className="chip-label" aria-hidden="true">Show</span>
          {Object.keys(show).map((k) => (
            <button key={k} type="button" className="inc-chip layer-chip" aria-pressed={show[k]} onClick={() => setShow({ ...show, [k]: !show[k] })}>
              {(() => { const I = LAYER[k].icon; return <I /> })()} {LAYER[k].label}
            </button>
          ))}
        </div>
        {data && (
          <div className="cmd-stats">
            <Badge tone="muted" size="sm" icon={Icons.camera}>{data.summary.cameras} cameras</Badge>
            {data.summary.offline > 0 && <Badge tone="danger" size="sm">{data.summary.offline} offline</Badge>}
            {data.summary.on_lookout > 0 && <Badge tone="orange" size="sm" icon={Icons.eye}>{data.summary.on_lookout} on lookout</Badge>}
            <Badge tone={data.summary.tracks ? 'danger' : 'muted'} size="sm" icon={Icons.dispatch}>{data.summary.tracks} target(s) moving</Badge>
          </div>
        )}
      </div>
      {error && <ErrorState compact message={error} onRetry={() => setTick((n) => n + 1)} />}
      {following && data?.tracks.find((t) => t.id === following) && (
        <FollowWall track={data.tracks.find((t) => t.id === following)} onClose={() => setFollowing(null)}
          online={new Set(data.cameras.filter((c) => c.status === 'online').map((c) => c.camera_id))} />
      )}
      <div className="cmd-grid">
        <div ref={host} className="cmd-map" role="application" aria-label="Command map" />
        <aside className="cmd-side">
          {picked?.type === 'camera' && (
            <Card title={picked.name} sub={picked.camera_id} actions={<button type="button" className="icon-btn" aria-label="Close" onClick={() => setPicked(null)}><Icons.close /></button>}>
              <CameraStatusBadge status={picked.status} /> {picked.on_lookout && <Badge tone="orange" size="sm" icon={Icons.eye}>On lookout</Badge>}
              {picked.status === 'online' && <img className="cmd-live" src={liveStreamUrl(picked.camera_id)} alt={`Live view from ${picked.name}`} />}
              {picked.reason && <p className="meta">{picked.reason}</p>}
              <p className="meta">Recent here: {data?.alerts.filter((a) => a.camera_id === picked.camera_id).slice(0, 5).map((a) => eventLabel(a.type)).join(', ') || 'nothing in the last hours'}</p>
            </Card>
          )}
          {picked?.type === 'point' && (
            <Card title={picked.track.label} sub={`${picked.label} · ${new Date(picked.at).toLocaleTimeString()}`} actions={<button type="button" className="icon-btn" aria-label="Close" onClick={() => setPicked(null)}><Icons.close /></button>}>
              {picked.snapshot ? <img className="cmd-live" src={picked.snapshot} alt={`Snapshot at ${picked.label}`} /> : <p className="meta">No snapshot for this sighting.</p>}
              {picked.direction && <Badge tone="cyan" size="sm">Moving {picked.direction}</Badge>}
              {picked.consistent === false && <Badge tone="warn" size="sm">Travel time implausible</Badge>}
              {picked.track.incident_id && <button type="button" className="btn btn-sm" onClick={() => ctx.setPage('incidents')}><Icons.incident /> Open incidents</button>}
            </Card>
          )}
          <Card title="Targets being followed" flush>
            {!data?.tracks.length && <EmptyState compact icon={Icons.dispatch} title="No active targets">Confirmed watchlist sightings show up here with their path.</EmptyState>}
            <ul className="wl-list">
              {data?.tracks.map((t, i) => (
                <li key={t.id} className="wl-item">
                  <span className="track-dot" style={{ background: css(TRACK_COLORS[i % TRACK_COLORS.length]) }} />
                  <div className="wl-main">
                    <div className="wl-title"><b>{t.label}</b>{t.verified ? <Badge tone="danger" size="sm">Confirmed</Badge> : <Badge tone="warn" size="sm">Unverified</Badge>}{t.direction && <Badge tone="cyan" size="sm">{ARROW[t.direction]} {t.direction}</Badge>}</div>
                    <div className="meta">Last {t.last_camera} · {timeAgo(t.last_seen)}{t.predicted.length ? ` · next: ${t.predicted.map((p) => p.name).slice(0, 3).join(', ')}` : ''}</div>
                  </div>
                  <div className="wl-actions">
                    <button type="button" className={`btn btn-sm ${following === t.id ? '' : 'btn-primary'}`} aria-pressed={following === t.id}
                      onClick={() => setFollowing(following === t.id ? null : t.id)}>{following === t.id ? 'Following' : 'Follow on video'}</button>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </aside>
      </div>
    </div>
  )
}
