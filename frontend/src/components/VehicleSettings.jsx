/* Settings → Vehicle classes & models: managed lists (types, colours, makes, models) and the
   vehicle matching weights / thresholds. Admin edits; others read. */
import { useEffect, useState } from 'react'
import { Card, Icons, Seg } from './ui'
import { Badge, EmptyState, ErrorState, SettingRow, SkeletonList } from './ds'
import { addCatalogEntry, editCatalogEntry, fetchMatchConfig, fetchVehicleCatalog, saveMatchConfig } from '../services/api'
import { useToast } from './Toast'

const KINDS = [{ value: 'type', label: 'Types' }, { value: 'color', label: 'Colours' }, { value: 'make', label: 'Makes' }, { value: 'model', label: 'Models' }]
const WEIGHTS = { plate: 'Plate', type: 'Type', color: 'Colour', model: 'Make / model', reid: 'Appearance (re-ID)' }

function Catalog({ isAdmin }) {
  const { push: toast } = useToast()
  const [kind, setKind] = useState('type')
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const [form, setForm] = useState({ code: '', name_en: '', name_bn: '', parent_code: '' })
  useEffect(() => {
    let off = false
    fetchVehicleCatalog().then((r) => { if (!off) { setRows(r); setError('') } }).catch((e) => { if (!off) setError(e.message) })
    return () => { off = true }
  }, [tick])
  const list = (rows || []).filter((r) => r.kind === kind)
  const makes = (rows || []).filter((r) => r.kind === 'make')
  const add = async () => {
    try {
      await addCatalogEntry({ kind, code: form.code.trim().toLowerCase(), name_en: form.name_en.trim(), name_bn: form.name_bn.trim() || null,
        parent_code: kind === 'model' ? form.parent_code || null : null })
      toast(`${form.name_en} added`, 'ok')
      setForm({ code: '', name_en: '', name_bn: '', parent_code: '' })
      setTick((n) => n + 1)
    } catch (e) {
      toast(e.message || 'Could not add', 'danger')
    }
  }
  const retire = async (r) => {
    try {
      await editCatalogEntry(r.id, { active: false })
      toast(`${r.name_en} retired (kept on old records)`, 'ok')
      setTick((n) => n + 1)
    } catch (e) {
      toast(e.message || 'Could not retire', 'danger')
    }
  }
  return (
    <Card title="Managed lists" sub="What operators can pick on watchlist entries and searches; training classes come from here" flush
      actions={<Seg value={kind} onChange={setKind} options={KINDS} />}>
      {error && <ErrorState compact message={error} onRetry={() => setTick((n) => n + 1)} />}
      {!error && !rows && <SkeletonList rows={4} />}
      {rows && list.length === 0 && <EmptyState compact icon={Icons.vehicle} title="Nothing in this list" />}
      {rows && list.length > 0 && (
        <ul className="cat-list">
          {list.map((r) => (
            <li key={r.id}>
              {kind === 'color' && <span className={`swatch sw-${r.code}`} aria-hidden="true" />}
              <span><b>{r.name_en}</b>{r.name_bn && <span className="muted"> · {r.name_bn}</span>}</span>
              <span className="mono muted">{r.code}</span>
              {isAdmin && r.code !== 'unknown' && r.code !== 'other' && <button type="button" className="link-btn" onClick={() => retire(r)}>Retire</button>}
            </li>
          ))}
        </ul>
      )}
      {isAdmin && (
        <div className="cat-add">
          <input className="input mono" placeholder="code (a-z, 0-9, _)" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} aria-label="Code" />
          <input className="input" placeholder="English name" value={form.name_en} onChange={(e) => setForm({ ...form, name_en: e.target.value })} aria-label="English name" />
          <input className="input" lang="bn" placeholder="বাংলা নাম" value={form.name_bn} onChange={(e) => setForm({ ...form, name_bn: e.target.value })} aria-label="Bangla name" />
          {kind === 'model' && (
            <select className="input" value={form.parent_code} onChange={(e) => setForm({ ...form, parent_code: e.target.value })} aria-label="Make">
              <option value="">Make…</option>{makes.map((m) => <option key={m.code} value={m.code}>{m.name_en}</option>)}
            </select>
          )}
          <button type="button" className="btn btn-sm btn-primary" disabled={!/^[a-z0-9_]+$/.test(form.code.trim()) || !form.name_en.trim()} onClick={add}><Icons.plus /> Add</button>
        </div>
      )}
    </Card>
  )
}

function Weights({ isAdmin }) {
  const { push: toast } = useToast()
  const [cfg, setCfg] = useState(null)
  const [saved, setSaved] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    fetchMatchConfig().then((r) => { setCfg(r.config); setSaved(r.config) }).catch((e) => setError(e.message))
  }, [])
  if (error) return <Card title="Matching"><ErrorState compact message={error} /></Card>
  if (!cfg) return <Card title="Matching"><SkeletonList rows={3} /></Card>
  const dirty = JSON.stringify(cfg) !== JSON.stringify(saved)
  const save = async () => {
    try {
      const r = await saveMatchConfig(cfg)
      setCfg(r.config); setSaved(r.config)
      toast('Matching settings saved', 'ok')
    } catch (e) {
      toast(e.message || 'Could not save', 'danger')
    }
  }
  const slider = (label, value, onChange, hint, max = 1, step = 0.01) => (
    <div className="ds-slider" key={label}>
      <div className="ds-slider-top"><label>{label}</label><span className="ds-slider-value">{Math.round(value * 100)}%</span></div>
      <input type="range" min={0} max={max} step={step} value={value} disabled={!isAdmin} onChange={(e) => onChange(Number(e.target.value))} aria-label={label} />
      {hint && <span className="ds-slider-hint">{hint}</span>}
    </div>
  )
  return (
    <Card title="Matching" sub="How a sighting is scored against a watchlist vehicle"
      actions={isAdmin && dirty && <button type="button" className="btn btn-sm btn-primary" onClick={save}>Save</button>}>
      {Object.entries(WEIGHTS).map(([k, label]) => slider(`Weight: ${label}`, cfg.weights[k], (v) => setCfg({ ...cfg, weights: { ...cfg.weights, [k]: v } })))}
      {slider('Colour weight at night / IR', cfg.night_color_weight, (v) => setCfg({ ...cfg, night_color_weight: v }), 'Colour is unreliable on grey IR frames')}
      {slider('Minimum attribute confidence', cfg.min_attr_confidence, (v) => setCfg({ ...cfg, min_attr_confidence: v }), 'Below this an attribute counts as unknown')}
      {slider('Re-ID similarity threshold', cfg.reid_threshold, (v) => setCfg({ ...cfg, reid_threshold: v }), 'Needed for a plate-less “Candidate vehicle”')}
      <SettingRow label="Candidate vehicles" hint="Plate unread, attributes + appearance match">
        <Badge tone="info" icon={Icons.eye}>Only inside an active lookout</Badge>
      </SettingRow>
    </Card>
  )
}

export function VehicleSettings({ isAdmin }) {
  return (
    <div className="settings-grid">
      <Catalog isAdmin={isAdmin} />
      <Weights isAdmin={isAdmin} />
    </div>
  )
}
