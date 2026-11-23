/* Responders: the field officer's screen (works on a phone and on a desk).
   Top: who I am, my duty status and location sharing, the counts that matter.
   Then the notifications the tracker sent me (answer within the deadline) and the alerts at my
   cameras with a step-by-step progress: On my way → On scene → Resolved. */
import { useCallback, useEffect, useState } from 'react'
import { Icons, Seg, timeAgo } from '../components/ui'
import { Badge, EmptyState, ErrorState, SeverityBadge, SkeletonList } from '../components/ds'
import { useI18n } from '../hooks/useI18n'
import { useToast } from '../components/Toast'
import { captureImageUrl, fetchIncidentsPage, fetchMyOfficer, fetchRoster, fetchResponderAlerts, setMyDuty, setResponderStatus } from '../services/api'
import { IncidentMessages } from '../components/IncidentMessages'
import { OPEN_STATUSES } from '../lib/incidentStatus'
import { eventLabel, waitLabel } from '../lib/events'
import { parseTs } from '../lib/time'
import { currentSubscription, pushSupported, turnOffPush, turnOnPush } from '../lib/push'
import { OfficerInbox } from '../components/OfficerInbox'
import { DUTY, OfficerAvatar } from '../components/Officers'

const OFFICER_ROLES = ['police', 'supervisor']
const hhmm = (ts) => parseTs(ts)?.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) || ''

/** "Phone alerts": this device buzzes on a new alert even with the screen off (Web Push). */
function PhoneAlerts({ toast }) {
  const { t } = useI18n()
  const [on, setOn] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { currentSubscription().then((s) => setOn(!!s)).catch(() => setOn(false)) }, [])
  if (!pushSupported()) {
    return <span className="meta" title="Browsers only allow phone alerts over HTTPS">{t('rsp.phoneNeedsHttps')}</span>
  }
  const toggle = async () => {
    setBusy(true)
    try {
      if (on) { await turnOffPush(); setOn(false); toast(t('rsp.phoneOffToast'), 'ok') }
      else { await turnOnPush(); setOn(true); toast(t('rsp.phoneOnToast'), 'ok') }
    } catch (e) {
      toast(e.message || 'Could not change phone alerts', 'danger')
    } finally {
      setBusy(false)
    }
  }
  return (
    <button type="button" className={`btn btn-sm rsp-push ${on ? 'on' : ''}`} disabled={busy || on === null} onClick={toggle}
      aria-pressed={!!on} title="Notifications on this device for new alerts, even when Aegis is closed">
      <Icons.bell /> {on ? t('rsp.phoneOn') : t('rsp.phoneTurnOn')}
    </button>
  )
}

