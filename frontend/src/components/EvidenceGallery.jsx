/* Case evidence gallery: filters, thumbnails, lightbox (image / video / audio / PDF), details with
   custody chain, faces found, integrity check, versions; admin soft-delete with a reason. */
import { useEffect, useState } from 'react'
import { Card, Icons, Modal, timeAgo } from './ui'
import { Badge, EmptyState, ErrorState, SkeletonList } from './ds'
import { deleteEvidenceItem, fetchEvidenceItem, fetchEvidenceItems, fetchIncidentsPage, verifyEvidenceItem } from '../services/api'
import { useToast } from './Toast'

const KINDS = [['', 'All types'], ['image', 'Photos'], ['video', 'Video'], ['audio', 'Audio'], ['pdf', 'PDF'], ['snapshot', 'Alert snapshots']]
const FACE = { pending: ['info', 'Processing faces…'], processing: ['info', 'Processing faces…'], done: ['ok', 'faces'], none: ['muted', 'No faces'], failed: ['danger', 'Face check failed'], skipped: ['muted', ''] }

function Preview({ item }) {
  const src = item.file_url + '?inline=true'
  if (item.kind === 'image' || item.kind === 'snapshot') return <img className="lb-media" src={src} alt={item.description || item.original_filename || item.ref} />
  if (item.kind === 'video') return <video className="lb-media" src={src} controls preload="metadata" />
  if (item.kind === 'audio') return <audio src={src} controls style={{ width: '100%' }} />
  if (item.kind === 'pdf') return <iframe className="lb-media" src={src} title={item.original_filename || item.ref} />
  return null
}

