/* Data-retention policy editor and the identification accuracy dashboard. */
import { useEffect, useState } from 'react'
import { Card, Icons, Seg } from './ui'
import { Badge, EmptyState, ErrorState, SettingRow, SkeletonList } from './ds'
import { fetchAccuracy, fetchRetention, saveRetention } from '../services/api'
import { useToast } from './Toast'
import { eventLabel } from '../lib/events'

const FIELDS = [
  ['detection_days', 'Detections, plate reads, vehicle attributes (days)', 'Not matched to a watchlist; then deleted automatically'],
  ['capture_days', 'Capture stills (days)', 'Zoomed stills of critical subjects'],
  ['recording_hours', 'Continuous recordings (hours)', 'Rolling DVR buffer'],
  ['evidence_image_days', 'Detection images (days)', 'Not on an open case; record and custody chain stay'],
]

export function RetentionEditor({ isAdmin }) {
  const { push: toast } = useToast()
  const [p, setP] = useState(null)
  const [saved, setSaved] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { fetchRetention().then((r) => { setP(r); setSaved(r) }).catch((e) => setError(e.message)) }, [])
  if (error) return <Card title="Retention policy"><ErrorState compact message={error} /></Card>
  if (!p) return <Card title="Retention policy"><SkeletonList rows={3} /></Card>
  const dirty = FIELDS.some(([k]) => Number(p[k]) !== Number(saved[k]))
  const save = async () => {
    try {
      const r = await saveRetention(Object.fromEntries(FIELDS.map(([k]) => [k, Number(p[k])])))
      setP(r); setSaved(r)
      toast('Retention policy saved — applied at the next nightly clean-up', 'ok')
    } catch (e) {
      toast(e.message || 'Could not save', 'danger')
    }
  }
  return (
    <Card title="Retention policy" sub="Audit-logged; case evidence is never deleted automatically"
      actions={isAdmin && dirty && <button type="button" className="btn btn-sm btn-primary" onClick={save}>Save</button>}>
      {FIELDS.map(([k, label, hint]) => (
        <SettingRow key={k} label={label} hint={hint} htmlFor={`ret-${k}`}>
          <input id={`ret-${k}`} className="input" type="number" min={1} style={{ width: 110 }} value={p[k]} disabled={!isAdmin}
            onChange={(e) => setP({ ...p, [k]: e.target.value })} />
        </SettingRow>
      ))}
      <SettingRow label="Incident evidence" hint={p.case_evidence}><Badge tone="ok" icon={Icons.shield}>Kept</Badge></SettingRow>
    </Card>
  )
}

function Table({ title, rows, label }) {
  if (!rows.length) return null
  return (
    <Card title={title} flush>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th scope="col">{title.replace('By ', '')}</th><th scope="col">Matches</th><th scope="col">Confirmed</th><th scope="col">Rejected</th><th scope="col">Pending</th><th scope="col">False-positive rate</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td>{label ? label(r.key) : r.key}</td><td>{r.matches}</td><td>{r.confirmed}</td><td>{r.rejected}</td><td>{r.pending}</td>
                <td>{r.false_positive_rate == null ? '—' : (
                  <span className="fp-cell"><span className="fp-bar"><span style={{ width: `${Math.round(r.false_positive_rate * 100)}%` }} /></span>{Math.round(r.false_positive_rate * 100)}%</span>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

export function AccuracyDashboard() {
  const [days, setDays] = useState(30)
  const [d, setD] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let off = false
    fetchAccuracy(days).then((r) => { if (!off) { setD(r); setError('') } }).catch((e) => { if (!off) setError(e.message) })
    return () => { off = true }
  }, [days])
  return (
    <div className="ev-page">
      <div className="ds-toolbar">
        <Seg value={days} onChange={setDays} options={[{ value: 7, label: '7 days' }, { value: 30, label: '30 days' }, { value: 90, label: '90 days' }]} />
      </div>
      {error && <ErrorState message={error} />}
      {!d && !error && <SkeletonList rows={4} />}
      {d && d.total.matches === 0 && <EmptyState icon={Icons.chart} title="No identification alerts in this period">Face and vehicle matches appear here once operators confirm or reject them.</EmptyState>}
      {d && d.total.matches > 0 && (
        <>
          <div className="grid grid-4">
            {[['Matches', d.total.matches], ['Confirmed', d.total.confirmed], ['Rejected', d.total.rejected],
              ['False-positive rate', d.total.false_positive_rate == null ? '—' : `${Math.round(d.total.false_positive_rate * 100)}%`]].map(([l, v]) => (
              <div key={l} className="stat"><span className="label">{l}</span><span className="value">{v}</span></div>
            ))}
          </div>
          <Table title="By alert type" rows={d.by_type} label={eventLabel} />
          <Table title="By camera" rows={d.by_camera} />
          <Table title="By model" rows={d.by_model} />
          <Table title="By score" rows={d.by_score} />
        </>
      )}
    </div>
  )
}
