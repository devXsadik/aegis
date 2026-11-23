/* Camera registry: health dashboard, registry editor (heading dial, capabilities, credentials,
   webhook token) and CSV bulk import. Every rule is checked again by the server. */
import { useEffect, useRef, useState } from 'react'
import { Icons, Modal } from './ui'
import { Badge, DsIcons, EmptyState, ErrorState, SkeletonList } from './ds'
import {
  cameraCsvTemplateUrl, clearCameraCredentials, fetchCameraDetail, fetchCameraHealth, fetchJurisdictions,
  importCamerasCsv, newIngestToken, setCameraCredentials, updateCamera,
} from '../services/api'
import { useToast } from './Toast'

const STATUS = {
  online: { tone: 'ok', label: 'Online', icon: Icons.check },
  degraded: { tone: 'warn', label: 'Degraded', icon: Icons.alert },
  offline: { tone: 'danger', label: 'Offline', icon: DsIcons.x },
  disabled: { tone: 'muted', label: 'Paused', icon: DsIcons.dot },
  unknown: { tone: 'muted', label: 'Unknown', icon: DsIcons.dot },
}
const CAPS = [
  { id: 'face', label: 'Face' }, { id: 'anpr', label: 'Number plates' },
  { id: 'vehicle_attr', label: 'Vehicle type / colour' }, { id: 'ptz', label: 'PTZ' },
]
const PROTOCOLS = ['rtsp', 'onvif', 'vendor', 'webhook', 'device', 'file']
const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
const compass = (deg) => COMPASS[Math.round(((deg % 360) + 360) % 360 / 45) % 8]
const ago = (s) => (s == null ? 'never' : s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`)

export function CameraStatusBadge({ status }) {
  const st = STATUS[status] || STATUS.unknown
  return <Badge tone={st.tone} icon={st.icon} size="sm">{st.label}</Badge>
}

/* ——— Health ——— */

export function CameraHealth({ onEdit, canEdit }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')
  useEffect(() => {
    let off = false
    const load = () => fetchCameraHealth().then((d) => { if (!off) { setData(d); setError('') } }).catch((e) => { if (!off) setError(e.message) })
    load()
    const t = setInterval(load, 15000)
    return () => { off = true; clearInterval(t) }
  }, [])
  if (error && !data) return <ErrorState compact message={error} />
  if (!data) return <SkeletonList rows={5} label="Loading camera health" />
  const rows = data.cameras.filter((c) => !filter || c.status === filter)
  return (
    <>
      <div className="health-summary" role="group" aria-label="Filter by status">
        {['online', 'degraded', 'offline', 'disabled'].map((s) => (
          <button key={s} type="button" className={`health-tile tone-${STATUS[s].tone}`} aria-pressed={filter === s} onClick={() => setFilter(filter === s ? '' : s)}>
            <b>{data.summary[s]}</b><span>{STATUS[s].label}</span>
          </button>
        ))}
      </div>
      {rows.length === 0 ? <EmptyState compact icon={Icons.camera} title="No cameras in this state" /> : (
        <div className="table-wrap table-stack">
          <table className="table">
            <thead><tr><th scope="col">Camera</th><th scope="col">Status</th><th scope="col">Last report</th><th scope="col">Frame rate</th><th scope="col">Detection</th><th scope="col">Source</th><th scope="col">Capabilities</th>{canEdit && <th scope="col"><span className="sr-only">Edit</span></th>}</tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.camera_id}>
                  <td className="cell-wide"><div className="inc-title-cell"><b>{c.name}</b><span className="meta mono">{c.camera_id}</span></div></td>
                  <td data-label="Status"><div className="inc-title-cell"><CameraStatusBadge status={c.status} />{c.reason && <span className="meta">{c.reason}</span>}</div></td>
                  <td data-label="Last report">{ago(c.last_seen_s)}</td>
                  <td data-label="Frame rate">{c.fps != null ? `${Number(c.fps).toFixed(1)} fps` : '—'}</td>
                  <td data-label="Detection">{c.infer_ms != null ? `${c.infer_ms} ms` : '—'}{c.priority > 0 && <Badge tone="orange" size="sm" icon={Icons.eye}>On lookout</Badge>}</td>
                  <td data-label="Source">{c.protocol}{c.vendor ? ` · ${c.vendor}` : ''}</td>
                  <td data-label="Capabilities">{c.capabilities.length ? c.capabilities.join(', ') : '—'}</td>
                  {canEdit && <td className="cell-wide"><button type="button" className="btn btn-sm" onClick={() => onEdit(c.camera_id)}>Registry</button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

/* ——— Heading dial ——— */

export function HeadingDial({ value, fov = 60, onChange, size = 140 }) {
  const ref = useRef(null)
  const deg = Number.isFinite(value) ? value : 0
  const latest = useRef(deg)            // key repeats arrive faster than re-renders: count from here
  const nudge = (d) => { latest.current = (latest.current + d + 360) % 360; onChange(latest.current) }
  const set = (e) => {
    const r = ref.current.getBoundingClientRect()
    const x = e.clientX - (r.left + r.width / 2)
    const y = e.clientY - (r.top + r.height / 2)
    latest.current = Math.round(((Math.atan2(x, -y) * 180) / Math.PI + 360) % 360)
    onChange(latest.current)
  }
  const half = Math.min(179, (fov || 60) / 2)
  const rad = (a) => ((a - 90) * Math.PI) / 180
  const R = 54
  const cone = `M60 60 L${60 + R * Math.cos(rad(deg - half))} ${60 + R * Math.sin(rad(deg - half))} A${R} ${R} 0 ${half > 90 ? 1 : 0} 1 ${60 + R * Math.cos(rad(deg + half))} ${60 + R * Math.sin(rad(deg + half))} Z`
  return (
    <div className="dial">
      <svg ref={ref} viewBox="0 0 120 120" width={size} height={size} role="slider" tabIndex={0}
        onFocus={() => { latest.current = deg }}
        aria-label="Camera heading" aria-valuemin={0} aria-valuemax={359} aria-valuenow={deg} aria-valuetext={`${deg}° ${compass(deg)}`}
        onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); set(e) }}
        onPointerMove={(e) => { if (e.buttons) set(e) }}
        onKeyDown={(e) => {
          const step = e.shiftKey ? 15 : 1
          if (e.key === 'ArrowRight' || e.key === 'ArrowUp') { e.preventDefault(); nudge(step) }
          if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') { e.preventDefault(); nudge(-step) }
        }}>
        <circle cx="60" cy="60" r="56" className="dial-face" />
        <path d={cone} className="dial-cone" />
        {COMPASS.map((c, i) => {
          const a = rad(i * 45)
          return <text key={c} x={60 + 47 * Math.cos(a)} y={60 + 47 * Math.sin(a) + 3} textAnchor="middle" className={`dial-tick ${i % 2 ? 'minor' : ''}`}>{c}</text>
        })}
        <line x1="60" y1="60" x2={60 + 40 * Math.cos(rad(deg))} y2={60 + 40 * Math.sin(rad(deg))} className="dial-arrow" />
        <circle cx={60 + 40 * Math.cos(rad(deg))} cy={60 + 40 * Math.sin(rad(deg))} r="4" className="dial-head" />
        <circle cx="60" cy="60" r="4" className="dial-head" />
      </svg>
      <div className="dial-read"><b>{deg}°</b> faces {compass(deg)}</div>
    </div>
  )
}

/* ——— Registry editor ——— */

export function CameraRegistryModal({ cameraId, onClose, onSaved }) {
  const { push: toast } = useToast()
  const [cam, setCam] = useState(null)
  const [error, setError] = useState('')
  const [areas, setAreas] = useState([])
  const [form, setForm] = useState(null)
  const [creds, setCreds] = useState({ username: '', password: '' })
  const [token, setToken] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetchCameraDetail(cameraId).then((c) => {
      setCam(c)
      setForm({
        name: c.name, location: c.location || '', address: c.address || '', road_name: c.road_name || '',
        lat: c.lat ?? '', lng: c.lng ?? '', heading: c.heading ?? 0, fov: c.fov ?? 60, protocol: c.protocol || 'rtsp',
        vendor: c.vendor || '', rtsp_url: '', capabilities: c.capabilities || [], ir_mode: !!c.ir_mode,
        sample_fps: c.sample_fps ?? '', jurisdiction_id: c.jurisdiction_id ?? '',
      })
    }).catch((e) => setError(e.message))
    fetchJurisdictions(false).then(setAreas).catch(() => {})
  }, [cameraId])

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const num = (v) => (v === '' || v == null ? null : Number(v))

  const save = async () => {
    setBusy(true)
    try {
      const body = {
        camera_id: cam.camera_id, name: form.name.trim(), location: form.location.trim() || null,
        address: form.address.trim() || null, road_name: form.road_name.trim() || null,
        lat: num(form.lat), lng: num(form.lng), heading: num(form.heading), fov: num(form.fov), protocol: form.protocol,
        vendor: form.vendor.trim() || null, capabilities: form.capabilities, ir_mode: form.ir_mode,
        sample_fps: num(form.sample_fps), jurisdiction_id: form.jurisdiction_id === '' ? null : Number(form.jurisdiction_id),
      }
      if (form.rtsp_url.trim()) body.rtsp_url = form.rtsp_url.trim()
      await updateCamera(cam.camera_id, body)
      if (creds.username && creds.password) await setCameraCredentials(cam.camera_id, creds.username, creds.password)
      toast(`${form.name} saved`, 'ok')
      onSaved?.()
      onClose()
    } catch (e) {
      toast(e.message || 'Could not save camera', 'danger')
    } finally {
      setBusy(false)
    }
  }

  const issueToken = async () => {
    try {
      setToken(await newIngestToken(cam.camera_id))
      toast('New webhook token issued: copy it now, it is not shown again', 'warn')
    } catch (e) {
      toast(e.message || 'Could not issue token', 'danger')
    }
  }

  return (
    <Modal className="reg-modal" title={cam ? `Registry — ${cam.name}` : 'Camera registry'} onClose={onClose}
      footer={(
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={!form || busy || !form.name.trim()} onClick={save}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      )}>
      {error && <ErrorState compact message={error} />}
      {!form && !error && <SkeletonList rows={3} />}
      {form && (
        <div className="reg-grid">
          <div className="reg-col">
            <label className="field">Name<input className="input" value={form.name} maxLength={100} onChange={set('name')} /></label>
            <label className="field">Address<input className="input" value={form.address} maxLength={200} onChange={set('address')} placeholder="House 12, Road 45, Gulshan 2" /></label>
            <div className="settings-grid">
              <label className="field">Road / segment<input className="input" value={form.road_name} maxLength={120} onChange={set('road_name')} placeholder="Gulshan Avenue" /></label>
              <label className="field">Area (thana)
                <select className="input" value={form.jurisdiction_id} onChange={set('jurisdiction_id')}>
                  <option value="">From position on the map</option>
                  {areas.map((a) => <option key={a.id} value={a.id}>{a.name_en} ({a.level})</option>)}
                </select>
              </label>
              <label className="field">Latitude<input className="input mono" inputMode="decimal" value={form.lat} onChange={set('lat')} /></label>
              <label className="field">Longitude<input className="input mono" inputMode="decimal" value={form.lng} onChange={set('lng')} /></label>
              <label className="field">Protocol
                <select className="input" value={form.protocol} onChange={set('protocol')}>{PROTOCOLS.map((p) => <option key={p} value={p}>{p}</option>)}</select>
              </label>
              <label className="field">Vendor<input className="input" list="vendors" value={form.vendor} maxLength={30} onChange={set('vendor')} /></label>
            </div>
            <datalist id="vendors">{['hikvision', 'dahua', 'uniview', 'axis', 'generic'].map((v) => <option key={v} value={v} />)}</datalist>
            <label className="field">Stream URL {cam.has_credentials && <span className="muted">(credentials stored separately)</span>}
              <input className="input mono" value={form.rtsp_url} onChange={set('rtsp_url')} placeholder="Leave empty to keep the current URL" autoComplete="off" />
            </label>
            <fieldset className="reg-fs">
              <legend>Capabilities</legend>
              {CAPS.map((c) => (
                <label key={c.id} className="off-area-opt">
                  <input type="checkbox" checked={form.capabilities.includes(c.id)}
                    onChange={() => setForm({ ...form, capabilities: form.capabilities.includes(c.id) ? form.capabilities.filter((x) => x !== c.id) : [...form.capabilities, c.id] })} />
                  {c.label}
                </label>
              ))}
              <label className="off-area-opt"><input type="checkbox" checked={form.ir_mode} onChange={set('ir_mode')} /> Infrared / night mode (colour is unreliable at night)</label>
            </fieldset>
          </div>
          <div className="reg-col">
            <div className="field">Heading — drag the arrow, or use the arrow keys
              <HeadingDial value={Number(form.heading) || 0} fov={Number(form.fov) || 60} onChange={(h) => setForm({ ...form, heading: h })} />
            </div>
            <div className="settings-grid">
              <label className="field">Field of view (°)<input className="input" type="number" min={1} max={360} value={form.fov} onChange={set('fov')} /></label>
              <label className="field">Frames analysed / s<input className="input" type="number" min={0.1} max={60} step={0.5} value={form.sample_fps} onChange={set('sample_fps')} placeholder="default" /></label>
            </div>
            <fieldset className="reg-fs">
              <legend><DsIcons.lock /> Camera login</legend>
              <p className="ds-setting-hint" style={{ marginTop: 0 }}>{cam.has_credentials ? 'Stored, encrypted. Enter new ones to replace them.' : 'None stored.'} Never shown again after saving.</p>
              <div className="settings-grid">
                <input className="input" aria-label="Camera username" placeholder="Username" autoComplete="off" value={creds.username} onChange={(e) => setCreds({ ...creds, username: e.target.value })} />
                <input className="input" aria-label="Camera password" placeholder="Password" type="password" autoComplete="new-password" value={creds.password} onChange={(e) => setCreds({ ...creds, password: e.target.value })} />
              </div>
              {cam.has_credentials && <button type="button" className="link-btn" onClick={async () => { await clearCameraCredentials(cam.camera_id); setCam({ ...cam, has_credentials: false }); toast('Credentials removed', 'ok') }}>Remove stored login</button>}
            </fieldset>
            <fieldset className="reg-fs">
              <legend>Event webhook (AI cameras)</legend>
              {!token && <p className="ds-setting-hint" style={{ marginTop: 0 }}>{cam.has_ingest_token ? 'A token is active. Issuing a new one replaces it.' : 'No token yet.'}</p>}
              {token && (
                <div className="token-box">
                  <div><span className="muted">POST</span> <code>{token.url}</code></div>
                  <div><span className="muted">{token.header}:</span> <code className="token">{token.token}</code></div>
                  <button type="button" className="btn btn-sm" onClick={() => navigator.clipboard?.writeText(token.token).then(() => toast('Token copied', 'ok'))}>Copy token</button>
                </div>
              )}
              <button type="button" className="btn btn-sm" onClick={issueToken}>{cam.has_ingest_token ? 'Issue new token' : 'Issue token'}</button>
            </fieldset>
          </div>
        </div>
      )}
    </Modal>
  )
}

/* ——— CSV import ——— */

export function CameraImportModal({ onClose, onDone }) {
  const { push: toast } = useToast()
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const check = async (f) => {
    setFile(f); setPreview(null)
    if (!f) return
    setBusy(true)
    try { setPreview(await importCamerasCsv(f, true)) } catch (e) { toast(e.message || 'Could not read CSV', 'danger') } finally { setBusy(false) }
  }
  const run = async () => {
    setBusy(true)
    try {
      const r = await importCamerasCsv(file, false)
      toast(`${r.valid} camera(s) imported`, 'ok')
      onDone?.()
      onClose()
    } catch (e) {
      toast(e.message || 'Import failed', 'danger')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal title="Import cameras from CSV" onClose={onClose}
      footer={(
        <div className="off-picker-foot">
          <a className="link-btn" href={cameraCsvTemplateUrl()} download>Download template</a>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            <button type="button" className="btn btn-primary" disabled={busy || !preview || preview.invalid > 0 || !preview.valid} onClick={run}>
              {busy ? 'Working…' : preview ? `Import ${preview.valid}` : 'Import'}
            </button>
          </div>
        </div>
      )}>
      <label className="field">CSV file (UTF-8; one camera per row; existing IDs are updated)
        <input className="input" type="file" accept=".csv,text/csv" onChange={(e) => check(e.target.files[0])} />
      </label>
      {busy && !preview && <SkeletonList rows={3} />}
      {preview && (
        <>
          <p className="ds-setting-hint">{preview.valid} row(s) ready{preview.invalid ? `, ${preview.invalid} with problems — nothing is imported until all rows are fixed` : ''}.</p>
          <div className="table-wrap" style={{ maxHeight: 300 }}>
            <table className="table">
              <thead><tr><th>Line</th><th>Camera</th><th>Result</th></tr></thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.line}>
                    <td>{r.line}</td><td className="mono">{r.camera_id || '—'}</td>
                    <td>{r.ok ? <Badge tone="ok" size="sm" icon={Icons.check}>{r.action}</Badge> : <Badge tone="danger" size="sm" icon={Icons.alert}>{r.error}</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Modal>
  )
}
