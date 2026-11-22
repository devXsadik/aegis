/* Small pieces of the shell: the top bar's clock and account menu, and Home's ask bar. */
import { useEffect, useState } from 'react'
import { Icons } from './ui'

/** Home only: type a question, Quick answers opens with the answer. */
export function AskBar({ liveCount, onAsk }) {
  const [q, setQ] = useState('')
  const submit = (e) => {
    e.preventDefault()
    if (!q.trim()) return
    onAsk(q.trim())
    setQ('')
  }
  return (
    <div className="askbar">
      <form onSubmit={submit}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about alerts, cameras or the threat level" aria-label="Ask a quick question" />
        <span className="askbar-meta">{liveCount} camera{liveCount === 1 ? '' : 's'} live</span>
        <button type="submit" className="askbar-send" disabled={!q.trim()} aria-label="Ask"><Icons.dispatch /></button>
      </form>
    </div>
  )
}

/** Local time for the top bar. Ticks by itself so the rest of the app does not re-render every second. */
export function Clock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  return (
    <time className="appbar-clock" dateTime={now.toISOString()} title="Local time">
      <b>{now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}</b>
      <span>{now.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })}</span>
    </time>
  )
}

/** Avatar in the top bar: who is signed in, and the account-level pages. */
export function AccountMenu({ me, open, setOpen, items, onSignOut }) {
  return (
    <div className="account">
      <button type="button" className="avatar avatar-btn" aria-haspopup="menu" aria-expanded={open} aria-label="Account menu" onClick={() => setOpen(!open)}>
        {(me?.username || '…').slice(0, 2).toUpperCase()}
      </button>
      {open && (
        <>
          <button type="button" className="menu-scrim" aria-label="Close account menu" onClick={() => setOpen(false)} />
          <div className="account-menu" role="menu">
            <div className="account-who"><b>{me?.username || '…'}</b><span>{me?.role || ''}</span></div>
            {items.map((it) => (
              <button key={it.label} type="button" role="menuitem" className="menu-item" onClick={() => { setOpen(false); it.run() }}>
                <it.icon />{it.label}
              </button>
            ))}
            <button type="button" role="menuitem" className="menu-item" onClick={onSignOut}><Icons.logout />Sign out</button>
          </div>
        </>
      )}
    </div>
  )
}
