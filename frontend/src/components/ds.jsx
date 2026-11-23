/* eslint-disable react-refresh/only-export-components */
/* Design-system pieces shared by every page: badges, skeletons, empty / error states,
   section headers and the sticky save bar. Styles live in styles/10-design.css. */
import { useEffect } from 'react'
import { Icons } from './ui'
import { EVENT_META } from '../lib/events'
import { useI18n } from '../hooks/useI18n'

const stroke = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round' }

export const DsIcons = {
  info: () => <svg viewBox="0 0 24 24" {...stroke}><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.5"/></svg>,
  error: () => <svg viewBox="0 0 24 24" {...stroke}><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5v.5"/></svg>,
  refresh: () => <svg viewBox="0 0 24 24" {...stroke}><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></svg>,
  x: () => <svg viewBox="0 0 24 24" {...stroke}><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/></svg>,
  dot: () => <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5" fill="currentColor"/></svg>,
  map: () => <svg viewBox="0 0 24 24" {...stroke}><path d="M9 4L3 6.5v13.5L9 17.5l6 2.5 6-2.5V4l-6 2.5L9 4z"/><path d="M9 4v13.5M15 6.5V20"/></svg>,
  lock: () => <svg viewBox="0 0 24 24" {...stroke}><rect x="4.5" y="10.5" width="15" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/></svg>,
  database: () => <svg viewBox="0 0 24 24" {...stroke}><ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-13M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/></svg>,
  sliders: () => <svg viewBox="0 0 24 24" {...stroke}><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></svg>,
  user: () => <svg viewBox="0 0 24 24" {...stroke}><circle cx="12" cy="8" r="4"/><path d="M4 21c1.3-4 4.3-6 8-6s6.7 2 8 6"/></svg>,
  cpu: () => <svg viewBox="0 0 24 24" {...stroke}><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/></svg>,
}

/* ——— Badges ——— */

/** Coloured label with an icon. tone ∈ ok | warn | danger | orange | info | muted | purple | cyan. */
export function Badge({ tone = 'muted', icon: Icon = DsIcons.dot, children, title, size = 'md' }) {
  return (
    <span className={`badge badge-${tone} badge-${size}`} title={title}>
      <Icon aria-hidden="true" />
      <span>{children}</span>
    </span>
  )
}

export const SEVERITY = {
  critical: { tone: 'danger', icon: Icons.alert },
  high: { tone: 'orange', icon: Icons.alert },
  medium: { tone: 'warn', icon: DsIcons.info },
  low: { tone: 'ok', icon: DsIcons.dot },
  info: { tone: 'info', icon: DsIcons.info },
}

export function SeverityBadge({ level, size }) {
  const { t } = useI18n()
  const s = SEVERITY[level] || { tone: 'muted', icon: DsIcons.dot }
  return <Badge tone={s.tone} icon={s.icon} size={size}>{t(`severity.${level}`)}</Badge>
}

/** Every incident status, current and the Phase 3 set, so old and new rows both render. */
export const STATUS = {
  open: { tone: 'danger', icon: DsIcons.dot },
  new: { tone: 'danger', icon: DsIcons.dot },
  acknowledged: { tone: 'info', icon: Icons.eye },
  verified_match: { tone: 'purple', icon: Icons.shield },
  officer_dispatched: { tone: 'cyan', icon: Icons.dispatch },
  investigating: { tone: 'warn', icon: Icons.search },
  in_progress: { tone: 'warn', icon: Icons.clock },
  target_located: { tone: 'orange', icon: Icons.map },
  resolved: { tone: 'ok', icon: Icons.check },
  closed: { tone: 'muted', icon: Icons.check },
  false_alarm: { tone: 'muted', icon: DsIcons.x },
}

export function StatusBadge({ status, size }) {
  const { t } = useI18n()
  const s = STATUS[status] || { tone: 'muted', icon: DsIcons.dot }
  return <Badge tone={s.tone} icon={s.icon} size={size}>{t(`status.${status}`)}</Badge>
}

const TYPE_TONE = { faces: 'purple', weapon: 'danger', vehicle: 'cyan', behavior: 'warn', fire: 'orange', fall: 'warn', camera: 'muted' }

