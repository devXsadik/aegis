import { useCallback, useEffect, useState } from 'react'
import { Card, Empty, Icons, Tag, timeAgo, useConfirm } from '../components/ui'
import { useToast } from '../components/Toast'
import {
  acceptHandover, addShiftNote, fetchPendingHandover, fetchShiftLog, fetchShiftSummary, handOverShift,
} from '../services/api'
import { parseTs } from '../lib/time'

const clock = (ts) => parseTs(ts)?.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) || ''
const day = (ts) => parseTs(ts)?.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' }) || ''

/** The numbers that matter at a shift change, as rows. */
function SummaryRows({ s }) {
  if (!s) return null
  const rows = [
    ['Alerts raised', s.alerts_raised],
    ['Alerts handled', s.alerts_handled],
    ['Alerts still waiting', s.alerts_waiting, s.alerts_waiting ? 'warn' : 'ok'],
    ['Critical, not acknowledged', s.critical_waiting, s.critical_waiting ? 'danger' : 'ok'],
    ['Camera tamper alerts', s.tamper_alerts, s.tamper_alerts ? 'warn' : null],
    ['Incidents opened', s.incidents_opened],
    ['Incidents still open', s.incidents_open, s.incidents_open ? 'warn' : 'ok'],
    ['Notes written', s.notes],
  ]
  return (
    <>
      <dl className="kv shift-sum">
        {rows.map(([label, n, tone]) => (
          <span key={label} style={{ display: 'contents' }}>
            <dt>{label}</dt><dd className={tone ? `tone-${tone}` : ''}>{n}</dd>
          </span>
        ))}
      </dl>
      {s.cameras_not_reporting?.length > 0 && (
        <p className="shift-down"><b>Not sending video:</b> {s.cameras_not_reporting.join(', ')}</p>
      )}
    </>
  )
}

export function ShiftLog({ ctx }) {
  const { me, cameras = [] } = ctx
  const { push: toast } = useToast()
  const [ask, confirmDialog] = useConfirm()
  const [log, setLog] = useState([])
  const [summary, setSummary] = useState(null)
  const [pending, setPending] = useState(null)
  const [text, setText] = useState('')
  const [cameraId, setCameraId] = useState('')
  const [handoverNotes, setHandoverNotes] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    fetchShiftLog().then(setLog).catch(() => {})
    fetchShiftSummary().then(setSummary).catch(() => {})
    fetchPendingHandover().then(setPending).catch(() => {})
  }, [])
  useEffect(() => {
    load()
    const t = setInterval(load, 30000)      // a colleague's note shows up without a reload
    return () => clearInterval(t)
  }, [load])

  const act = async (fn, ok) => {
    setBusy(true)
    try {
      await fn()
      if (ok) toast(ok, 'ok')
      load()
      return true
    } catch (e) {
      toast(e.message || 'Request failed', 'danger')
      return false
    } finally {
      setBusy(false)
    }
  }

  const addNote = async (e) => {
    e.preventDefault()
    if (await act(() => addShiftNote(text.trim(), cameraId), null)) { setText(''); setCameraId('') }
  }
  const handOver = async () => {
    if (!(await ask({ title: 'Hand over the shift', message: 'This records the shift summary and your notes for the next operator. Continue?', confirmLabel: 'Hand over' }))) return
    if (await act(() => handOverShift(handoverNotes.trim()), 'Shift handed over')) setHandoverNotes('')
  }
  const camName = (id) => cameras.find((c) => c.camera_id === id)?.name || id
  const forMe = pending && pending.username !== me?.username

  return (
    <>
      {forMe && (
        <Card className="mb shift-incoming" title={`Handover from ${pending.username}`} sub={`${day(pending.timestamp)} · ${clock(pending.timestamp)}`}
          actions={<button type="button" className="btn btn-primary btn-sm" disabled={busy}
            onClick={() => act(() => acceptHandover(pending.id), 'Handover accepted: the shift is yours')}>Accept handover</button>}>
          {pending.text ? <p className="shift-notes">{pending.text}</p> : <p className="muted">No notes.</p>}
          <SummaryRows s={pending.summary} />
        </Card>
      )}

      <div className="grid grid-23">
        <Card title="Shift log" sub="Notes from this and earlier shifts, newest first">
          <form className="shift-compose" onSubmit={addNote}>
            <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} rows={2}
              placeholder="What happened? e.g. Delivery van at the loading bay, driver checked in" aria-label="Note" />
            <div className="shift-compose-row">
              <select className="input" value={cameraId} onChange={(e) => setCameraId(e.target.value)} aria-label="Camera (optional)">
                <option value="">No particular camera</option>
                {cameras.map((c) => <option key={c.camera_id} value={c.camera_id}>{c.name || c.camera_id}</option>)}
              </select>
              <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !text.trim()}>Add note</button>
            </div>
          </form>

          {log.length === 0 ? (
            <Empty icon={Icons.clock}>Nothing logged yet. Notes and handovers appear here.</Empty>
          ) : (
            <ol className="shift-log">
              {log.map((e) => (
                <li key={e.id} className={e.kind}>
                  <time title={parseTs(e.timestamp)?.toLocaleString()}>{clock(e.timestamp)}<small>{day(e.timestamp)}</small></time>
                  <div>
                    <div className="shift-who">
                      <b>{e.username}</b>
                      {e.kind === 'handover' && <Tag tone={e.accepted_at ? 'ok' : 'warn'}>{e.accepted_at ? 'Handover accepted' : 'Handover waiting'}</Tag>}
                      {e.accepted_by && <span className="meta">by {e.accepted_by} at {clock(e.accepted_at)}</span>}
                      {e.camera_id && <Tag tone="muted">{camName(e.camera_id)}</Tag>}
                    </div>
                    {e.text && <p>{e.text}</p>}
                    {e.kind === 'handover' && e.summary && (
                      <p className="meta">{e.summary.alerts_handled} alerts handled · {e.summary.alerts_waiting} waiting · {e.summary.incidents_open} incident{e.summary.incidents_open === 1 ? '' : 's'} open</p>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Card>

        <div className="shift-side">
          <Card title="This shift" sub={summary ? `Since ${clock(summary.since)}, ${timeAgo(summary.since)}` : ''}>
            <SummaryRows s={summary} />
          </Card>
          <Card title="Hand over" sub="For the operator who takes over from you">
            <textarea className="shift-handover" value={handoverNotes} onChange={(e) => setHandoverNotes(e.target.value)} maxLength={2000} rows={4}
              placeholder="Anything they must know: open situations, cameras to watch, people expected…" aria-label="Handover notes" />
            <button type="button" className="btn btn-primary" disabled={busy} onClick={handOver}>Hand over the shift</button>
          </Card>
        </div>
      </div>
      {confirmDialog}
    </>
  )
}
