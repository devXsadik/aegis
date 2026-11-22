/* The one place every page is listed: grouped, always the same shape, collapsible to icons.
   Set-up pages sit in a folded group at the bottom so daily work stays in front. */
import { Icons } from './ui'

export function Sidebar({ groups, page, setPage, badges = {}, alerting, collapsed, onToggleCollapsed, setupOpen, onToggleSetup }) {
  const item = (p) => {
    const n = badges[p.id] || 0
    return (
      <button
        key={p.id} type="button"
        className={`nav-item ${page === p.id ? 'active' : ''}`}
        aria-current={page === p.id ? 'page' : undefined}
        data-alert-nav={alerting && p.id === 'alerts' ? 'true' : undefined}
        title={collapsed ? `${p.label}${n ? ` (${n})` : ''}` : p.desc}
        onClick={() => setPage(p.id)}
      >
        <p.icon />
        <span className="nav-label">{p.label}</span>
        {n > 0 && <span className="nav-badge" aria-label={`${n} need action`}>{n}</span>}
      </button>
    )
  }

  return (
    <aside className={`sidenav ${collapsed ? 'collapsed' : ''}`} aria-label="Main navigation">
      <div className="sidenav-brand">
        <span className="brand-logo" aria-hidden="true"><img src="/logo.svg" alt="" width="32" height="32" /></span>
        <span className="nav-label">Aegis<small>Surveillance operations</small></span>
      </div>

      <nav className="sidenav-groups">
        {groups.map((g) => {
          const setup = g.group === 'Set up'
          const open = !setup || setupOpen || collapsed || g.pages.some((p) => p.id === page)
          return (
            <div className="nav-group" key={g.group}>
              {setup ? (
                <button type="button" className="nav-group-label nav-group-toggle" aria-expanded={open} onClick={onToggleSetup}>
                  <span className="nav-label">{g.group}</span>
                  <span className={`nav-chevron ${open ? 'open' : ''}`} aria-hidden="true">›</span>
                </button>
              ) : (
                <div className="nav-group-label"><span className="nav-label">{g.group}</span></div>
              )}
              {open && g.pages.map(item)}
            </div>
          )
        })}
      </nav>

      <button type="button" className="nav-item sidenav-collapse" onClick={onToggleCollapsed}
        aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'} title={collapsed ? 'Expand navigation' : 'Collapse navigation'}>
        <Icons.panel />
        <span className="nav-label">Collapse</span>
      </button>
    </aside>
  )
}
