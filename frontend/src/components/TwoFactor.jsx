/* Two-factor sign-in for "My account": set up with a QR code, or turn off with password + code. */
import { useEffect, useState } from 'react'
import qrcode from 'qrcode-generator'
import { disableTwoFactor, enableTwoFactor, fetchTwoFactor, startTwoFactor } from '../services/api'

function Qr({ text }) {
  const qr = qrcode(0, 'M')
  qr.addData(text)
  qr.make()
  return <span className="tf-qr" dangerouslySetInnerHTML={{ __html: qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true }) }} />
}

export function TwoFactor() {
  const [state, setState] = useState(null)        // {enabled, recommended}
  const [setup, setSetup] = useState(null)        // {secret, otpauth_uri} while setting up
  const [off, setOff] = useState(false)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { fetchTwoFactor().then(setState).catch(() => {}) }, [])

  const run = async (fn) => {
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(e.message || 'Request failed') } finally { setBusy(false) }
  }
  const digits = code.replace(/\s/g, '')

  if (!state) return null
  return (
    <section className="tf">
      <div className="tf-head">
        <b>Two-factor sign-in</b>
        <span className={`tag ${state.enabled ? 'tag-ok' : state.recommended ? 'tag-warn' : 'tag-muted'}`}>{state.enabled ? 'On' : 'Off'}</span>
      </div>
      {!state.enabled && state.recommended && <p className="tf-rec">Recommended for admins and supervisors.</p>}
      <p className="meta">A 6-digit code from an app on your phone (Google Authenticator, Microsoft Authenticator, 1Password…)
        is needed at sign-in as well as the password, so a stolen password is not enough.</p>

      {!state.enabled && !setup && (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => run(async () => setSetup(await startTwoFactor()))}>Set up</button>
      )}
      {setup && (
        <div className="tf-setup">
          <Qr text={setup.otpauth_uri} />
          <div className="tf-steps">
            <ol>
              <li>In the app, add an account and scan this code.</li>
              <li>Can't scan? Enter this key: <code className="tf-key">{setup.secret.match(/.{1,4}/g).join(' ')}</code></li>
              <li>Type the 6-digit code the app shows:</li>
            </ol>
            <input className="input" value={code} onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, ''))} inputMode="numeric"
              autoComplete="one-time-code" maxLength={7} placeholder="123 456" aria-label="Code" />
            <button type="button" className="btn btn-primary btn-sm" disabled={busy || digits.length !== 6}
              onClick={() => run(async () => { await enableTwoFactor(digits); setSetup(null); setCode(''); setState({ ...state, enabled: true }) })}>
              Turn on
            </button>
          </div>
        </div>
      )}
      {state.enabled && !off && <button type="button" className="btn btn-sm" onClick={() => setOff(true)}>Turn off</button>}
      {state.enabled && off && (
        <div className="tf-off">
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" aria-label="Password" autoComplete="current-password" />
          <input className="input" value={code} onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, ''))} inputMode="numeric" maxLength={7} placeholder="Code" aria-label="Code" />
          <button type="button" className="btn btn-sm btn-danger" disabled={busy || !password || digits.length !== 6}
            onClick={() => run(async () => { await disableTwoFactor(password, digits); setOff(false); setCode(''); setPassword(''); setState({ ...state, enabled: false }) })}>
            Turn off
          </button>
        </div>
      )}
      {error && <div className="login-error" role="alert">{error}</div>}
    </section>
  )
}