/** Alert / incident type (CRIMINAL_DETECTED, SUSPICIOUS_VEHICLE, MANUAL…). */
export function AlertTypeBadge({ type, size }) {
  const meta = EVENT_META[type]
  if (!meta) {
    const label = (type || 'ALERT').replace(/_/g, ' ').toLowerCase()
    return <Badge tone="muted" icon={type === 'MANUAL' ? Icons.incident : DsIcons.dot} size={size}>{label[0].toUpperCase() + label.slice(1)}</Badge>
  }
  return <Badge tone={TYPE_TONE[meta.group] || 'muted'} icon={Icons[meta.icon] || DsIcons.dot} size={size}>{meta.label}</Badge>
}

/* ——— Loading ——— */

export function Skeleton({ w = '100%', h = 14, r, className = '' }) {
  return <span className={`skeleton ds-skel ${className}`} style={{ width: w, height: h, borderRadius: r }} aria-hidden="true" />
}

/** Placeholder rows shaped like a table / list while it loads. */
export function SkeletonList({ rows = 4, label }) {
  const { t } = useI18n()
  return (
    <div className="ds-skel-list" role="status" aria-label={label || t('common.loading')}>
      {Array.from({ length: rows }, (_, i) => (
        <div className="ds-skel-row" key={i}>
          <Skeleton w={44} h={44} r={10} />
          <div className="ds-skel-lines">
            <Skeleton w={`${55 + ((i * 17) % 30)}%`} h={13} />
            <Skeleton w={`${30 + ((i * 11) % 25)}%`} h={11} />
          </div>
          <Skeleton w={72} h={22} r={999} />
        </div>
      ))}
    </div>
  )
}

/* ——— Empty / error ——— */

/** Nothing to show: icon, short title, one helpful line and (optionally) the next action. */
export function EmptyState({ icon: Icon = Icons.search, title, children, action, compact = false }) {
  return (
    <div className={`ds-state ${compact ? 'compact' : ''}`}>
      <span className="ds-state-icon"><Icon aria-hidden="true" /></span>
      {title && <h3 className="ds-state-title">{title}</h3>}
      {children && <p className="ds-state-msg">{children}</p>}
      {action && <div className="ds-state-action">{action}</div>}
    </div>
  )
}

export function ErrorState({ title, message, onRetry, compact = false }) {
  const { t } = useI18n()
  return (
    <div className={`ds-state is-error ${compact ? 'compact' : ''}`} role="alert">
      <span className="ds-state-icon"><DsIcons.error aria-hidden="true" /></span>
      <h3 className="ds-state-title">{title || t('common.error')}</h3>
      {message && <p className="ds-state-msg">{message}</p>}
      {onRetry && (
        <div className="ds-state-action">
          <button type="button" className="btn btn-sm" onClick={onRetry}><DsIcons.refresh /> {t('common.retry')}</button>
        </div>
      )}
    </div>
  )
}

/* ——— Layout ——— */

/** Title + one line of description + actions on the right; used at the top of a settings section. */
export function SectionHeader({ icon: Icon, title, desc, actions, as: H = 'h2', id }) {
  return (
    <header className="ds-section-head">
      {Icon && <span className="ds-section-icon"><Icon aria-hidden="true" /></span>}
      <div className="ds-section-text">
        <H className="ds-section-title" id={id}>{title}</H>
        {desc && <p className="ds-section-desc">{desc}</p>}
      </div>
      {actions && <div className="ds-section-actions">{actions}</div>}
    </header>
  )
}

/** Label / control row inside a settings card. */
export function SettingRow({ label, hint, htmlFor, children }) {
  return (
    <div className="ds-setting">
      <div className="ds-setting-text">
        {htmlFor ? <label htmlFor={htmlFor}>{label}</label> : <span className="ds-setting-label">{label}</span>}
        {hint && <span className="ds-setting-hint">{hint}</span>}
      </div>
      <div className="ds-setting-control">{children}</div>
    </div>
  )
}

/** Stays at the bottom of the scroll area while there are unsaved edits. Warns on tab close. */
export function SaveBar({ count, busy, onSave, onDiscard }) {
  const { t } = useI18n()
  useEffect(() => {
    if (!count) return undefined
    const warn = (e) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [count])
  if (!count) return null
  return (
    <div className="ds-savebar" role="region" aria-label={t('common.unsaved', { n: count })}>
      <span className="ds-savebar-msg" aria-live="polite"><span className="ds-savebar-dot" />{t('common.unsaved', { n: count })}</span>
      <div className="ds-savebar-actions">
        <button type="button" className="btn btn-sm" onClick={onDiscard} disabled={busy}>{t('common.discard')}</button>
        <button type="button" className="btn btn-sm btn-primary" onClick={onSave} disabled={busy}>
          {busy ? t('common.saving') : t('common.save')}
        </button>
      </div>
    </div>
  )
}
