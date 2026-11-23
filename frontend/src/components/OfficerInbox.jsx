/* Officer's phone view of their notifications: target, where, direction, ETA, snapshot, map —
   and the four answers that update the incident: Acknowledge / En route / Located / Unable. */
import { useCallback, useEffect, useState } from 'react'
import { Icons, timeAgo } from './ui'
import { Badge, EmptyState } from './ds'
import { ackNotification, fetchMyNotifications } from '../services/api'
import { useWebSocket } from '../hooks/useWebSocket'
import { useToast } from './Toast'
import { parseTs } from '../lib/time'

const KIND = {
  target_detected: { tone: 'danger', label: 'Target detected', icon: Icons.alert },
  heading_to_area: { tone: 'orange', label: 'Heading your way', icon: Icons.dispatch },
  escalation: { tone: 'warn', label: 'Escalated to you', icon: Icons.bell },
  lost: { tone: 'muted', label: 'Track lost', icon: Icons.eye },
  assigned: { tone: 'info', label: 'Assigned', icon: Icons.users },
}
const ANSWERS = [
  { state: 'en_route', label: 'On my way', cls: 'btn-primary', icon: Icons.dispatch },
  { state: 'acknowledged', label: 'Seen it', cls: '', icon: Icons.check },
  { state: 'located', label: 'Target located', cls: '', icon: Icons.eye },
  { state: 'unable', label: "Can't respond", cls: 'inbox-unable', icon: Icons.close },
]
const ANSWER_LABEL = { acknowledged: 'Seen it', en_route: 'On my way', located: 'Target located', unable: "Can't respond" }
const mmss = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

function Countdown({ deadline }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [])
  const d = parseTs(deadline)
  if (!d) return null
  const s = Math.round((d.getTime() - now) / 1000)
  return <Badge tone={s < 0 ? 'danger' : s < 30 ? 'warn' : 'muted'} size="sm" icon={Icons.clock}>{s < 0 ? 'Overdue — escalated' : `Answer within ${mmss(s)}`}</Badge>
}

function Item({ n, onAnswer, busy }) {
  const k = KIND[n.kind] || { tone: 'muted', label: n.kind, icon: Icons.bell }
  const p = n.payload || {}
  const maps = p.lat != null ? `https://www.google.com/maps/dir/?api=1&destination=${p.lat},${p.lng}` : null
  return (
    <article className={`inbox-card tone-${k.tone} ${n.acked_at ? 'done' : ''}`} aria-label={n.title}>
      {p.snapshot && <img className="inbox-photo" src={p.snapshot} alt="Snapshot of the target" loading="lazy" />}
      <div className="inbox-body">
        <div className="wl-title">
          <Badge tone={k.tone} icon={k.icon} size="sm">{k.label}</Badge>
          {p.direction && <Badge tone="cyan" size="sm" icon={Icons.map}>Moving {p.direction}</Badge>}
          {!n.acked_at && n.ack_deadline && <Countdown deadline={n.ack_deadline} />}
          <span className="meta">{timeAgo(n.created_at)}</span>
        </div>
        <h3 className="inbox-title">{n.title}</h3>
        {n.body && <p className="inbox-text">{n.body}</p>}
        {n.acked_at ? (
          <p className="meta"><Icons.check /> You answered “{ANSWER_LABEL[n.ack_state] || n.ack_state}” {timeAgo(n.acked_at)}</p>
        ) : (
          <div className="inbox-actions">
            {ANSWERS.map((a) => (
              <button key={a.state} type="button" className={`btn ${a.cls}`} disabled={busy} onClick={() => onAnswer(n, a.state)}><a.icon /> {a.label}</button>
            ))}
            {maps && <a className="btn" href={maps} target="_blank" rel="noreferrer"><Icons.map /> Directions</a>}
          </div>
        )}
      </div>
    </article>
  )
}

export function OfficerInbox({ me, onOpenCount }) {
  const { push: toast } = useToast()
  const [items, setItems] = useState(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => fetchMyNotifications().then(setItems).catch(() => setItems([])), [])
  useEffect(() => { load() }, [load])
  const onLive = useCallback((msg) => {
    if (msg?.event_type !== 'NOTIFICATION') return
    setItems((list) => [msg, ...(list || []).filter((x) => x.id !== msg.id)])
    toast(msg.title, msg.priority === 'critical' ? 'danger' : 'warn')
    try { navigator.vibrate?.([200, 100, 200]) } catch { /* not a phone */ }
  }, [toast])
  useWebSocket('notifications', onLive, !!me)
  const answer = async (n, state) => {
    setBusy(true)
    try {
      const updated = await ackNotification(n.id, state)
      setItems((list) => list.map((x) => (x.id === n.id ? updated : x)))
      toast(`Answered: ${ANSWER_LABEL[state]}`, 'ok')
    } catch (e) {
      toast(e.message || 'Could not send', 'danger')
    } finally {
      setBusy(false)
    }
  }
  const open = (items || []).filter((n) => !n.acked_at)
  const done = (items || []).filter((n) => n.acked_at).slice(0, 5)
  useEffect(() => { onOpenCount?.(open.length) }, [open.length, onOpenCount])
  if (items === null) return null
  return (
    <section className="inbox" aria-labelledby="inbox-h">
      <header className="rsp-section-head">
        <div>
          <h2 id="inbox-h">Notifications for you</h2>
          <span className="meta">Targets in or heading into your area</span>
        </div>
        {open.length > 0 && <Badge tone="danger">{open.length} to answer</Badge>}
      </header>
      {items.length === 0 && <EmptyState compact icon={Icons.bell} title="Nothing for you right now">When a tracked target enters or heads into your area, it appears here and your phone buzzes.</EmptyState>}
      {open.map((n) => <Item key={n.id} n={n} onAnswer={answer} busy={busy} />)}
      {done.length > 0 && <h3 className="inbox-sub">Answered</h3>}
      {done.map((n) => <Item key={n.id} n={n} onAnswer={answer} busy={busy} />)}
    </section>
  )
}
