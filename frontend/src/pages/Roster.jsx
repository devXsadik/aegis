/* Duty roster: who is on shift, where, and when. Supervisors and admins plan shifts; officers on
   shift now come first in the officer picker. Officers see their own shifts. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, Icons, Seg } from '../components/ui'
import { Badge, EmptyState, ErrorState, SkeletonList } from '../components/ds'
import { useToast } from '../components/Toast'
import { addShift, fetchJurisdictions, fetchRoster, fetchRosterOfficers, removeShift } from '../services/api'
import { parseTs } from '../lib/time'

const COMMAND = ['admin', 'supervisor']
const pad = (n) => String(n).padStart(2, '0')
const dayKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const hm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`
const PRESETS = [
  { label: 'Morning 06–14', start: '06:00', hours: 8 },
  { label: 'Evening 14–22', start: '14:00', hours: 8 },
  { label: 'Night 22–06', start: '22:00', hours: 8 },
]

function AddShift({ onAdded }) {
  const { push: toast } = useToast()
  const [officers, setOfficers] = useState([])
  const [areas, setAreas] = useState([])
  const [f, setF] = useState({ user_id: '', date: dayKey(new Date()), start: '06:00', hours: 8, jurisdiction_id: '', assignment: '' })
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    fetchRosterOfficers().then(setOfficers).catch(() => {})
    fetchJurisdictions(false).then((d) => setAreas(Array.isArray(d) ? d : [])).catch(() => {})
  }, [])
  const set = (patch) => setF((x) => ({ ...x, ...patch }))
  const submit = async (e) => {
    e.preventDefault()
    const start = new Date(`${f.date}T${f.start}`)
    const end = new Date(start.getTime() + Number(f.hours) * 3600e3)
    setBusy(true)
    try {
      await addShift({ user_id: Number(f.user_id), starts_at: start.toISOString(), ends_at: end.toISOString(),
        jurisdiction_id: f.jurisdiction_id ? Number(f.jurisdiction_id) : null, assignment: f.assignment || null })
      toast('Shift added', 'ok')
      set({ assignment: '' })
      onAdded()
    } catch (err) {
      toast(err.message || 'Could not add the shift', 'danger')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card title="Add a shift" sub="The officer's area is used when you leave Area empty">
      <form className="roster-form" onSubmit={submit}>
        <label className="field">Officer
          <select className="input" required value={f.user_id} onChange={(e) => set({ user_id: e.target.value })}>
            <option value="">Choose an officer</option>
            {officers.map((o) => <option key={o.id} value={o.id}>{o.rank ? `${o.rank} ` : ''}{o.name}</option>)}
          </select>
        </label>
        <label className="field">Date
          <input className="input" type="date" required value={f.date} onChange={(e) => set({ date: e.target.value })} />
        </label>
        <div className="field roster-wide">
          <span>Shift</span>
          <div className="roster-presets">
            {PRESETS.map((p) => (
              <button key={p.start} type="button" className={`chip ${f.start === p.start && Number(f.hours) === p.hours ? 'on' : ''}`}
                aria-pressed={f.start === p.start && Number(f.hours) === p.hours} onClick={() => set({ start: p.start, hours: p.hours })}>{p.label}</button>
            ))}
          </div>
        </div>
        <label className="field">Starts
          <input className="input" type="time" required value={f.start} onChange={(e) => set({ start: e.target.value })} />
        </label>
        <label className="field">Hours
          <input className="input" type="number" min="1" max="24" required value={f.hours} onChange={(e) => set({ hours: e.target.value })} />
        </label>
        <label className="field">Area
          <select className="input" value={f.jurisdiction_id} onChange={(e) => set({ jurisdiction_id: e.target.value })}>
            <option value="">Officer's own area</option>
            {areas.map((a) => <option key={a.id} value={a.id}>{a.name_en}</option>)}
          </select>
        </label>
        <label className="field roster-wide">Assignment (optional)
          <input className="input" maxLength={80} value={f.assignment} placeholder="e.g. Patrol car 3, Gulshan-2 checkpoint"
            onChange={(e) => set({ assignment: e.target.value })} />
        </label>
        <div className="roster-wide"><button type="submit" className="btn btn-primary" disabled={busy || !f.user_id}>{busy ? 'Adding…' : 'Add shift'}</button></div>
      </form>
    </Card>
  )
}

export function Roster({ ctx }) {
  const role = ctx?.me?.role
  const canPlan = COMMAND.includes(role)
  const { push: toast } = useToast()
  const [days, setDays] = useState(7)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(() => fetchRoster({ days }).then((d) => { setData(d); setError('') })
    .catch((e) => setError(e.message || 'Could not load the roster')), [days])
  useEffect(() => { load() }, [load])

  const byDay = useMemo(() => {
    const out = new Map()
    for (const s of data?.shifts || []) {
      const k = dayKey(parseTs(s.starts_at))
      if (!out.has(k)) out.set(k, [])
      out.get(k).push(s)
    }
    return [...out.entries()]
  }, [data])
  const onNow = (data?.shifts || []).filter((s) => s.now)

  const remove = async (s) => {
    try { await removeShift(s.id); toast('Shift removed', 'ok'); load() } catch (e) { toast(e.message, 'danger') }
  }

  return (
    <div className="stack-page">
      <div className="rpt-filters">
        <Seg value={days} onChange={setDays} options={[{ value: 1, label: 'Today' }, { value: 7, label: '7 days' }, { value: 14, label: '14 days' }]} />
        {data && <span className="muted">{onNow.length} officer{onNow.length === 1 ? '' : 's'} on shift now</span>}
      </div>
      {canPlan && <AddShift onAdded={load} />}
      <Card title={role === 'police' ? 'Your shifts' : 'Duty roster'} sub="Times in your browser's time zone" flush>
        {!data && !error && <div style={{ padding: 16 }}><SkeletonList rows={3} label="Loading roster" /></div>}
        {error && <div style={{ padding: 16 }}><ErrorState compact message={error} onRetry={load} /></div>}
        {data && byDay.length === 0 && (
          <div style={{ padding: 16 }}>
            <EmptyState compact icon={Icons.clock} title="No shifts planned">
              {canPlan ? 'Add shifts above. Officers on shift are offered first when you assign an incident.' : 'Your supervisor has not planned shifts for this period.'}
            </EmptyState>
          </div>
        )}
        {byDay.map(([day, shifts]) => (
          <section key={day} className="roster-day" aria-label={day}>
            <h3>{parseTs(shifts[0].starts_at).toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'short' })}</h3>
            <ul>
              {shifts.map((s) => (
                <li key={s.id} className={s.now ? 'now' : ''}>
                  <span className="mono">{hm(parseTs(s.starts_at))}–{hm(parseTs(s.ends_at))}</span>
                  <b>{s.officer || `User ${s.user_id}`}</b>
                  <span className="muted">{[s.area, s.assignment].filter(Boolean).join(' · ') || '—'}</span>
                  <span className="roster-end">
                    {s.now && <Badge tone="ok" size="sm">On shift</Badge>}
                    {canPlan && <button type="button" className="icon-btn" aria-label={`Remove ${s.officer}'s shift`} onClick={() => remove(s)}><Icons.close /></button>}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </Card>
    </div>
  )
}
