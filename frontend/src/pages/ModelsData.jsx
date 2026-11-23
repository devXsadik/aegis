/* Models & data (ML engineers, admins): datasets with labelling, split, balance, freeze, export;
   the model registry with promote / rollback; the review queue of operator corrections. */
import { useEffect, useState } from 'react'
import { Card, Icons, Modal, Seg, timeAgo } from '../components/ui'
import { Badge, EmptyState, ErrorState, SkeletonList } from '../components/ds'
import {
  addDatasetItems, createDataset, datasetExportUrl, datasetFromReview, dismissReview, fetchDataset, fetchDatasets,
  fetchModels, fetchReviewQueue, fetchVehicleCatalog, freezeDataset, labelItem, promoteModel, rollbackModel,
  splitDataset, versionDataset,
} from '../services/api'
import { useToast } from '../components/Toast'

const TASKS = { vehicle_attr: 'Colour / type / model', vehicle_detect: 'Vehicle detector', vehicle_reid: 'Vehicle re-ID', face: 'Face' }
const FORMATS = { vehicle_attr: ['attributes'], vehicle_detect: ['yolo', 'coco'], vehicle_reid: ['reid'], face: ['reid'] }
const STAGE = { production: 'ok', staging: 'info', archived: 'muted' }

function useLoad(fn, key) {
  const [d, setD] = useState(null)
  const [e, setE] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let off = false
    fn().then((x) => { if (!off) { setD(x); setE('') } }).catch((er) => { if (!off) setE(er.message) })
    return () => { off = true }
  }, [key, tick]) // eslint-disable-line react-hooks/exhaustive-deps
  return [d, e, () => setTick((n) => n + 1)]
}

