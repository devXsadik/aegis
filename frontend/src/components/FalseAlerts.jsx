/* What operators' decisions say about the detectors: per camera and alert type, how often an
   alert was a false detection, why alerts were rejected, and what to change where it is noisy. */
import { useEffect, useState } from 'react'
import { Card, Empty, Icons, Seg } from './ui'
import { useToast } from './Toast'
import { fetchFalseAlerts, saveConfigThreshold } from '../services/api'
import { eventLabel, REJECT_REASONS } from '../lib/events'

const REASON = Object.fromEntries(REJECT_REASONS.map((r) => [r.value, r.label]))

export function FalseAlerts({ canTune }) {
  const { push: toast } = useToast()
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [applied, setApplied] = useState({})
  useEffect(() => { fetchFalseAlerts(days).then(setData).catch(() => setData({ groups: [] })) }, [days])

  const apply = async (s) => {
    try {
      await saveConfigThreshold(s.key, s.to)
      setApplied((a) => ({ ...a, [s.key]: s.to }))
      toast(`${s.key} set to ${s.to}. Cameras pick it up within 30 s.`, 'ok')
    } catch (e) {
      toast(e.message || 'Could not change the setting', 'danger')
    }
  }

  const groups = data?.groups || []
  return (
    <Card title="False alerts" sub="From operators' confirm / reject decisions"
      actions={<Seg value={days} onChange={setDays} options={[{ value: 7, label: '7 d' }, { value: 30, label: '30 d' }, { value: 90, label: '90 d' }]} />}>
      {data && groups.length === 0 && <Empty icon={Icons.check}>No reviewed alerts in this period yet.</Empty>}
      {groups.length > 0 && (
        <div className="table-wrap">
          <table className="table fa-table">
            <thead>
              <tr><th>Camera</th><th>Alert</th><th>Reviewed</th><th>False</th><th>Why rejected</th><th>What to do</th></tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={`${g.camera_id}-${g.alert_type}`}>
                  <td>{g.camera}</td>
                  <td>{eventLabel(g.alert_type)}</td>
                  <td>{g.reviewed}</td>
                  <td className={g.false_rate >= 0.5 && g.reviewed >= data.min_reviewed ? 'tone-danger' : ''}>{Math.round(g.false_rate * 100)}%</td>
                  <td className="meta">{Object.entries(g.reasons).map(([r, n]) => `${REASON[r] || r} ${n}`).join(' · ') || '—'}</td>
                  <td>
                    {g.suggestion ? (
                      <span className="fa-suggest">
                        <span>{g.suggestion.text}</span>
                        {canTune && g.suggestion.key && (
                          applied[g.suggestion.key] === g.suggestion.to
                            ? <span className="meta">Applied</span>
                            : <button type="button" className="btn btn-sm" onClick={() => apply(g.suggestion)}>Apply</button>
                        )}
                      </span>
                    ) : g.reviewed < (data.min_reviewed || 5) ? <span className="meta">Too few decisions yet</span> : <span className="meta">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
