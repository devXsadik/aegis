import { useState } from 'react'
import { Icons } from './ui'

// Demo button on the sign-in page, only when both values are set at build time: local dev reads
// frontend/.env.development.local (gitignored); Docker passes DEMO_LOGIN_* from .env. The password
// ends up in the bundle, so this is for demos, never for a deployment others can reach.
const DEMO_LOGIN = import.meta.env.VITE_DEMO_USERNAME && import.meta.env.VITE_DEMO_PASSWORD
  ? { username: import.meta.env.VITE_DEMO_USERNAME, password: import.meta.env.VITE_DEMO_PASSWORD }
  : null

export function LoginForm({ onLogin, theme, setTheme, notice }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(notice || '')
  const [loading, setLoading] = useState(false)
  const [needCode, setNeedCode] = useState(false)     // the account has two-factor sign-in on
  const [code, setCode] = useState('')

  const signIn = async (user, pass, otp) => {
    setLoading(true); setError('')
    try {
      await onLogin(user, pass, otp)
    } catch (err) {
      if (err.detail?.totp_required) {
        setNeedCode(true)
        setCode('')
        if (otp) setError(err.message)                  // a wrong code; a first ask needs no error
      } else {
        setError(err.message || 'Login failed')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    signIn(username, password, needCode ? code : undefined)
  }

  return (
    <div className="login-screen">
      <button
        type="button"
        className="icon-btn login-theme-btn"
        title="Toggle theme"
        aria-label="Toggle theme"
        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      >
        {theme === 'dark' ? <Icons.sun /> : <Icons.moon />}
      </button>
      <form className="login-card" onSubmit={handleSubmit}>
        <span className="brand-logo" aria-hidden="true">
          <img src="/logo.svg" alt="" width="46" height="46" />
        </span>
        <h1>Sign in to Aegis</h1>
        <p className="login-sub">Your cameras, alerts and evidence in one place.</p>
        {error && <div className="login-error" role="alert">{error}</div>}
        <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
        {needCode && (
          <label>Code from your authenticator app
            <input value={code} onChange={(e) => setCode(e.target.value.replace(/[^\d ]/g, ''))} inputMode="numeric"
              autoComplete="one-time-code" maxLength={7} placeholder="123 456" autoFocus required />
          </label>
        )}
        <button type="submit" className="btn btn-primary" disabled={loading || !username || !password || (needCode && code.replace(/\s/g, '').length !== 6)}>
          {loading ? 'Signing in…' : needCode ? 'Verify and sign in' : 'Sign in'}
        </button>
        {DEMO_LOGIN && (
          <button type="button" className="btn login-demo-btn" disabled={loading} onClick={() => signIn(DEMO_LOGIN.username, DEMO_LOGIN.password)}>Use the demo account</button>
        )}
      </form>
    </div>
  )
}
