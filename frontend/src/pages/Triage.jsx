import { useCallback, useEffect, useRef, useState } from 'react'
import { VehicleMatchCard } from '../components/MatchCard'
import { Card, Icons, Tag, Empty, Seg, timeAgo, SEVERITY_TONE } from '../components/ui'
import {
  fetchAlertsFiltered, fetchAlertContext, acknowledgeAlert, dispatchPolice,
  createIncidentFromAlert, evidenceImageUrl, openVmsPlayback,
} from '../services/api'
import { useToast } from '../components/Toast'
import { can } from '../lib/permissions'
import { useConfirm } from '../components/ui'
import { PersonJourney } from '../components/PersonJourney'
import {
  eventLabel, eventIconKey, fromAlertRow, groupRepeats, waitLabel, waitUrgency, EXPLAIN, REJECT_REASONS, REVIEW_LABEL,
} from '../lib/events'
import { parseTs } from '../lib/time'

const SEVERITY_ORDER = { critical: 0, high: 1, medium: 2, info: 3, low: 4 }

const QUEUES = {
  review: { params: { reviewStatus: 'pending', dismissed: false }, keep: () => true },
  open: { params: { acknowledged: false, dismissed: false }, keep: () => true },
  done: { params: {}, keep: (a) => a.acknowledged || a.dismissed },
}

// Waiting queues: most severe first, then whoever has waited longest. Resolved: newest first.
function sortItems(list, longestWaitingFirst = true) {
  const at = (i) => parseTs(longestWaitingFirst ? (i.since ?? i.time) : i.time)?.getTime() || 0
  return [...list].sort((a, b) => {
    const s = (SEVERITY_ORDER[a.severity] ?? 5) - (SEVERITY_ORDER[b.severity] ?? 5)
    if (s) return s
    return longestWaitingFirst ? at(a) - at(b) : at(b) - at(a)
  })
}

const PRE_ROLL_MS = 10_000      // the clip starts this long before the alert

/** Recorded video around the alert: the segment covering 10 s before it, cued to that moment. */
function AlertVideo({ item, playRef }) {
  const [state, setState] = useState({ status: 'idle' })     // idle | loading | ready | error
  const urlRef = useRef(null)
  useEffect(() => () => { if (urlRef.current) URL.revokeObjectURL(urlRef.current) }, [])
  const atMs = parseTs(item.since ?? item.time)?.getTime()

  const play = useCallback(async () => {
    if (!item.cameraId || !atMs) return
    setState({ status: 'loading' })
    try {
      const { blobUrl, seekOffset } = await openVmsPlayback(item.cameraId, new Date(atMs - PRE_ROLL_MS).toISOString())
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
      urlRef.current = blobUrl
      setState({ status: 'ready', url: blobUrl, seek: seekOffset })
    } catch {
      setState({ status: 'error' })
    }
  }, [item.cameraId, atMs])
  useEffect(() => { if (playRef) playRef.current = play }, [play, playRef])

  if (!item.cameraId) return null
  if (state.status === 'ready') {
    return (
      <video className="tq-video" src={state.url} controls autoPlay muted
        onLoadedMetadata={(e) => { e.currentTarget.currentTime = state.seek }}
        aria-label={`Recording from ${item.camera || 'the camera'} around the alert`} />
    )
  }
  return (
    <div className="tq-video-cta">
      <button type="button" className="btn btn-sm" disabled={state.status === 'loading'} onClick={play}>
        <Icons.live /> {state.status === 'loading' ? 'Loading video…' : 'Watch video from 10 s before'} <kbd>P</kbd>
      </button>
      {state.status === 'error' && (
        <span className="meta">
          No recording covers this moment. Video is saved in one-minute pieces while a camera streams,
          so a very recent alert can take a minute to appear.
        </span>
      )}
    </div>
  )
}

function TypeIcon({ type }) {
  const Icon = Icons[eventIconKey(type)] || Icons.eye
  return <Icon />
}

