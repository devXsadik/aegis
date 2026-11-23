import { useCallback, useEffect, useState } from 'react'
import { Icons, Seg, timeAgo } from '../components/ui'
import { EmptyState, ErrorState, SeverityBadge, SkeletonList } from '../components/ds'
import { useI18n } from '../hooks/useI18n'
import { useToast } from '../components/Toast'
import { captureImageUrl, fetchResponderAlerts, setResponderStatus } from '../services/api'
import { eventLabel, waitLabel } from '../lib/events'
import { parseTs } from '../lib/time'
import { currentSubscription, pushSupported, turnOffPush, turnOnPush } from '../lib/push'
import { OfficerInbox } from '../components/OfficerInbox'

/** "Phone alerts": this device buzzes on a new alert even with the screen off (Web Push). */
function PhoneAlerts({ toast }) {
  const [on, setOn] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { currentSubscription().then((s) => setOn(!!s)).catch(() => setOn(false)) }, [])
  if (!pushSupported()) {
    return <span className="meta rsp-push">Phone alerts need the dashboard over HTTPS (or localhost)</span>
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

// Each step offers the next one; resolved is the end.
const NEXT = { null: ['en_route', 'On my way'], en_route: ['on_scene', 'On scene'], on_scene: ['resolved', 'Resolved'] }
const STEP_LABEL = { en_route: 'On my way', on_scene: 'On scene', resolved: 'Resolved' }

function Card({ a, now, busy, onStep }) {
  const [note, setNote] = useState('')
  const next = NEXT[a.status ?? null]
  const waited = (now - (parseTs(a.time)?.getTime() || now)) / 1000
  return (
    <article className={`rsp-card ${a.status === 'resolved' ? 'done' : ''} sev-${a.severity}`}>
      {a.capture_id && <img className="rsp-photo" src={captureImageUrl(a.capture_id, 480)} alt={`Still from ${a.camera}`} loading="lazy" />}
      <div className="rsp-body">
        <div className="rsp-title">
          <b>{eventLabel(a.type)}{a.person_name && a.person_name !== 'Unknown' ? `: ${a.person_name}` : ''}</b>
          <SeverityBadge level={a.severity} size="sm" />
        </div>
        <div className="rsp-where">
          <Icons.map /> {a.camera}{a.location && a.location !== a.camera ? ` · ${a.location}` : ''}
        </div>
        <div className="meta">
          {a.status === 'resolved' ? `Raised ${timeAgo(a.time)}` : `Raised ${waitLabel(waited)} ago`}{a.ticket_id ? ` · ${a.ticket_id}` : ''}
        </div>
        {a.steps.length > 0 && (
          <ol className="rsp-steps">
            {a.steps.map((s) => (
              <li key={`${s.status}-${s.at}`}><b>{STEP_LABEL[s.status]}</b> {s.by} · {parseTs(s.at)?.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</li>
            ))}
          </ol>
        )}
        {a.status !== 'resolved' && (
          <>
            <input className="input rsp-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={300}
              placeholder="Note (optional), e.g. suspect left towards the market" aria-label="Note" />
            <div className="rsp-actions">
              {a.maps_url && (
                <a className="btn rsp-btn" href={a.maps_url} target="_blank" rel="noreferrer"><Icons.map /> Directions</a>
              )}
              <button type="button" className="btn btn-primary rsp-btn" disabled={busy}
                onClick={async () => { if (await onStep(a, next[0], note)) setNote('') }}>
                <Icons.check /> {next[1]}
              </button>
            </div>
          </>
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
  const { t } = useI18n()
  const [error, setError] = useState('')
  const load = useCallback(() => fetchResponderAlerts()
    .then((d) => { setData(d); setError('') })
    .catch((e) => setError(e.message || 'error')), [])
  const liveCount = ctx.events.length
  useEffect(() => {
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [load, liveCount])        // a new alert on the socket refreshes the list at once
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
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

  const alerts = (data?.alerts || []).filter((a) => (show === 'open' ? a.status !== 'resolved' : a.status === 'resolved'))
  return (
    <div className="rsp">
      <OfficerInbox me={ctx.me} />
      <div className="rsp-head">
        <span className="meta">
          {data?.assigned_cameras?.length ? `Your cameras: ${data.assigned_cameras.length}` : 'All cameras (none assigned to you)'} · last 24 hours
        </span>
        <div className="rsp-tools">
          <PhoneAlerts toast={toast} />
          <Seg value={show} onChange={setShow} options={[{ value: 'open', label: 'To do' }, { value: 'done', label: 'Resolved' }]} />
        </div>
      </div>
      {!data && !error && <SkeletonList rows={3} />}
      {!data && error && <ErrorState title={t('respond.loadError')} message={error} onRetry={load} />}
      {data && alerts.length === 0 && (
        show === 'open'
          ? <EmptyState icon={Icons.check} title={t('respond.empty')}>{t('respond.emptyMsg')}</EmptyState>
          : <EmptyState icon={Icons.clock} title={t('respond.emptyDone')} />
      )}
      <div className="rsp-list">
        {alerts.map((a) => <Card key={a.id} a={a} now={now} busy={busy} onStep={step} />)}
      </div>
    </div>
  )
}
