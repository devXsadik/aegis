/* Responders: the field officer's screen (works on a phone and on a desk).
   Top: who I am, my duty status and location sharing, the counts that matter.
   Then the notifications the tracker sent me (answer within the deadline) and the alerts at my
   cameras with a step-by-step progress: On my way → On scene → Resolved. */
import { useCallback, useEffect, useState } from 'react'
import { Icons, Seg, timeAgo } from '../components/ui'
import { Badge, EmptyState, ErrorState, SeverityBadge, SkeletonList } from '../components/ds'
import { useI18n } from '../hooks/useI18n'
import { useToast } from '../components/Toast'
import { captureImageUrl, fetchMyOfficer, fetchResponderAlerts, setMyDuty, setResponderStatus } from '../services/api'
import { eventLabel, waitLabel } from '../lib/events'
import { parseTs } from '../lib/time'
import { currentSubscription, pushSupported, turnOffPush, turnOnPush } from '../lib/push'
import { OfficerInbox } from '../components/OfficerInbox'
import { DUTY, OfficerAvatar } from '../components/Officers'

const OFFICER_ROLES = ['police', 'supervisor']
const hhmm = (ts) => parseTs(ts)?.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) || ''

/** "Phone alerts": this device buzzes on a new alert even with the screen off (Web Push). */
function PhoneAlerts({ toast }) {
  const [on, setOn] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { currentSubscription().then((s) => setOn(!!s)).catch(() => setOn(false)) }, [])
  if (!pushSupported()) {
    return <span className="meta" title="Browsers only allow phone alerts over HTTPS">Phone alerts need HTTPS</span>
  }
  const toggle = async () => {
    setBusy(true)
    try {
      if (on) { await turnOffPush(); setOn(false); toast('Phone alerts off on this device', 'ok') }
      else { await turnOnPush(); setOn(true); toast('Phone alerts on: this device will buzz on a new alert', 'ok') }
    } catch (e) {
      toast(e.message || 'Could not change phone alerts', 'danger')
    } finally {
      setBusy(false)
    }
  }
  return (
    <button type="button" className={`btn btn-sm rsp-push ${on ? 'on' : ''}`} disabled={busy || on === null} onClick={toggle}
      aria-pressed={!!on} title="Notifications on this device for new alerts, even when Aegis is closed">
      <Icons.bell /> {on ? 'Phone alerts on' : 'Turn on phone alerts'}
    </button>
  )
}

/** The officer's own card: name, rank, station, duty status and location sharing. */
function DutyCard({ toast }) {
  const [me, setMe] = useState(null)
  const [busy, setBusy] = useState(false)
  const [sharing, setSharing] = useState(false)
  useEffect(() => { fetchMyOfficer().then(setMe).catch(() => setMe(false)) }, [])

  const position = () => new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null)
    navigator.geolocation.getCurrentPosition((p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      () => resolve(null), { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 })
  })
  const change = async (duty, withPos = sharing) => {
    setBusy(true)
    try {
      const pos = withPos ? await position() : null
      if (withPos && !pos) { setSharing(false); toast('Location is blocked on this device; status saved without it', 'warn') }
      setMe(await setMyDuty(duty, pos))
      toast(`You are now: ${DUTY[duty].label}`, 'ok')
    } catch (e) {
      toast(e.message || 'Could not update your status', 'danger')
    } finally {
      setBusy(false)
    }
  }
  // While sharing, send the position every minute so dispatch sees who is closest.
  useEffect(() => {
    if (!sharing || !me) return undefined
    const t = setInterval(async () => {
      const pos = await position()
      if (pos) setMyDuty(me.duty_status, pos).then(setMe).catch(() => {})
    }, 60000)
    return () => clearInterval(t)
  }, [sharing, me])

  if (me === null) return <div className="rsp-me"><SkeletonList rows={1} /></div>
  if (me === false) return null
  const duty = DUTY[me.duty_status] || DUTY.off_duty
  return (
    <section className="rsp-me" aria-label="My duty status">
      <div className="rsp-me-who">
        <OfficerAvatar id={me.id} name={me.name} hasPhoto={me.has_photo} size={52} ring={duty.tone} />
        <div>
          <b className="rsp-me-name">{me.rank ? `${me.rank} ` : ''}{me.name}</b>
          <span className="meta">
            {[...new Set([me.badge_no && `#${me.badge_no}`, me.station, ...(me.jurisdictions || []).map((j) => j.name)].filter(Boolean))].join(' · ') || 'No area assigned yet'}
          </span>
        </div>
        <Badge tone={duty.tone}>{duty.label}</Badge>
      </div>
      <div className="rsp-me-controls">
        <div className="rsp-duty" role="radiogroup" aria-label="Duty status">
          {Object.entries(DUTY).map(([k, d]) => (
            <button key={k} type="button" role="radio" aria-checked={me.duty_status === k} disabled={busy}
              className={`rsp-duty-btn tone-${d.tone} ${me.duty_status === k ? 'on' : ''}`} onClick={() => change(k)}>
              {d.label}
            </button>
          ))}
        </div>
        <label className="rsp-share">
          <input type="checkbox" checked={sharing} disabled={busy}
            onChange={(e) => { setSharing(e.target.checked); if (e.target.checked) change(me.duty_status, true) }} />
          <span>Share my location with dispatch</span>
          {me.last_seen_at && <span className="meta">· last sent {timeAgo(me.last_seen_at)}</span>}
        </label>
      </div>
    </section>
  )
}

