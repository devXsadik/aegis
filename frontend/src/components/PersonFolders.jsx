/* People in evidence: one folder per person (spec 13). Cards with best face, ID / name, criminal
   badge, image count, first / last seen; detail with every face, and Merge / Move / Split /
   Rename / confirm-or-reject possible criminal matches. Every change is logged. */
import { useEffect, useState } from 'react'
import { Card, Icons, Modal, timeAgo } from './ui'
import { Badge, EmptyState, ErrorState, SkeletonList } from './ds'
import { editPersonGroup, fetchPersonGroup, fetchPersonGroups, mergePersonGroups, moveFaces, verifyEvidenceFace } from '../services/api'
import { useToast } from './Toast'

const STATUS = { unknown: ['muted', 'Unknown'], named: ['info', 'Named'], known: ['ok', 'Known person'],
  criminal_possible: ['warn', 'Possible criminal match'], criminal: ['danger', 'Criminal (confirmed)'] }

function FolderDetail({ id, folders, onClose, onChanged }) {
  const { push: toast } = useToast()
  const [g, setG] = useState(null)
  const [sel, setSel] = useState([])
  const [name, setName] = useState('')
  const [target, setTarget] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => { fetchPersonGroup(id).then((d) => { setG(d); setName(d.name || '') }).catch((e) => toast(e.message, 'danger')) }, [id, tick, toast])
  const run = async (fn, msg) => {
    try { await fn(); toast(msg, 'ok'); setSel([]); setTick((n) => n + 1); onChanged() } catch (e) { toast(e.message || 'Failed', 'danger') }
  }
  const toggle = (fid) => setSel((s) => (s.includes(fid) ? s.filter((x) => x !== fid) : [...s, fid]))
  const others = folders.filter((x) => x.id !== id)
  return (
    <Modal className="lb" title={g ? `${g.code}${g.name ? ` — ${g.name}` : ''}` : 'Folder'} onClose={onClose}>
      {!g && <SkeletonList rows={2} />}
      {g && (
        <>
          <div className="wl-title" style={{ marginBottom: 10 }}>
            <Badge tone={(STATUS[g.status] || STATUS.unknown)[0]}>{(STATUS[g.status] || STATUS.unknown)[1]}</Badge>
            {g.criminal && <Badge tone="danger" icon={Icons.watchlist}>{g.criminal.name}</Badge>}
            <span className="meta">{g.items.length} image(s) · first {timeAgo(g.first_seen)} · last {timeAgo(g.last_seen)} · incidents {g.incidents.map((i) => `#${i}`).join(', ')}</span>
          </div>
          <div className="ds-toolbar" style={{ marginBottom: 12 }}>
            <input className="input" style={{ maxWidth: 260 }} value={name} onChange={(e) => setName(e.target.value)} placeholder="Name this person" aria-label="Folder name" />
            <button type="button" className="btn btn-sm" disabled={name === (g.name || '')} onClick={() => run(() => editPersonGroup(id, { name }), 'Folder renamed')}>Rename</button>
            <button type="button" className="btn btn-sm" onClick={() => run(() => editPersonGroup(id, { status: 'known' }), 'Marked as known person')}>Mark known</button>
          </div>
          <ul className="pf-faces">
            {g.items.map((f) => (
              <li key={f.id}>
                <label className={`pf-face ${sel.includes(f.id) ? 'on' : ''}`}>
                  <input type="checkbox" checked={sel.includes(f.id)} onChange={() => toggle(f.id)} aria-label={`Select face from ${f.item_ref}`} />
                  <img src={f.crop_url} alt={`Face from ${f.item_ref}`} loading="lazy" />
                  <span className="meta">{f.item_ref}{f.frame_ts != null ? ` @${Math.round(f.frame_ts)}s` : ''}<br />{f.location || f.camera_id || ''} {timeAgo(f.at)}</span>
                </label>
                {f.verify_status === 'pending' && (
                  <span className="pf-verify">
                    <Badge tone="warn" size="sm">Possible match {Math.round((f.watch_similarity || 0) * 100)}%</Badge>
                    <button type="button" className="btn btn-sm" onClick={() => run(() => verifyEvidenceFace(f.id, 'confirm'), 'Match confirmed')}>Confirm</button>
                    <button type="button" className="btn btn-sm" onClick={() => run(() => verifyEvidenceFace(f.id, 'reject'), 'Match rejected: moved to its own folder')}>Reject</button>
                  </span>
                )}
                {f.verify_status && f.verify_status !== 'pending' && <Badge tone={f.verify_status === 'confirmed' ? 'danger' : 'muted'} size="sm">{f.verify_status}</Badge>}
              </li>
            ))}
          </ul>
          <div className="pf-actions">
            <span className="muted">{sel.length} selected</span>
            <select className="input" value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Move to folder">
              <option value="">Move selected to…</option>{others.map((o) => <option key={o.id} value={o.id}>{o.code}{o.name ? ` — ${o.name}` : ''}</option>)}
            </select>
            <button type="button" className="btn btn-sm" disabled={!sel.length || !target} onClick={() => run(() => moveFaces(sel, Number(target)), 'Faces moved')}>Move</button>
            <button type="button" className="btn btn-sm" disabled={!sel.length} onClick={() => run(() => moveFaces(sel, null), 'Split into a new folder')}>Split off</button>
          </div>
        </>
      )}
    </Modal>
  )
}