/** The officer's own card: name, rank, station, duty status and location sharing. */
function DutyCard({ toast }) {
  const { t } = useI18n()
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
      if (withPos && !pos) { setSharing(false); toast(t('rsp.locBlocked'), 'warn') }
      setMe(await setMyDuty(duty, pos))
      toast(t('rsp.nowDuty', { duty: t(`duty.${duty}`) }), 'ok')
    } catch (e) {
      toast(e.message || 'Could not update your status', 'danger')
    } finally {
      setBusy(false)
    }
  }
  // While sharing, send the position every minute so dispatch sees who is closest.
  useEffect(() => {
    if (!sharing || !me) return undefined
    const timer = setInterval(async () => {
      const pos = await position()
      if (pos) setMyDuty(me.duty_status, pos).then(setMe).catch(() => {})
    }, 60000)
    return () => clearInterval(timer)
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
            {[...new Set([me.badge_no && `#${me.badge_no}`, me.station, ...(me.jurisdictions || []).map((j) => j.name)].filter(Boolean))].join(' · ') || t('rsp.noArea')}
          </span>
        </div>
        <Badge tone={duty.tone}>{t(`duty.${me.duty_status in DUTY ? me.duty_status : 'off_duty'}`)}</Badge>
      </div>
      <div className="rsp-me-controls">
        <div className="rsp-duty" role="radiogroup" aria-label={t('rsp.dutyStatus')}>
          {Object.entries(DUTY).map(([k, d]) => (
            <button key={k} type="button" role="radio" aria-checked={me.duty_status === k} disabled={busy}
              className={`rsp-duty-btn tone-${d.tone} ${me.duty_status === k ? 'on' : ''}`} onClick={() => change(k)}>
              {t(`duty.${k}`)}
            </button>
          ))}
        </div>
        <label className="rsp-share">
          <input type="checkbox" checked={sharing} disabled={busy}
            onChange={(e) => { setSharing(e.target.checked); if (e.target.checked) change(me.duty_status, true) }} />
          <span>{t('rsp.share')}</span>
          {me.last_seen_at && <span className="meta">· {t('rsp.lastSent', { when: timeAgo(me.last_seen_at) })}</span>}
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

function Progress({ a }) {
  const { t } = useI18n()
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
              <b>{t(`step.${s.status || 'raised'}`)}</b>
              {step && <span>{hhmm(step.at)}{step.by ? ` · ${step.by}` : ''}</span>}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function AlertCard({ a, now, busy, onStep }) {
  const { t } = useI18n()
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
          <Icons.clock /> {a.status === 'resolved' ? t('rsp.raised', { when: timeAgo(a.time) }) : t('rsp.waiting', { when: waitLabel(waited) })}
          {a.ticket_id && <Badge tone="muted" size="sm" icon={Icons.incident}>{a.ticket_id}</Badge>}
        </div>
        <Progress a={a} />
        {a.status !== 'resolved' && next && (
          <div className="rsp-do">
            <input className="input rsp-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={300}
              placeholder={t('rsp.notePh')} aria-label={t('rsp.notePh')} />
            <div className="rsp-actions">
              {a.maps_url && (
                <a className="btn rsp-btn" href={a.maps_url} target="_blank" rel="noreferrer"><Icons.map /> {t('rsp.directions')}</a>
              )}
              <button type="button" className="btn btn-primary rsp-btn" disabled={busy}
                onClick={async () => { if (await onStep(a, next[0], note)) setNote('') }}>
                <NextIcon /> {t(`next.${next[0]}`)}
              </button>
            </div>
          </div>
        )}
      </div>
    </article>
  )
}

/* Incidents this officer is assigned to, each with its dispatch thread. */
function MyIncidents({ me }) {
  const { t } = useI18n()
  const [items, setItems] = useState(null)
  const [openId, setOpenId] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(() => fetchIncidentsPage({ officer_id: me.id, status: OPEN_STATUSES.join(','), limit: 20 })
    .then((d) => { setItems(d.items || []); setError('') })
    .catch((e) => setError(e.message || 'Could not load your incidents')), [me.id])
  useEffect(() => {
    load()
    const id = setInterval(load, 20000)
    return () => clearInterval(id)
  }, [load])
  if (!items && !error) return null
  if (error) return <ErrorState compact message={error} onRetry={load} />
  if (!items.length) return null
  return (
    <section className="rsp-incidents card" aria-labelledby="rsp-inc-h">
      <header className="rsp-section-head">
        <div>
          <h2 id="rsp-inc-h">{t('rsp.yourIncidents')}</h2>
          <span className="meta">{t('rsp.yourIncidentsSub')}</span>
        </div>
      </header>
      <ul className="rsp-inc-list">
        {items.map((i) => (
          <li key={i.id}>
            <button type="button" className="rsp-inc-row" aria-expanded={openId === i.id} onClick={() => setOpenId(openId === i.id ? null : i.id)}>
              <span className="mono">{i.ticket_id}</span>
              <b>{i.title}</b>
              <SeverityBadge level={i.priority} size="sm" />
              <span className="muted">{i.camera_location || ''} · {timeAgo(i.created_at)}</span>
              <span className="rsp-inc-cta">{openId === i.id ? t('rsp.close') : t('rsp.messages')}</span>
            </button>
            {openId === i.id && <div className="rsp-inc-thread"><IncidentMessages incidentId={i.id} me={me} compact /></div>}
          </li>
        ))}
      </ul>
    </section>
  )
}

/* The officer's next or current shift from the roster. */
function MyShift() {
  const { t } = useI18n()
  const [shift, setShift] = useState(undefined)
  useEffect(() => {
    fetchRoster({ days: 2 }).then((d) => {
      const now = Date.now()
      setShift((d.shifts || []).find((s) => parseTs(s.ends_at) > now) || null)
    }).catch(() => setShift(null))
  }, [])
  if (!shift) return null
  const fmt = (v) => parseTs(v)?.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })
  return (
    <p className="rsp-shift" role="status">
      <Icons.clock /> <b>{shift.now ? t('rsp.onShiftUntil', { t: fmt(shift.ends_at) }) : t('rsp.nextShift', { t: `${fmt(shift.starts_at)} – ${fmt(shift.ends_at)}` })}</b>
      {shift.area && <> · {shift.area}</>}{shift.assignment && <> · {shift.assignment}</>}
    </p>
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
      toast(t('rsp.stepToast', { step: t(`step.${status}`) }), 'ok')
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
    ? t('rsp.scopeArea', { n: data.assigned_cameras.length })
    : t('rsp.scopeAll')

  return (
    <div className="rsp">
      {isOfficer && <DutyCard toast={toast} />}
      {isOfficer && <MyShift />}
      {isOfficer && ctx.me && <MyIncidents me={ctx.me} />}

      <div className="rsp-stats" role="list" aria-label="Summary">
        <div role="listitem" className={`rsp-stat ${toAnswer ? 'hot' : ''}`}><b>{toAnswer}</b><span>{t('rsp.toAnswer')}</span></div>
        <div role="listitem" className={`rsp-stat ${counts.waiting ? 'warn' : ''}`}><b>{data ? counts.waiting : '–'}</b><span>{t('rsp.waitingSomeone')}</span></div>
        <div role="listitem" className="rsp-stat"><b>{data ? counts.active : '–'}</b><span>{t('rsp.inProgress')}</span></div>
        <div role="listitem" className="rsp-stat"><b>{data ? counts.done : '–'}</b><span>{t('rsp.resolved24')}</span></div>
      </div>

      <div className="rsp-grid">
        <section className="rsp-main" aria-labelledby="rsp-alerts-h">
          <header className="rsp-section-head">
            <div>
              <h2 id="rsp-alerts-h">{t('rsp.alertsTitle')}</h2>
              <span className="meta">{scope} · {t('rsp.scopeTail')}</span>
            </div>
            <div className="rsp-tools">
              <PhoneAlerts toast={toast} />
              <Seg value={show} onChange={setShow} options={[
                { value: 'open', label: `${t('rsp.todo')}${data ? ` (${open.length})` : ''}` },
                { value: 'done', label: t('rsp.done') },
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