// Each step offers the next one; resolved is the end.
const STEPS = [
  { status: null, label: 'Alert raised' },
  { status: 'en_route', label: 'On my way' },
  { status: 'on_scene', label: 'On scene' },
  { status: 'resolved', label: 'Resolved' },
]
const NEXT = { null: ['en_route', 'On my way', Icons.dispatch], en_route: ['on_scene', "I'm on scene", Icons.map], on_scene: ['resolved', 'Mark resolved', Icons.check] }
const STEP_LABEL = { en_route: 'On my way', on_scene: 'On scene', resolved: 'Resolved' }

function Progress({ a }) {
  const at = Object.fromEntries(a.steps.map((s) => [s.status, s]))
  const reached = STEPS.findIndex((s) => s.status === (a.status ?? null))
  return (
    <ol className="rsp-progress" aria-label="Response progress">
      {STEPS.map((s, i) => {
        const step = s.status ? at[s.status] : { at: a.time }
        const state = i < reached ? 'done' : i === reached ? 'now' : 'todo'
        return (
          <li key={s.label} className={state} aria-current={state === 'now' ? 'step' : undefined}>
            <span className="rsp-dot">{state === 'done' || (state === 'now' && s.status === 'resolved') ? <Icons.check /> : i + 1}</span>
            <span className="rsp-step-text">
              <b>{s.label}</b>
              {step && <span>{hhmm(step.at)}{step.by ? ` · ${step.by}` : ''}</span>}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function AlertCard({ a, now, busy, onStep }) {
  const [note, setNote] = useState('')
  const next = NEXT[a.status ?? null]
  const waited = (now - (parseTs(a.time)?.getTime() || now)) / 1000
  const NextIcon = next?.[2]
  const title = `${eventLabel(a.type)}${a.person_name && a.person_name !== 'Unknown' ? `: ${a.person_name}` : ''}`
  return (
    <article className={`rsp-card ${a.status === 'resolved' ? 'done' : ''} ${a.capture_id ? '' : 'no-shot'} sev-${a.severity}`} aria-label={title}>
      {a.capture_id && (
        <div className="rsp-media"><img src={captureImageUrl(a.capture_id, 480)} alt={`Still from ${a.camera}`} loading="lazy" /></div>
      )}
      <div className="rsp-body">
        <div className="rsp-title">
          <b>{title}</b>
          <SeverityBadge level={a.severity} size="sm" />
        </div>
        <div className="rsp-where"><Icons.map /> {a.camera}{a.location && a.location !== a.camera ? ` · ${a.location}` : ''}</div>
        <div className="rsp-meta meta">
          <Icons.clock /> {a.status === 'resolved' ? `Raised ${timeAgo(a.time)}` : `Waiting ${waitLabel(waited)}`}
          {a.ticket_id && <Badge tone="muted" size="sm" icon={Icons.incident}>{a.ticket_id}</Badge>}
        </div>
        <Progress a={a} />
        {a.status !== 'resolved' && next && (
          <div className="rsp-do">
            <input className="input rsp-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={300}
              placeholder="Add a note for the control room (optional)" aria-label="Note for the control room" />
            <div className="rsp-actions">
              {a.maps_url && (
                <a className="btn rsp-btn" href={a.maps_url} target="_blank" rel="noreferrer"><Icons.map /> Directions</a>
              )}
              <button type="button" className="btn btn-primary rsp-btn" disabled={busy}
                onClick={async () => { if (await onStep(a, next[0], note)) setNote('') }}>
                <NextIcon /> {next[1]}
              </button>
            </div>
          </div>
        )}
      </div>
    </article>
  )
}

export function Responder({ ctx }) {
  const { push: toast } = useToast()
  const [data, setData] = useState(null)
  const [show, setShow] = useState('open')
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const [toAnswer, setToAnswer] = useState(0)
  const { t } = useI18n()
  const [error, setError] = useState('')
  const isOfficer = OFFICER_ROLES.includes(ctx.me?.role)
  const load = useCallback(() => fetchResponderAlerts()
    .then((d) => { setData(d); setError('') })
    .catch((e) => setError(e.message || 'error')), [])
  const liveCount = ctx.events.length
  useEffect(() => {
    load()
    const id = setInterval(load, 10000)
    return () => clearInterval(id)
  }, [load, liveCount])        // a new alert on the socket refreshes the list at once
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const step = async (a, status, note) => {
    setBusy(true)
    try {
      await setResponderStatus(a.id, status, note)
      toast(`${STEP_LABEL[status]} — the control room can see it`, 'ok')
      load()
      return true
    } catch (e) {
      toast(e.message || 'Could not update', 'danger')
      return false
    } finally {
      setBusy(false)
    }
  }

  const all = data?.alerts || []
  const open = all.filter((a) => a.status !== 'resolved')
  const counts = {
    waiting: open.filter((a) => !a.status).length,
    active: open.filter((a) => a.status).length,
    done: all.length - open.length,
  }
  const alerts = show === 'open' ? open : all.filter((a) => a.status === 'resolved')
  const scope = data?.assigned_cameras?.length
    ? `${data.assigned_cameras.length} camera${data.assigned_cameras.length === 1 ? '' : 's'} in your area`
    : 'All cameras'

  return (
    <div className="rsp">
      {isOfficer && <DutyCard toast={toast} />}

      <div className="rsp-stats" role="list" aria-label="Summary">
        <div role="listitem" className={`rsp-stat ${toAnswer ? 'hot' : ''}`}><b>{toAnswer}</b><span>To answer</span></div>
        <div role="listitem" className={`rsp-stat ${counts.waiting ? 'warn' : ''}`}><b>{data ? counts.waiting : '–'}</b><span>Waiting for someone</span></div>
        <div role="listitem" className="rsp-stat"><b>{data ? counts.active : '–'}</b><span>In progress</span></div>
        <div role="listitem" className="rsp-stat"><b>{data ? counts.done : '–'}</b><span>Resolved (24 h)</span></div>
      </div>

      <div className="rsp-grid">
        <section className="rsp-main" aria-labelledby="rsp-alerts-h">
          <header className="rsp-section-head">
            <div>
              <h2 id="rsp-alerts-h">Alerts to attend</h2>
              <span className="meta">{scope} · critical and high · last 24 hours</span>
            </div>
            <div className="rsp-tools">
              <PhoneAlerts toast={toast} />
              <Seg value={show} onChange={setShow} options={[
                { value: 'open', label: `To do${data ? ` (${open.length})` : ''}` },
                { value: 'done', label: 'Resolved' },
              ]} />
            </div>
          </header>
          {!data && !error && <SkeletonList rows={3} />}
          {!data && error && <ErrorState title={t('respond.loadError')} message={error} onRetry={load} />}
          {data && alerts.length === 0 && (
            show === 'open'
              ? <EmptyState icon={Icons.check} title={t('respond.empty')}>{t('respond.emptyMsg')}</EmptyState>
              : <EmptyState icon={Icons.clock} title={t('respond.emptyDone')} />
          )}
          <div className="rsp-list">
            {alerts.map((a) => <AlertCard key={a.id} a={a} now={now} busy={busy} onStep={step} />)}
          </div>
        </section>

        <aside className="rsp-side" aria-label="Notifications for you">
          <OfficerInbox me={ctx.me} onOpenCount={setToAnswer} />
        </aside>
      </div>
    </div>
  )
}
