import { useEffect, useState } from 'react'
import { Card, Tag } from '../components/ui'
import { fetchIntegrationStatus, testIntegration } from '../services/api'

function ThresholdSlider({ id, label, def, thresholds, onSet }) {
  return (
    <label className="field" style={{ marginBottom: 14 }}>
      <span>{label} — <b>{thresholds[id] ?? def}%</b></span>
      <input
        type="range" min="30" max="99" value={thresholds[id] ?? def}
        onChange={(e) => onSet(id, Number(e.target.value))}
      />
    </label>
  )
}

export function Settings({ ctx }) {
  const { theme, setTheme, systemStatus } = ctx
  const [thresholds, setThresholds] = useState(() => {
    try { return JSON.parse(localStorage.getItem('ai_sss_thresholds')) || {} } catch { return {} }
  })
  const [integrations, setIntegrations] = useState(null)
  const [testMsg, setTestMsg] = useState(null)

  useEffect(() => {
    fetchIntegrationStatus().then(setIntegrations).catch(() => {})
  }, [])

  const set = (key, val) => {
    const next = { ...thresholds, [key]: val }
    setThresholds(next)
    localStorage.setItem('ai_sss_thresholds', JSON.stringify(next))
  }

  const runTest = async (channel) => {
    setTestMsg(null)
    try {
      const r = await testIntegration(channel, `Ai-SSS test from ${channel}`)
      setTestMsg({ ok: true, text: `${channel}: HTTP ${r.http_status}` })
    } catch (e) {
      setTestMsg({ ok: false, text: e.message })
    }
  }

  const redis = systemStatus?.redis

  return (
    <div className="grid grid-2">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Card title="AI Detection Thresholds" sub="stored locally · pipeline reads config/models.yaml">
          <ThresholdSlider id="face" label="Face recognition confidence" def={60} thresholds={thresholds} onSet={set} />
          <ThresholdSlider id="weapon" label="Weapon detection confidence" def={55} thresholds={thresholds} onSet={set} />
          <ThresholdSlider id="behavior" label="Suspicious behavior score" def={50} thresholds={thresholds} onSet={set} />
          <ThresholdSlider id="plate" label="License plate OCR confidence" def={70} thresholds={thresholds} onSet={set} />
        </Card>

        <Card title="External Integrations" sub="CAD / SMS / radio / security webhooks">
          {integrations && (
            <>
              <div className="row">
                <span>ALERTS_ENABLED</span>
                <Tag tone={integrations.alerts_enabled ? 'ok' : 'warn'}>
                  {integrations.alerts_enabled ? 'true' : 'false'}
                </Tag>
              </div>
              {Object.entries(integrations.channels || {}).map(([name, ch]) => (
                <div className="row" key={name}>
                  <span>
                    {name}
                    {ch.url_host && <span className="meta muted"> · {ch.url_host}</span>}
                  </span>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <Tag tone={ch.configured ? 'ok' : 'muted'}>{ch.configured ? 'Configured' : 'Not set'}</Tag>
                    {ch.configured && (
                      <button className="btn btn-sm" onClick={() => runTest(name)}>Test</button>
                    )}
                  </div>
                </div>
              ))}
              {testMsg && (
                <div className={testMsg.ok ? 'tag tag-ok' : 'login-error'} style={{ marginTop: 8, padding: '8px 12px', display: 'block' }}>
                  {testMsg.text}
                </div>
              )}
              <p className="muted" style={{ fontSize: '0.74rem', marginTop: 10 }}>
                Set CAD_WEBHOOK, SMS_WEBHOOK, LAW_ENFORCEMENT_WEBHOOK in .env and ALERTS_ENABLED=true
              </p>
            </>
          )}
        </Card>

        <Card title="Alert Rules">
          <div className="row"><span>Auto-dispatch on criminal detection</span><Tag tone="ok">Enabled</Tag></div>
          <div className="row"><span>Auto-incident ticket creation</span><Tag tone="ok">Enabled</Tag></div>
          <div className="row"><span>GPS pinpoint push</span><Tag tone="ok">Enabled</Tag></div>
          <div className="row"><span>Heartbeat / camera SLA</span><Tag tone={systemStatus?.online ? 'ok' : 'warn'}>{systemStatus?.online ? 'Healthy' : 'No signal'}</Tag></div>
        </Card>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Card title="Appearance">
          <div className="row">
            <span>Theme</span>
            <div className="seg">
              <button className={theme === 'dark' ? 'on' : ''} onClick={() => setTheme('dark')}>Dark</button>
              <button className={theme === 'light' ? 'on' : ''} onClick={() => setTheme('light')}>Light</button>
            </div>
          </div>
        </Card>

        <Card title="High Availability">
          <div className="row">
            <span>Redis</span>
            <Tag tone={redis?.connected ? 'ok' : 'muted'}>
              {redis?.connected ? 'Connected' : redis?.enabled ? 'Configured (down)' : 'In-process'}
            </Tag>
          </div>
          <div className="row"><span>Offline cameras</span><Tag tone={(systemStatus?.offline_cameras || 0) ? 'warn' : 'ok'}>{systemStatus?.offline_cameras ?? 0}</Tag></div>
          <div className="row"><span>Mode</span><span className="mono muted">{redis?.mode || 'in-process'}</span></div>
          <p className="muted" style={{ fontSize: '0.74rem', marginTop: 8 }}>
            docker compose up redis — set REDIS_URL=redis://localhost:6379/0
          </p>
        </Card>

        <Card title="API & Storage">
          <dl className="kv">
            <dt>REST</dt><dd className="mono">/api/v1</dd>
            <dt>Docs</dt><dd><a href="/docs" target="_blank" rel="noreferrer" style={{ color: 'var(--primary)' }}>/docs</a></dd>
            <dt>Evidence</dt><dd>PostgreSQL + SHA-256 custody</dd>
            <dt>Recordings</dt><dd className="mono">data/recordings/</dd>
          </dl>
        </Card>

        <Card title="Keyboard Shortcuts">
          <div className="row"><span>Command palette</span><span className="mono">⌘K / Ctrl+K</span></div>
          <div className="row"><span>Notifications</span><span className="mono">N</span></div>
          <div className="row"><span>AI Copilot</span><span className="mono">C</span></div>
        </Card>
      </div>
    </div>
  )
}