export function PersonFolders() {
  const { push: toast } = useToast()
  const [list, setList] = useState(null)
  const [error, setError] = useState('')
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(null)
  const [pick, setPick] = useState([])
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let off = false
    fetchPersonGroups({ q }).then((d) => { if (!off) { setList(d); setError('') } }).catch((e) => { if (!off) setError(e.message) })
    return () => { off = true }
  }, [q, tick])
  const merge = async () => {
    const [target, ...sources] = pick
    try {
      await mergePersonGroups(target, sources)
      toast(`${sources.length + 1} folders merged`, 'ok')
      setPick([]); setTick((n) => n + 1)
    } catch (e) {
      toast(e.message || 'Could not merge', 'danger')
    }
  }
  return (
    <Card title="People in evidence" sub="One folder per person across all case evidence. Unknown people are only grouped, never identified." flush
      actions={<div className="ds-toolbar">
        <label className="ds-search" style={{ minWidth: 200 }}><Icons.search /><input className="input" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="UNKNOWN-000123 or name" aria-label="Find folder" /></label>
        <button type="button" className="btn btn-sm" disabled={pick.length < 2} onClick={merge}>Merge {pick.length >= 2 ? pick.length : ''}</button>
      </div>}>
      {error && <ErrorState compact message={error} onRetry={() => setTick((n) => n + 1)} />}
      {!error && !list && <SkeletonList rows={3} />}
      {list && list.length === 0 && <EmptyState compact icon={Icons.users} title="No faces found in evidence yet">Faces in uploaded photos and videos are grouped here automatically.</EmptyState>}
      {list && list.length > 0 && (
        <ul className="pf-grid">
          {list.map((g) => {
            const st = STATUS[g.status] || STATUS.unknown
            return (
              <li key={g.id} className={`pf-card ${pick.includes(g.id) ? 'on' : ''}`}>
                <input type="checkbox" className="pf-pick" checked={pick.includes(g.id)} aria-label={`Select ${g.code} for merging`}
                  onChange={() => setPick((p) => (p.includes(g.id) ? p.filter((x) => x !== g.id) : [...p, g.id]))} />
                <button type="button" className="pf-open" onClick={() => setOpen(g.id)} aria-label={`Open ${g.code}`}>
                  {g.best_face_url ? <img src={g.best_face_url} alt="" loading="lazy" /> : <span className="ev-icon"><Icons.users /></span>}
                  <span className="pf-body">
                    <b>{g.name || g.code}</b>{g.name && <span className="mono muted">{g.code}</span>}
                    <span className="ev-tags"><Badge tone={st[0]} size="sm">{st[1]}</Badge><Badge tone="muted" size="sm">{g.faces} image(s)</Badge></span>
                    <span className="meta">First {timeAgo(g.first_seen)} · last {timeAgo(g.last_seen)}</span>
                    {g.seen_at.length > 0 && <span className="meta">Seen at {g.seen_at.slice(0, 3).join(', ')}</span>}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {open && <FolderDetail id={open} folders={list || []} onClose={() => setOpen(null)} onChanged={() => setTick((n) => n + 1)} />}
    </Card>
  )
}