function ReviewTag({ status }) {
  if (!REVIEW_LABEL[status]) return null
  const tone = { pending: 'warn', confirmed: 'ok', rejected: 'muted' }[status] || 'muted'
  return <Tag tone={tone}>{REVIEW_LABEL[status]}</Tag>
}

function Fact({ label, value }) {
  if (value == null || value === '') return null
  return (<><dt>{label}</dt><dd>{value}</dd></>)
}

const JOURNEY_TYPES = new Set(['CRIMINAL_DETECTED', 'PERSON_TRACKED'])

function DetailPane({ item, detail, mode, setMode, busy, canAct, onConfirm, onReject, onDispatch, onIncident, now, escalation, playRef, onJourney, media = true }) {
  const [evIdx, setEvIdx] = useState(0)
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')

  const data = detail?.id === item.id ? detail.data : null
  const evidence = media ? data?.evidence?.filter((e) => e.has_image) || [] : []
  const shown = evidence[Math.min(evIdx, Math.max(evidence.length - 1, 0))]
  const resolved = item.acknowledged || item.dismissed
  const notifies = data?.holds_external_notification
  const when = parseTs(item.time)
  const n = item.repeats?.length || 1
  const urgency = waitUrgency(item, now, escalation)
  const waited = (now - (parseTs(item.since ?? item.time)?.getTime() || now)) / 1000
  const escalates = escalation?.after > 0 && escalation.types?.includes(item.type)
  const all = n > 1 ? ` all ${n}` : ''

  return (
    <div className="tq-detail">
      <header className="tq-detail-head">
        <span className={`tq-icon sev-${item.severity}`}><TypeIcon type={item.type} /></span>
        <div className="tq-title">
          <h3>{eventLabel(item.type)}</h3>
          <div className="meta">
            <span>{item.camera || 'Unknown camera'}</span>
            <span title={when ? when.toLocaleString() : ''}>{timeAgo(item.time)}</span>
            {when && <span className="mono">{when.toLocaleTimeString()}</span>}
          </div>
        </div>
        <span className="spacer" />
        <Tag tone={SEVERITY_TONE[item.severity] || 'muted'}>{item.severity}</Tag>
        <ReviewTag status={item.reviewStatus} />
      </header>

      {media && (
        <div className="tq-evidence">
          {shown ? (
            <img
              src={evidenceImageUrl(shown.id, 'frame')}
              alt={`Snapshot for ${eventLabel(item.type)} on ${item.camera || 'camera'}`}
            />
          ) : (
            <Empty icon={Icons.camera}>{data ? 'No snapshot was saved for this alert' : 'Loading snapshot…'}</Empty>
          )}
          {evidence.length > 1 && (
            <div className="tq-thumbs" role="group" aria-label="Snapshots">
              {evidence.map((e, i) => (
                <button
                  key={e.id} type="button" className={i === evIdx ? 'on' : ''}
                  onClick={() => setEvIdx(i)} aria-label={`Snapshot ${i + 1}`}
                >
                  <img src={evidenceImageUrl(e.id, 'roi')} alt="" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {urgency && (
        <p className={`tq-waiting u-${urgency}`} role="status">
          Waiting {waitLabel(waited)}
          {item.escalatedAt
            ? ` · backup officers were paged at ${parseTs(item.escalatedAt)?.toLocaleTimeString()}`
            : escalates && ` · backup officers are paged after ${waitLabel(escalation.after)} without acknowledgement`}
        </p>
      )}

      {n > 1 && (
        <p className="tq-repeat" role="note">
          Raised {n} times since {parseTs(item.since)?.toLocaleTimeString() || timeAgo(item.since)}.
          Your decision applies to all {n}.
        </p>
      )}

      {media && <AlertVideo item={item} playRef={playRef} />}

      {media && onJourney && JOURNEY_TYPES.has(item.type) && item.personName && item.personName !== 'Unknown' && (
        <button type="button" className="btn btn-sm tq-journey" onClick={() => onJourney(item.personName)}>
          <Icons.map /> Where else was {item.personName} seen?
        </button>
      )}

      {data?.identification?.match && <VehicleMatchCard id={data.identification} />}

      <p className="tq-why">{EXPLAIN[String(item.type).toUpperCase()] || item.msg}</p>

      <dl className="kv tq-facts">
        <Fact label="Confidence" value={data?.confidence != null ? `${Math.round(data.confidence * 100)}%` : null} />
        <Fact label="Zone" value={data?.zone} />
        <Fact label="Track" value={item.trackId != null && item.trackId >= 0 ? `#${item.trackId}` : null} />
        <Fact label="Candidate" value={item.personName && item.personName !== 'Unknown' ? `${item.personName} (unverified)` : null} />
        <Fact label="Plate" value={item.plate} />
        <Fact label="Details" value={item.msg} />
      </dl>

      {data?.related_events?.length > 0 && (
        <div className="tq-related">
          <div className="section-label"><span>Recent on this camera</span></div>
          {data.related_events.map((r) => (
            <div className="row" key={r.id}>
              <span>{eventLabel(r.type)}</span>
              <span className="meta">{timeAgo(r.timestamp)}</span>
            </div>
          ))}
        </div>
      )}

      {resolved ? (
        <div className="tq-resolved">
          <ReviewTag status={item.reviewStatus} />
          {item.reviewNote && <span className="meta">{item.reviewNote}</span>}
        </div>
      ) : !canAct ? (
        <div className="meta">Your role can view alerts but not act on them.</div>
      ) : mode === 'confirm' ? (
        <div className="tq-panel" role="group" aria-label="Confirm alert">
          <p>
            {notifies
              ? 'Confirming marks this as a real event and sends the held notification to external channels (security / law enforcement).'
              : 'Confirming marks this as a real event.'}
          </p>
          <div className="a-actions">
            <button type="button" className="btn btn-primary" disabled={busy} onClick={onConfirm} autoFocus>
              <Icons.check /> {notifies ? 'Confirm & notify' : 'Confirm'}{all}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setMode(null)}>Cancel</button>
          </div>
        </div>
      ) : mode === 'reject' ? (
        <div className="tq-panel" role="group" aria-label="Reject alert">
          <label className="field">
            <span>Reason (required — helps tune the detector)</span>
            <select value={reason} onChange={(e) => setReason(e.target.value)} autoFocus>
              <option value="">Select a reason…</option>
              {REJECT_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Note (optional)</span>
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} />
          </label>
          <div className="a-actions">
            <button
              type="button" className="btn btn-primary" disabled={busy || !reason}
              onClick={() => onReject(reason, note)}
            >Reject{all || ' alert'}</button>
            <button type="button" className="btn btn-ghost" onClick={() => setMode(null)}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="a-actions tq-actions">
          <button type="button" className="btn btn-primary" onClick={() => setMode('confirm')}>
            <Icons.check /> Confirm <kbd>V</kbd>
          </button>
          <button type="button" className="btn" onClick={() => setMode('reject')}>
            <Icons.close /> Reject <kbd>D</kbd>
          </button>
          <button type="button" className="btn" disabled={busy} onClick={onDispatch}><Icons.dispatch /> Dispatch police</button>
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={onIncident}>Create incident <kbd>I</kbd></button>
        </div>
      )}
    </div>
  )
}

export function Triage({ ctx }) {
  const { setEvents, setPage, reviewPending, refreshReviewCount } = ctx
  const { push: toast } = useToast()
  const [ask, confirmDialog] = useConfirm()
  const canAct = can(ctx.me?.role, 'triage.act')
  const [queue, setQueue] = useState('review')
  const [items, setItems] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [mode, setMode] = useState(null)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(() => Date.now())     // drives the waiting timers
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const playRef = useRef(null)
  const [journeyFor, setJourneyFor] = useState(null)

  const selected = items.find((i) => i.id === selectedId) || items[0] || null

  const load = useCallback(async () => {
    const q = QUEUES[queue]
    const rows = await fetchAlertsFiltered({ ...q.params, limit: 100 })
    return sortItems(groupRepeats(rows.map(fromAlertRow).filter(q.keep)), queue !== 'done')
  }, [queue])

  /* Reload on queue change, on new live events, and every 20 s as a safety net. */
  const liveCount = ctx.events.length
  useEffect(() => {
    let alive = true
    const run = () => load().then((list) => { if (alive) { setItems(list); setLoaded(true) } }).catch(() => {})
    run()
    const t = setInterval(run, 20000)
    return () => { alive = false; clearInterval(t) }
  }, [load, liveCount])

  const selId = selected?.id
  useEffect(() => {
    if (selId == null) return undefined
    let alive = true
    fetchAlertContext(selId)
      .then((data) => { if (alive) setDetail({ id: selId, data }) })
      .catch(() => { if (alive) setDetail({ id: selId, data: {} }) })
    return () => { alive = false }
  }, [selId])

  const move = useCallback((delta) => {
    if (!items.length) return
    const idx = Math.max(0, items.findIndex((i) => i.id === selected?.id))
    setSelectedId(items[Math.min(items.length - 1, Math.max(0, idx + delta))].id)
    setMode(null)
  }, [items, selected])

  const finish = useCallback((item, patch) => {
    const idx = items.findIndex((i) => i.id === item.id)
    const next = items[idx + 1] || items[idx - 1]
    const done = new Set(item.repeats || [item.id])
    setItems((prev) => prev.filter((i) => i.id !== item.id))
    setSelectedId(next ? next.id : null)
    setMode(null)
    setEvents?.((prev) => prev.map((e) => (done.has(e.id) ? { ...e, ...patch } : e)))
    refreshReviewCount?.()
  }, [items, setEvents, refreshReviewCount])

  // Applies `fn` to every alert in the selected entry (repeats included).
  const run = async (fn, okMsg, item, patch) => {
    setBusy(true)
    try {
      await Promise.all((item.repeats || [item.id]).map(fn))
      const n = item.repeats?.length || 1
      toast(n > 1 ? `${okMsg} (${n} alerts)` : okMsg, 'ok')
      finish(item, patch)
    } catch (err) {
      toast(err.message || 'Action failed', 'danger')
    } finally {
      setBusy(false)
    }
  }

  const confirm = () => selected && run(
    (id) => acknowledgeAlert(id, { acknowledged: true, dismissed: false }),
    'Alert confirmed', selected, { acknowledged: true },
  )
  const reject = (reason, note) => selected && run(
    (id) => acknowledgeAlert(id, {
      acknowledged: false, dismissed: true, note: `${reason}${note ? `: ${note}` : ''}`,
    }),
    'Alert rejected', selected, { dismissed: true },
  )
  const dispatch = async () => {
    if (!selected) return
    if (!(await ask({ title: 'Dispatch police', message: 'This notifies the configured external channels (CAD, SMS, security). Continue?', confirmLabel: 'Dispatch', danger: true }))) return
    // Police are dispatched once, for the newest alert; its repeats are acknowledged with it.
    run((id) => (id === selected.id ? dispatchPolice(id) : acknowledgeAlert(id, { acknowledged: true, dismissed: false })),
      'Police dispatched', selected, { acknowledged: true })
  }
  const incident = useCallback(async () => {
    if (!selected) return
    try {
      await createIncidentFromAlert(selected.id)
      toast('Incident created', 'ok')
      setPage?.('incidents')
    } catch (err) {
      toast(err.message || 'Failed to create incident', 'danger')
    }
  }, [selected, toast, setPage])

  /* Keyboard triage. A ref keeps the handler current without re-binding every render. */
  const keys = useRef(null)
  useEffect(() => {
    keys.current = { move, setMode, selected, incident, canAct }
  }, [move, selected, incident, canAct])
  useEffect(() => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return
      const k = keys.current
      if (!k) return
      const key = e.key.toLowerCase()
      if (key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); k.move(1) }
      else if (key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); k.move(-1) }
      else if (key === 'v' && k.selected) k.setMode('confirm')
      else if (key === 'd' && k.selected) { e.preventDefault(); k.setMode('reject') }
      else if (key === 'i' && k.selected && k.canAct) k.incident()
      else if (key === 'p' && k.selected) playRef.current?.()
      else if (e.key === 'Escape') k.setMode(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <>
      <div className="page-head">
        <div className="head-actions">
          <Seg
            value={queue}
            onChange={(v) => { setQueue(v); setSelectedId(null); setLoaded(false); setMode(null) }}
            options={[
              { value: 'review', label: `Needs review${reviewPending ? ` (${reviewPending})` : ''}` },
              { value: 'open', label: 'Open' },
              { value: 'done', label: 'Resolved' },
            ]}
          />
        </div>
      </div>

      <div className="triage">
        <Card title="Queue" flush sub={(() => {
          // Repeats are one entry: say both numbers so they add up with the sidebar badge.
          const total = items.reduce((n, i) => n + (i.repeats?.length || 1), 0)
          return total === items.length ? `${total} alert${total === 1 ? '' : 's'}` : `${items.length} entries · ${total} alerts`
        })()}>
          <div className="tq-list" role="listbox" aria-label="Alerts">
            {loaded && items.length === 0 && (
              <Empty icon={Icons.check}>
                {queue === 'review' ? 'Nothing waiting for review' : 'No alerts in this queue'}
              </Empty>
            )}
            {items.map((it) => (
              <button
                key={it.id} type="button" role="option"
                aria-selected={it.id === selected?.id}
                className={`tq-item ${it.id === selected?.id ? 'on' : ''}`}
                onClick={() => { setSelectedId(it.id); setMode(null) }}
              >
                <span className={`tq-icon sev-${it.severity}`}><TypeIcon type={it.type} /></span>
                <span className="tq-item-body">
                  <b>{eventLabel(it.type)}</b>
                  <span className="meta">
                    {it.camera || 'Unknown camera'} ·{' '}
                    {(() => {
                      const u = waitUrgency(it, now, ctx.escalation)
                      if (!u) return timeAgo(it.time)
                      const waited = (now - (parseTs(it.since ?? it.time)?.getTime() || now)) / 1000
                      return <span className={`tq-wait u-${u}`}>waiting {waitLabel(waited)}</span>
                    })()}
                  </span>
                </span>
                {it.repeats?.length > 1 && (
                  <span className="tq-count" title={`Raised ${it.repeats.length} times`} aria-label={`${it.repeats.length} times`}>×{it.repeats.length}</span>
                )}
                <Tag tone={SEVERITY_TONE[it.severity] || 'muted'}>{it.severity}</Tag>
              </button>
            ))}
          </div>
          <div className="tq-keys"><kbd>J</kbd><kbd>K</kbd> move <kbd>V</kbd> confirm <kbd>D</kbd> reject <kbd>I</kbd> incident <kbd>P</kbd> video</div>
        </Card>

        <Card title="Alert details" flush>
          {selected ? (
            <DetailPane
              key={selected.id}
              item={selected} detail={detail} mode={mode} setMode={setMode} busy={busy} canAct={canAct}
              onConfirm={confirm} onReject={reject} onDispatch={dispatch} onIncident={incident}
              now={now} escalation={ctx.escalation} playRef={playRef} onJourney={setJourneyFor}
              media={can(ctx.me?.role, 'media.view')}
            />
          ) : (
            <Empty icon={Icons.shield}>Select an alert to review it</Empty>
          )}
        </Card>
      </div>
      {confirmDialog}
      {journeyFor && <PersonJourney name={journeyFor} onClose={() => setJourneyFor(null)} onShowOnMap={ctx.showOnMap} />}
    </>
  )
}
