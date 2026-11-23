/* Status picker: a button showing the current status, opening a listbox of the statuses allowed
   next (coloured icon, label, one-line description). Closing / false alarm / re-opening ask for a
   confirmation with a required note. The server checks every rule again. */
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Modal } from './ui'
import { STATUS, StatusBadge, DsIcons } from './ds'
import { nextOptions, normalizeStatus, statusMeta } from '../lib/incidentStatus'
import { useI18n } from '../hooks/useI18n'

function NoteDialog({ option, onCancel, onConfirm }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const id = useId()
  const ok = !option.needsNote || note.trim().length >= 3
  const submit = async () => {
    if (!ok) return
    setBusy(true)
    try { await onConfirm(note.trim()) } finally { setBusy(false) }
  }
  return (
    <Modal title={`Change status to “${option.label}”?`} onClose={onCancel}
      footer={(
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
          <button type="button" className={`btn ${['false_alarm', 'closed'].includes(option.id) ? 'btn-danger' : 'btn-primary'}`}
            disabled={!ok || busy} onClick={submit}>{busy ? 'Saving…' : `Mark ${option.label.toLowerCase()}`}</button>
        </div>
      )}>
      <p style={{ marginTop: 0 }}>{option.desc}</p>
      <label className="field" htmlFor={id}>
        {option.needsNote ? 'Note (required)' : 'Note (optional)'}
        <textarea id={id} className="input" rows={3} value={note} maxLength={2000}
          onChange={(e) => setNote(e.target.value)} aria-required={option.needsNote}
          placeholder={option.id === 'false_alarm' ? 'Why is this not a real match / event?' : 'What happened, and who decided?'} />
      </label>
      <p className="ds-setting-hint" style={{ marginBottom: 0 }}>Saved to the incident timeline and the audit log.</p>
    </Modal>
  )
}

export function StatusSelector({ spec, value, role, disabled, onChange, size = 'md', label }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [pending, setPending] = useState(null)
  const [pos, setPos] = useState(null)
  const btn = useRef(null)
  const list = useRef(null)
  const listId = useId()
  const options = nextOptions(spec, value, role)
  const current = normalizeStatus(value)
  const canOpen = !disabled && options.length > 0

  useLayoutEffect(() => {
    if (!open || !btn.current) return
    const r = btn.current.getBoundingClientRect()
    const h = Math.min(420, options.length * 62 + 12)
    const below = window.innerHeight - r.bottom > h + 8
    setPos({ left: Math.min(r.left, window.innerWidth - 336), top: below ? r.bottom + 6 : Math.max(8, r.top - h - 6) })
  }, [open, options.length])

  useEffect(() => {
    if (!open) return undefined
    list.current?.focus({ preventScroll: true })
    const away = (e) => { if (!list.current?.contains(e.target) && !btn.current?.contains(e.target)) setOpen(false) }
    // The list is fixed to where the button was: close if the page behind it scrolls.
    // Layout settling can fire scroll events without anything moving: compare positions.
    const start = btn.current?.getBoundingClientRect()
    const close = () => {
      const now = btn.current?.getBoundingClientRect()
      if (!start || !now || Math.abs(now.top - start.top) > 2 || Math.abs(now.left - start.left) > 2) setOpen(false)
    }
    document.addEventListener('pointerdown', away)
    window.addEventListener('scroll', close, true)
    const onResize = () => setOpen(false)
    window.addEventListener('resize', onResize)
    return () => {
      document.removeEventListener('pointerdown', away)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', onResize)
    }
  }, [open])

  const choose = (opt) => {
    setOpen(false)
    btn.current?.focus()
    if (opt.needsConfirm || opt.needsNote) setPending(opt)
    else onChange(opt.id, null)
  }

  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => (i + 1) % options.length) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => (i - 1 + options.length) % options.length) }
    else if (e.key === 'Home') { e.preventDefault(); setActive(0) }
    else if (e.key === 'End') { e.preventDefault(); setActive(options.length - 1) }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(options[active]) }
    else if (e.key === 'Escape' || e.key === 'Tab') { setOpen(false); btn.current?.focus() }
  }

  const meta = statusMeta(spec, current)
  return (
    <>
      <button ref={btn} type="button" className={`status-trigger status-${size}`} disabled={!canOpen}
        aria-haspopup="listbox" aria-expanded={open} aria-controls={open ? listId : undefined}
        aria-label={`${label || 'Status'}: ${meta.label}${canOpen ? '. Change status' : ''}`}
        title={canOpen ? meta.desc : (disabled ? meta.desc : 'No further status changes for your role')}
        onClick={() => { setActive(0); setOpen((o) => !o) }}
        onKeyDown={(e) => { if (e.key === 'ArrowDown' && canOpen) { e.preventDefault(); setActive(0); setOpen(true) } }}>
        <StatusBadge status={current} size={size === 'sm' ? 'sm' : 'md'} />
        {canOpen && <svg className="status-chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>}
      </button>
      {open && pos && createPortal(
        <ul ref={list} id={listId} role="listbox" tabIndex={-1} className="status-pop" aria-label="Next status"
          aria-activedescendant={`${listId}-${active}`} onKeyDown={onKey} style={{ left: pos.left, top: pos.top }}>
          {options.map((o, i) => {
            const Icon = STATUS[o.id]?.icon || DsIcons.dot
            return (
              <li key={o.id} id={`${listId}-${i}`} role="option" aria-selected={i === active}
                className={`status-opt tone-${STATUS[o.id]?.tone || 'muted'} ${i === active ? 'active' : ''}`}
                onPointerEnter={() => setActive(i)} onClick={() => choose(o)}>
                <span className="status-opt-icon"><Icon aria-hidden="true" /></span>
                <span className="status-opt-text">
                  <b>{t(`status.${o.id}`)}{o.needsNote && <span className="status-opt-req"> · note required</span>}</b>
                  <span>{o.desc}</span>
                </span>
              </li>
            )
          })}
        </ul>, document.body)}
      {pending && createPortal(
        <div className="layer-top">
          <NoteDialog option={pending} onCancel={() => setPending(null)}
            onConfirm={async (note) => { await onChange(pending.id, note); setPending(null) }} />
        </div>, document.body)}
    </>
  )
}
