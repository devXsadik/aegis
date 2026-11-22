import { useEffect, useState } from 'react'
import { currentUser, fetchMe, login, refreshSession, signOut as apiSignOut } from '../services/api'

/** Who is signed in. The session is an httpOnly cookie, so start-up asks the server (authed is
    null until it answers); an expired session anywhere (auth_expired) returns to sign-in. */
export function useSession({ reloadTick, onProfileError }) {
  const [authed, setAuthed] = useState(null)
  const [me, setMe] = useState(null)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    currentUser().then((u) => { if (u) setMe(u); setAuthed(!!u) })
  }, [])

  useEffect(() => {
    const onAuthExpired = () => {
      setMe(null)
      setNotice('Your session expired. Please sign in again.')
      setAuthed(false)
    }
    window.addEventListener('auth_expired', onAuthExpired)
    return () => window.removeEventListener('auth_expired', onAuthExpired)
  }, [])

  // Keep the session alive while the dashboard is open (a wall display must not log itself out).
  useEffect(() => {
    if (!authed) return undefined
    refreshSession()
    const t = setInterval(refreshSession, 15 * 60 * 1000)
    const onVisible = () => { if (document.visibilityState === 'visible') refreshSession() }
    document.addEventListener('visibilitychange', onVisible)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onVisible) }
  }, [authed])

  useEffect(() => {
    if (!authed) return
    fetchMe().then(setMe).catch(() => onProfileError?.())
  }, [authed, reloadTick])  // eslint-disable-line react-hooks/exhaustive-deps

  return {
    authed, me, notice,
    signIn: async (u, p) => { await login(u, p); setNotice(''); setAuthed(true) },
    signOut: () => { apiSignOut(); setMe(null); setAuthed(false) },
  }
}
