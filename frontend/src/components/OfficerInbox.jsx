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
  { state: 'acknowledged', label: 'Acknowledge', cls: '' },
  { state: 'en_route', label: 'En route', cls: 'btn-primary' },
  { state: 'located', label: 'Located', cls: '' },
  { state: 'unable', label: 'Unable', cls: 'btn-ghost' },
]

function Countdown({ deadline }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [])
  const d = parseTs(deadline)
  if (!d) return null
  const s = Math.round((d.getTime() - now) / 1000)
  return <Badge tone={s < 0 ? 'danger' : s < 30 ? 'warn' : 'muted'} size="sm" icon={Icons.clock}>{s < 0 ? 'Overdue — escalated' : `Answer within ${s}s`}</Badge>
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
          <p className="meta"><Icons.check /> You answered “{(n.ack_state || '').replace('_', ' ')}” {timeAgo(n.acked_at)}</p>
        ) : (
          <div className="inbox-actions">
            {ANSWERS.map((a) => (
              <button key={a.state} type="button" className={`btn rsp-btn ${a.cls}`} disabled={busy} onClick={() => onAnswer(n, a.state)}>{a.label}</button>
            ))}
            {maps && <a className="btn rsp-btn" href={maps} target="_blank" rel="noreferrer"><Icons.map /> Directions</a>}
          </div>
        )}
      </div>
    </article>
  )
}

export function OfficerInbox({ me }) {
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
      toast(`Answered: ${state.replace('_', ' ')}`, 'ok')
    } catch (e) {
      toast(e.message || 'Could not send', 'danger')
    } finally {
      setBusy(false)
    }
  }
  if (items === null) return null
  const open = items.filter((n) => !n.acked_at)
  const done = items.filter((n) => n.acked_at).slice(0, 5)
  return (
    <section className="inbox" aria-label="My notifications">
      <h2 className="inc-section-title">Notifications for you {open.length > 0 && <Badge tone="danger" size="sm">{open.length} to answer</Badge>}</h2>
      {items.length === 0 && <EmptyState compact icon={Icons.bell} title="No notifications">Targets in or heading into your area appear here.</EmptyState>}
      {open.map((n) => <Item key={n.id} n={n} onAnswer={answer} busy={busy} />)}
      {done.map((n) => <Item key={n.id} n={n} onAnswer={answer} busy={busy} />)}
    </section>
  )
}