function Lightbox({ refId, isAdmin, onClose, onChanged }) {
  const { push: toast } = useToast()
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [check, setCheck] = useState(null)
  const [reason, setReason] = useState('')
  useEffect(() => { fetchEvidenceItem(refId).then(setD).catch((e) => setErr(e.message)) }, [refId])
  const verify = async () => {
    try { setCheck(await verifyEvidenceItem(refId)) } catch (e) { toast(e.message, 'danger') }
  }
  const del = async () => {
    try {
      await deleteEvidenceItem(refId, reason.trim())
      toast(`${refId} deleted (record kept)`, 'ok')
      onChanged?.()
      onClose()
    } catch (e) {
      toast(e.message || 'Could not delete', 'danger')
    }
  }
  return (
    <Modal className="lb" title={d ? `${d.ref} · ${d.original_filename || d.kind}` : 'Evidence'} onClose={onClose}>
      {err && <ErrorState compact message={err} />}
      {!d && !err && <SkeletonList rows={2} />}
      {d && (
        <div className="lb-grid">
          <div><Preview item={d} /></div>
          <div className="lb-side">
            <dl className="gov-dl lb-dl">
              <div><dt>Incident</dt><dd>#{d.incident_id}</dd></div>
              <div><dt>Captured</dt><dd>{d.captured_at ? new Date(d.captured_at).toLocaleString() : '—'}</dd></div>
              <div><dt>Uploaded</dt><dd>{d.uploaded_by} · {timeAgo(d.uploaded_at)}</dd></div>
              <div><dt>Location</dt><dd>{d.location || '—'}{d.lat != null ? ` (${d.lat}, ${d.lng})` : ''}</dd></div>
              <div><dt>Size</dt><dd>{(d.size / 1e6).toFixed(2)} MB · v{d.version}</dd></div>
              <div><dt>SHA-256</dt><dd className="mono lb-hash">{d.sha256}</dd></div>
              {d.device_info && <div><dt>Device</dt><dd className="lb-hash">{d.device_info}</dd></div>}
            </dl>
            {d.description && <p className="gov-basis">{d.description}</p>}
            {d.faces.length > 0 && (
              <div className="lb-faces">{d.faces.map((f) => <img key={f.id} src={f.crop_url} alt="Face found" title={f.verify_status ? `Possible watchlist match (${f.verify_status})` : `Folder #${f.group_id}`} className={f.verify_status === 'pending' ? 'pending' : ''} />)}</div>
            )}
            <div className="ds-toolbar">
              <a className="btn btn-sm" href={d.file_url} download><Icons.download /> Download</a>
              <button type="button" className="btn btn-sm" onClick={verify}><Icons.shield /> Check integrity</button>
            </div>
            {check && <Badge tone={check.ok ? 'ok' : 'danger'} icon={check.ok ? Icons.check : Icons.alert}>{check.ok ? `Intact · ${check.records} custody records` : 'Integrity check FAILED'}</Badge>}
            <details className="lb-custody"><summary>Chain of custody ({d.custody.length})</summary>
              <ol>{d.custody.map((c, i) => <li key={i}><b>{c.action}</b> {c.actor} · {new Date(c.at).toLocaleString()}{c.details ? ` · ${c.details}` : ''}</li>)}</ol>
            </details>
            {d.versions.length > 0 && <p className="meta">Other versions: {d.versions.map((v) => `${v.ref} (v${v.version})`).join(', ')}</p>}
            {isAdmin && !d.deleted && (
              <div className="lb-del">
                <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for deletion (logged)" aria-label="Reason for deletion" />
                <button type="button" className="btn btn-sm btn-danger" disabled={reason.trim().length < 5} onClick={del}>Delete</button>
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}

export function EvidenceGallery({ me, incidentId: fixedIncident, groupId, reloadKey = 0 }) {
  const [f, setF] = useState({ incident_id: fixedIncident || '', kind: '', date_from: '', date_to: '' })
  const [incidents, setIncidents] = useState([])
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(null)
  const [tick, setTick] = useState(0)
  useEffect(() => { if (!fixedIncident) fetchIncidentsPage({ limit: 100 }).then((d) => setIncidents(d.items)).catch(() => {}) }, [fixedIncident])
  useEffect(() => {
    let off = false
    fetchEvidenceItems({ ...f, group_id: groupId, date_from: f.date_from ? `${f.date_from}T00:00:00` : '', date_to: f.date_to ? `${f.date_to}T23:59:59` : '' })
      .then((d) => { if (!off) { setData(d); setError('') } }).catch((e) => { if (!off) setError(e.message) })
    return () => { off = true }
  }, [f, groupId, tick, reloadKey])
  // Faces are processed after upload: refresh while something is still processing.
  useEffect(() => {
    if (!data?.items.some((i) => ['pending', 'processing'].includes(i.faces_status))) return undefined
    const t = setTimeout(() => setTick((n) => n + 1), 3000)
    return () => clearTimeout(t)
  }, [data])
  return (
    <Card title="Case evidence" sub={data ? `${data.total} item(s)` : ''} flush>
      {!fixedIncident && (
        <div className="inc-filters">
          <select className="input" value={f.incident_id} onChange={(e) => setF({ ...f, incident_id: e.target.value })} aria-label="Incident">
            <option value="">All incidents</option>{incidents.map((i) => <option key={i.id} value={i.id}>{i.ticket_id} — {i.title}</option>)}
          </select>
          <select className="input" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })} aria-label="Type">
            {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <input className="input" type="date" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} aria-label="From" />
          <input className="input" type="date" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} aria-label="To" />
        </div>
      )}
      {error && <ErrorState compact message={error} onRetry={() => setTick((n) => n + 1)} />}
      {!error && !data && <SkeletonList rows={3} />}
      {data && data.items.length === 0 && <EmptyState compact icon={Icons.evidence} title="No evidence yet">Upload photos, video, audio or documents to an incident.</EmptyState>}
      {data && data.items.length > 0 && (
        <ul className="ev-grid" aria-label="Evidence">
          {data.items.map((i) => {
            const fs = FACE[i.faces_status] || FACE.skipped
            return (
              <li key={i.ref}>
                <button type="button" className="ev-tile" onClick={() => setOpen(i.ref)} aria-label={`Open ${i.ref}`}>
                  {i.thumb_url ? <img src={i.thumb_url} alt="" loading="lazy" /> : <span className="ev-icon">{i.kind === 'video' ? <Icons.live /> : i.kind === 'pdf' ? <Icons.report /> : <Icons.evidence />}</span>}
                  <span className="ev-meta">
                    <b className="mono">{i.ref}</b>
                    <span>{i.original_filename || i.kind} · {timeAgo(i.uploaded_at)}</span>
                    <span className="ev-tags">
                      <Badge tone={i.source === 'system' ? 'purple' : 'muted'} size="sm">{i.source === 'system' ? 'Alert snapshot' : i.kind}</Badge>
                      {fs[1] && <Badge tone={fs[0]} size="sm">{i.faces_status === 'done' ? `${i.faces_found} face(s)` : fs[1]}</Badge>}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {open && <Lightbox refId={open} isAdmin={me?.role === 'admin'} onClose={() => setOpen(null)} onChanged={() => setTick((n) => n + 1)} />}
    </Card>
  )
}
