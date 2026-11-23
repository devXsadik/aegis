/* Dispatch ↔ field thread for one incident: messages and photos from the officer's phone camera.
   Live: an INCIDENT_MESSAGE on the incidents socket (ids only) triggers a re-fetch through the API. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Icons, timeAgo } from './ui'
import { EmptyState, ErrorState, SkeletonList } from './ds'
import { API_BASE, fetchIncidentMessages, sendIncidentMessage, uploadEvidenceFile } from '../services/api'
import { useWebSocket } from '../hooks/useWebSocket'
import { parseTs } from '../lib/time'
import { useI18n } from '../hooks/useI18n'

export function IncidentMessages({ incidentId, me, canWrite = true, compact = false }) {
  const { t } = useI18n()
  const [list, setList] = useState(null)
  const [error, setError] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(null)
  const [sendErr, setSendErr] = useState('')
  const endRef = useRef(null)
  const fileRef = useRef(null)

  const load = useCallback(() => {
    fetchIncidentMessages(incidentId).then((d) => { setList(d); setError('') })
      .catch((e) => setError(e.message || 'Could not load messages'))
  }, [incidentId])
  useEffect(() => { load() }, [load])
  useWebSocket('incidents', (msg) => {
    if (msg?.event_type === 'INCIDENT_MESSAGE' && msg.incident_id === incidentId) load()
  }, !!me)
  // Scroll the list itself to the newest message (scrollIntoView would also scroll the page / card sideways).
  useEffect(() => { const el = endRef.current?.parentElement; if (el) el.scrollTop = el.scrollHeight }, [list?.length])

  const send = async (e) => {
    e?.preventDefault()
    if (!text.trim() || busy) return
    setBusy(true); setSendErr('')
    try {
      await sendIncidentMessage(incidentId, { body: text.trim() })
      setText('')
      load()
    } catch (err) {
      setSendErr(err.message || 'Not sent')
    } finally {
      setBusy(false)
    }
  }

  const sendPhoto = async (file) => {
    if (!file) return
    setBusy(true); setSendErr(''); setProgress(0)
    try {
      const r = await uploadEvidenceFile(file, { incident_id: incidentId, description: `Photo from ${me?.username || 'the field'}` }, setProgress)
      await sendIncidentMessage(incidentId, { body: text.trim(), evidence_ref: r.ref })
      setText('')
      load()
    } catch (err) {
      setSendErr(err.message || 'Photo not sent')
    } finally {
      setBusy(false); setProgress(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className={`msg-thread ${compact ? 'compact' : ''}`}>
      {!list && !error && <SkeletonList rows={2} label="Loading messages" />}
      {error && <ErrorState compact message={error} onRetry={load} />}
      {list && list.length === 0 && (
        <EmptyState compact icon={Icons.incident} title={t('msg.emptyTitle')}>
          {t('msg.emptyMsg')}
        </EmptyState>
      )}
      {list && list.length > 0 && (
        <ol className="msg-list" aria-label="Messages" aria-live="polite">
          {list.map((m) => {
            const mine = m.author_id === me?.id
            return (
              <li key={m.id} className={`msg ${mine ? 'mine' : ''} ${m.from_field ? 'field' : 'dispatch'}`}>
                <div className="msg-meta">
                  <b>{mine ? t('msg.you') : m.author_name}</b>
                  <span className="muted">{m.from_field ? t('msg.field') : t('msg.dispatch')} · <time dateTime={m.created_at} title={parseTs(m.created_at)?.toLocaleString()}>{timeAgo(m.created_at)}</time></span>
                </div>
                {m.evidence_ref && (
                  <a className="msg-photo" href={`${API_BASE}/evidence-items/${encodeURIComponent(m.evidence_ref)}/file`} target="_blank" rel="noreferrer">
                    <img src={`${API_BASE}/evidence-items/${encodeURIComponent(m.evidence_ref)}/file`} alt={`Photo ${m.evidence_ref} from ${m.author_name}`} loading="lazy" />
                    <span className="mono">{m.evidence_ref}</span>
                  </a>
                )}
                {m.body && <p>{m.body}</p>}
              </li>
            )
          })}
          <li ref={endRef} aria-hidden="true" className="msg-end" />
        </ol>
      )}
      {canWrite && (
        <form className="msg-compose" onSubmit={send}>
          <label className="sr-only" htmlFor={`msg-${incidentId}`}>Message</label>
          <input id={`msg-${incidentId}`} className="input" value={text} maxLength={2000} disabled={busy}
            onChange={(e) => setText(e.target.value)} placeholder={me?.role === 'police' ? t('msg.phDispatch') : t('msg.phOfficers')} />
          <input ref={fileRef} type="file" accept="image/*" capture="environment" className="sr-only" id={`msg-photo-${incidentId}`}
            onChange={(e) => sendPhoto(e.target.files?.[0])} />
          <label htmlFor={`msg-photo-${incidentId}`} className={`btn icon-label ${busy ? 'disabled' : ''}`} title="Send a photo (saved as evidence)">
            <Icons.camera /> <span>{t('msg.photo')}</span>
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy || !text.trim()}>{busy && progress == null ? t('msg.sending') : t('msg.send')}</button>
        </form>
      )}
      {progress != null && <div className="msg-progress" role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${progress * 100}%` }} /></div>}
      {sendErr && <p className="msg-err" role="alert">{sendErr}</p>}
    </div>
  )
}
