/* Evidence upload: drag-and-drop, file picker, phone camera; each file uploads on its own with
   a progress bar and a Retry; then "Processing faces…". Linked incident is required. */
import { useEffect, useRef, useState } from 'react'
import { Icons } from './ui'
import { Badge } from './ds'
import { fetchIncidentsPage, uploadEvidenceFile } from '../services/api'
import { useToast } from './Toast'

const ACCEPT = 'image/jpeg,image/png,image/webp,image/heic,video/mp4,video/quicktime,video/webm,audio/mpeg,audio/mp4,audio/wav,audio/webm,application/pdf'
const MAX_MB = 100
const kindOf = (f) => (f.type.startsWith('image/') ? 'Photo' : f.type.startsWith('video/') ? 'Video' : f.type.startsWith('audio/') ? 'Audio' : f.type === 'application/pdf' ? 'PDF' : 'Unsupported')
const human = (n) => (n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.ceil(n / 1e3)} KB`)
const localNow = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16) }

export function EvidenceUploader({ incidentId: fixedIncident, onUploaded }) {
  const { push: toast } = useToast()
  const [incidents, setIncidents] = useState([])
  const [incidentId, setIncidentId] = useState(fixedIncident || '')
  const [meta, setMeta] = useState({ description: '', location: '', lat: '', lng: '', captured_at: localNow() })
  const [queue, setQueue] = useState([])        // {id, file, progress, status: ready|uploading|done|error, error, result}
  const [drag, setDrag] = useState(false)
  const pick = useRef(null)
  const cam = useRef(null)

  useEffect(() => {
    if (fixedIncident) return
    fetchIncidentsPage({ limit: 100, sort: '-created_at' }).then((d) => setIncidents(d.items)).catch(() => {})
  }, [fixedIncident])

  const add = (files) => {
    const items = [...files].map((file) => {
      const bad = kindOf(file) === 'Unsupported' ? 'File type not accepted' : file.size > MAX_MB * 1024 * 1024 ? `Larger than ${MAX_MB} MB` : null
      return { id: `${file.name}-${file.size}-${Math.random()}`, file, progress: 0, status: bad ? 'error' : 'ready', error: bad }
    })
    setQueue((q) => [...q, ...items])
  }
  const set = (id, patch) => setQueue((q) => q.map((x) => (x.id === id ? { ...x, ...patch } : x)))

  const send = async (it) => {
    set(it.id, { status: 'uploading', progress: 0, error: null })
    try {
      const r = await uploadEvidenceFile(it.file, {
        incident_id: incidentId, description: meta.description, location: meta.location, lat: meta.lat, lng: meta.lng,
        captured_at: meta.captured_at ? new Date(meta.captured_at).toISOString() : '', device_info: navigator.userAgent.slice(0, 300),
      }, (p) => set(it.id, { progress: p }))
      set(it.id, { status: 'done', progress: 1, result: r })
      return true
    } catch (e) {
      set(it.id, { status: 'error', error: e.message })
      return false
    }
  }
  const sendAll = async () => {
    const ready = queue.filter((x) => x.status === 'ready' || (x.status === 'error' && x.error && !x.error.startsWith('File type') && !x.error.startsWith('Larger')))
    let ok = 0
    for (const it of ready) if (await send(it)) ok += 1          // one at a time: phones on weak networks
    if (ok) { toast(`${ok} file(s) added to the incident`, 'ok'); onUploaded?.() }
    if (ok < ready.length) toast(`${ready.length - ok} file(s) failed — use Retry`, 'danger')
  }
  const locate = () => navigator.geolocation?.getCurrentPosition(
    (p) => setMeta((m) => ({ ...m, lat: p.coords.latitude.toFixed(6), lng: p.coords.longitude.toFixed(6) })),
    () => toast('Location not available', 'warn'), { enableHighAccuracy: true, timeout: 8000 })

  const pending = queue.filter((x) => x.status === 'ready').length
  return (
    <div className="upl">
      {!fixedIncident && (
        <label className="field">Linked incident (required)
          <select className="input" value={incidentId} onChange={(e) => setIncidentId(e.target.value)}>
            <option value="">Choose an incident…</option>
            {incidents.map((i) => <option key={i.id} value={i.id}>{i.ticket_id} — {i.title}</option>)}
          </select>
        </label>
      )}
      <div className={`upl-drop ${drag ? 'over' : ''}`} onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files) }}>
        <Icons.evidence />
        <p><b>Drop photos, videos, audio or PDFs here</b><br /><span className="muted">up to {MAX_MB} MB each</span></p>
        <div className="ds-toolbar" style={{ justifyContent: 'center' }}>
          <button type="button" className="btn btn-sm" onClick={() => pick.current.click()}><Icons.plus /> Choose files</button>
          <button type="button" className="btn btn-sm" onClick={() => cam.current.click()}><Icons.camera /> Take photo / video</button>
        </div>
        <input ref={pick} type="file" multiple accept={ACCEPT} hidden onChange={(e) => { add(e.target.files); e.target.value = '' }} aria-label="Choose evidence files" />
        <input ref={cam} type="file" accept="image/*,video/*" capture="environment" hidden onChange={(e) => { add(e.target.files); e.target.value = '' }} aria-label="Capture with camera" />
      </div>
      <div className="settings-grid">
        <label className="field">Description<input className="input" value={meta.description} maxLength={1000} onChange={(e) => setMeta({ ...meta, description: e.target.value })} placeholder="What it shows, who took it" /></label>
        <label className="field">Captured at<input className="input" type="datetime-local" value={meta.captured_at} onChange={(e) => setMeta({ ...meta, captured_at: e.target.value })} /></label>
        <label className="field">Location<input className="input" value={meta.location} maxLength={200} onChange={(e) => setMeta({ ...meta, location: e.target.value })} placeholder="Road / building" /></label>
        <div className="field">GPS
          <div className="ds-toolbar"><span className="mono muted">{meta.lat ? `${meta.lat}, ${meta.lng}` : 'not set'}</span><button type="button" className="btn btn-sm" onClick={locate}><Icons.map /> Use my location</button></div>
        </div>
      </div>
      {queue.length > 0 && (
        <ul className="upl-list" aria-label="Files to upload">
          {queue.map((it) => (
            <li key={it.id} className={`upl-item st-${it.status}`}>
              <span className="upl-name"><b>{it.file.name}</b><span className="muted"> · {kindOf(it.file)} · {human(it.file.size)}</span></span>
              <span className="upl-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(it.progress * 100)} aria-label={`Upload of ${it.file.name}`}>
                <span style={{ width: `${Math.round(it.progress * 100)}%` }} />
              </span>
              <span className="upl-state">
                {it.status === 'ready' && <Badge tone="muted" size="sm">Ready</Badge>}
                {it.status === 'uploading' && <Badge tone="info" size="sm">{Math.round(it.progress * 100)}%</Badge>}
                {it.status === 'done' && <><Badge tone="ok" size="sm" icon={Icons.check}>{it.result.ref}</Badge>{['image', 'video'].includes(it.result.kind) && <Badge tone="info" size="sm">Processing faces…</Badge>}</>}
                {it.status === 'error' && <><Badge tone="danger" size="sm" icon={Icons.alert}>{it.error}</Badge>
                  {!it.error?.startsWith('File type') && !it.error?.startsWith('Larger') && !it.error?.startsWith('Identical') && <button type="button" className="btn btn-sm" onClick={() => send(it)}>Retry</button>}</>}
                {it.status !== 'uploading' && it.status !== 'done' && <button type="button" className="icon-btn" aria-label={`Remove ${it.file.name}`} onClick={() => setQueue((q) => q.filter((x) => x.id !== it.id))}><Icons.close /></button>}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="ds-toolbar" style={{ justifyContent: 'flex-end' }}>
        {queue.some((x) => x.status === 'done') && <button type="button" className="btn" onClick={() => setQueue((q) => q.filter((x) => x.status !== 'done'))}>Clear finished</button>}
        <button type="button" className="btn btn-primary" disabled={!incidentId || !pending} onClick={sendAll}><Icons.download /> Upload {pending || ''}</button>
      </div>
      <p className="ds-setting-hint">Each file is fingerprinted (SHA-256) and logged: who uploaded it, when, from which device. Originals cannot be changed or deleted by officers.</p>
    </div>
  )
}