function DatasetDetail({ id, cat, onClose, onChanged }) {
  const { push: toast } = useToast()
  const [filter, setFilter] = useState('')
  const [d, err, reload] = useLoad(() => fetchDataset(id, filter === 'unlabelled' ? { unlabelled: true } : filter ? { split: filter } : {}), `${id}|${filter}`)
  const [crop, setCrop] = useState(false)
  const act = async (fn, msg) => { try { await fn(); toast(msg, 'ok'); reload(); onChanged() } catch (e) { toast(e.message, 'danger') } }
  const frozen = d?.status === 'frozen'
  const setLabel = (it, k, v) => act(() => labelItem(it.id, { ...it.labels, [k]: v || undefined }), 'Label saved')
  return (
    <Modal className="lb" title={d ? `${d.name} v${d.version} · ${TASKS[d.task]}` : 'Dataset'} onClose={onClose}>
      {err && <ErrorState compact message={err} />}
      {!d && !err && <SkeletonList rows={3} />}
      {d && (
        <div className="ml-detail">
          <div className="ds-toolbar">
            <Badge tone={frozen ? 'ok' : 'warn'}>{frozen ? 'Frozen' : 'Draft'}</Badge>
            <span className="meta">{d.items} items · {d.labelled} labelled · {d.balance.unlabelled} unlabelled</span>
            {!frozen && <>
              <label className="btn btn-sm">Add images<input type="file" multiple accept="image/*" hidden onChange={(e) => act(() => addDatasetItems(id, e.target.files, { cropVehicles: crop }), 'Images added')} /></label>
              <label className="off-area-opt"><input type="checkbox" checked={crop} onChange={(e) => setCrop(e.target.checked)} /> Crop vehicles from scenes</label>
              <button type="button" className="btn btn-sm" onClick={() => act(() => splitDataset(id, { train: 0.8, val: 0.1, test: 0.1, seed: 13 }), 'Split 80 / 10 / 10')}>Split</button>
              <button type="button" className="btn btn-sm btn-primary" onClick={() => act(() => freezeDataset(id), 'Frozen')}>Freeze</button>
            </>}
            {frozen && <button type="button" className="btn btn-sm" onClick={() => act(() => versionDataset(id), 'New draft version created')}>New version</button>}
            {FORMATS[d.task].map((f) => <a key={f} className="btn btn-sm" href={datasetExportUrl(id, f)} download><Icons.download /> {f}</a>)}
          </div>
          <details open><summary className="inc-section-title">Balance</summary>
            <div className="ml-balance">
              <div><b>Splits</b> {Object.entries(d.balance.splits).map(([k, v]) => `${k} ${v}`).join(' · ')}</div>
              <div><b>Day / night</b> {Object.entries(d.balance.day_night).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'}</div>
              {Object.entries(d.balance.fields).map(([f, classes]) => (
                <div key={f}><b>{f}</b> {Object.entries(classes).map(([c, s]) => {
                  const n = Object.values(s).reduce((a, b) => a + b, 0)
                  return <span key={c} className={`ml-class ${n < 20 ? 'low' : ''}`} title={JSON.stringify(s)}>{c} {n}</span>
                })}</div>
              ))}
            </div>
          </details>
          <Seg value={filter} onChange={setFilter} options={[{ value: '', label: 'All' }, { value: 'unlabelled', label: 'Unlabelled' }, { value: 'train', label: 'Train' }, { value: 'val', label: 'Val' }, { value: 'test', label: 'Test' }]} />
          <ul className="ml-items">
            {d.items_list.map((it) => (
              <li key={it.id}>
                <img src={it.image_url} alt="" loading="lazy" />
                <span className="meta">{it.split || 'unsplit'} · {it.day_night}</span>
                {d.task === 'vehicle_attr' && ['vehicle_type', 'color', 'make_model'].map((k) => (
                  <select key={k} className="input" disabled={frozen} value={it.labels[k] || ''} aria-label={k} onChange={(e) => setLabel(it, k, e.target.value)}>
                    <option value="">{k.replace('_', ' ')}…</option>
                    {(cat[{ vehicle_type: 'type', color: 'color', make_model: 'model' }[k]] || []).map((c) => <option key={c.code} value={c.code}>{c.name_en}</option>)}
                  </select>
                ))}
                {d.task !== 'vehicle_attr' && <input className="input" disabled={frozen} defaultValue={it.labels.identity || ''} placeholder={d.task === 'vehicle_detect' ? 'boxes via CVAT import' : 'identity'}
                  onBlur={(e) => e.target.value !== (it.labels.identity || '') && setLabel(it, 'identity', e.target.value)} aria-label="Identity" />}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Modal>
  )
}

function Datasets({ cat }) {
  const { push: toast } = useToast()
  const [list, err, reload] = useLoad(fetchDatasets, 'ds')
  const [open, setOpen] = useState(null)
  const [f, setF] = useState({ name: '', task: 'vehicle_attr' })
  const create = async () => {
    try { const d = await createDataset(f); toast(`Dataset ${d.name} created`, 'ok'); setF({ ...f, name: '' }); reload(); setOpen(d.id) } catch (e) { toast(e.message, 'danger') }
  }
  return (
    <Card title="Datasets" sub="Versioned; frozen versions are read-only and reproducible" flush
      actions={<div className="ds-toolbar">
        <input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="name, e.g. dhaka-attrs" aria-label="Dataset name" />
        <select className="input" value={f.task} onChange={(e) => setF({ ...f, task: e.target.value })} aria-label="Task">{Object.entries(TASKS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <button type="button" className="btn btn-sm btn-primary" disabled={f.name.trim().length < 2} onClick={create}><Icons.plus /> Create</button>
      </div>}>
      {err && <ErrorState compact message={err} onRetry={reload} />}
      {!list && !err && <SkeletonList rows={3} />}
      {list?.length === 0 && <EmptyState compact icon={Icons.chart} title="No datasets yet" />}
      {list?.length > 0 && (
        <ul className="wl-list">{list.map((d) => (
          <li key={d.id} className="wl-item">
            <div className="wl-main">
              <div className="wl-title"><b>{d.name}</b><span className="mono">v{d.version}</span><Badge tone="muted" size="sm">{TASKS[d.task]}</Badge><Badge tone={d.status === 'frozen' ? 'ok' : 'warn'} size="sm">{d.status}</Badge></div>
              <div className="meta">{d.items} items · {d.labelled} labelled · created {timeAgo(d.created_at)}</div>
            </div>
            <div className="wl-actions"><button type="button" className="btn btn-sm" onClick={() => setOpen(d.id)}>Open</button></div>
          </li>
        ))}</ul>
      )}
      {open && <DatasetDetail id={open} cat={cat} onClose={() => setOpen(null)} onChanged={reload} />}
    </Card>
  )
}

function Registry() {
  const { push: toast } = useToast()
  const [list, err, reload] = useLoad(fetchModels, 'm')
  const act = async (fn, msg) => { try { await fn(); toast(msg, 'ok'); reload() } catch (e) { toast(e.message, 'danger') } }
  const tasks = [...new Set((list || []).map((m) => m.task))]
  return (
    <Card title="Model registry" sub="Register from training/register.py; promotion swaps the live model, rollback restores the previous one" flush>
      {err && <ErrorState compact message={err} onRetry={reload} />}
      {!list && !err && <SkeletonList rows={3} />}
      {list?.length === 0 && <EmptyState compact icon={Icons.ai} title="No models registered">Train with training/, then register the run.</EmptyState>}
      {tasks.map((t) => (
        <section key={t} className="ml-task">
          <div className="inc-sec-head" style={{ padding: '10px 16px 0' }}>
            <h3 className="inc-section-title">{TASKS[t] || t}</h3>
            <button type="button" className="btn btn-sm" onClick={() => act(() => rollbackModel(t), 'Rolled back')}>Roll back</button>
          </div>
          <ul className="wl-list">{list.filter((m) => m.task === t).map((m) => (
            <li key={m.id} className="wl-item">
              <div className="wl-main">
                <div className="wl-title"><b>{m.name}</b><span className="mono">{m.version}</span><Badge tone={STAGE[m.stage]} size="sm">{m.stage}</Badge>{m.dataset_id && <Badge tone="muted" size="sm">dataset #{m.dataset_id}</Badge>}</div>
                <div className="meta mono">{Object.entries(m.metrics).map(([k, v]) => `${k} ${typeof v === 'number' ? v.toFixed(3) : v}`).join(' · ') || 'no metrics'}</div>
                <div className="meta">{m.format} · registered {timeAgo(m.created_at)}{m.promoted_at ? ` · promoted ${timeAgo(m.promoted_at)}` : ''}</div>
              </div>
              <div className="wl-actions">{m.stage !== 'production' && <button type="button" className="btn btn-sm btn-primary" onClick={() => act(() => promoteModel(m.id), `${m.version} is now in production`)}>Promote</button>}</div>
            </li>
          ))}</ul>
        </section>
      ))}
    </Card>
  )
}

function ReviewQueue() {
  const { push: toast } = useToast()
  const [list, err, reload] = useLoad(() => fetchReviewQueue('open'), 'rq')
  const [ds] = useLoad(fetchDatasets, 'rqds')
  const [pick, setPick] = useState([])
  const [target, setTarget] = useState('')
  const drafts = (ds || []).filter((d) => d.status === 'draft')
  const add = async () => {
    try { const r = await datasetFromReview(Number(target), pick); toast(`${r.added} item(s) added to the dataset`, 'ok'); setPick([]); reload() } catch (e) { toast(e.message, 'danger') }
  }
  return (
    <Card title="Review queue" sub="Operator corrections and rejected matches — material for the next training round" flush
      actions={<div className="ds-toolbar">
        <select className="input" value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Target dataset"><option value="">Add selected to…</option>{drafts.map((d) => <option key={d.id} value={d.id}>{d.name} v{d.version}</option>)}</select>
        <button type="button" className="btn btn-sm btn-primary" disabled={!pick.length || !target} onClick={add}>Add {pick.length || ''}</button>
      </div>}>
      {err && <ErrorState compact message={err} onRetry={reload} />}
      {!list && !err && <SkeletonList rows={3} />}
      {list?.length === 0 && <EmptyState compact icon={Icons.check} title="Nothing waiting" />}
      {list?.length > 0 && (
        <ul className="ml-items">{list.map((r) => (
          <li key={r.id} className={pick.includes(r.id) ? 'on' : ''}>
            <label className="off-area-opt"><input type="checkbox" checked={pick.includes(r.id)} onChange={() => setPick((p) => (p.includes(r.id) ? p.filter((x) => x !== r.id) : [...p, r.id]))} /> #{r.id}</label>
            {r.image_url ? <img src={r.image_url} alt="" loading="lazy" /> : <span className="ev-icon"><Icons.vehicle /></span>}
            <Badge tone={r.reason === 'correction' ? 'info' : 'danger'} size="sm">{r.reason === 'correction' ? `${r.field}: ${r.predicted || '?'} → ${r.corrected}` : `Rejected: ${r.predicted || 'match'}`}</Badge>
            <span className="meta">{r.day_night} · {timeAgo(r.created_at)}{r.note ? ` · ${r.note}` : ''}</span>
            <button type="button" className="link-btn" onClick={async () => { await dismissReview(r.id); reload() }}>Dismiss</button>
          </li>
        ))}</ul>
      )}
    </Card>
  )
}

export function ModelsData() {
  const [tab, setTab] = useState('datasets')
  const [cat, setCat] = useState({})
  useEffect(() => {
    fetchVehicleCatalog().then((rows) => {
      const by = {}
      rows.forEach((r) => { (by[r.kind] = by[r.kind] || []).push(r) })
      setCat(by)
    }).catch(() => {})
  }, [])
  return (
    <div className="ev-page">
      <Seg value={tab} onChange={setTab} options={[{ value: 'datasets', label: 'Datasets' }, { value: 'registry', label: 'Model registry' }, { value: 'review', label: 'Review queue' }]} />
      {tab === 'datasets' && <Datasets cat={cat} />}
      {tab === 'registry' && <Registry />}
      {tab === 'review' && <ReviewQueue />}
    </div>
  )
}
