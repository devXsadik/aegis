import { useEffect, useRef } from 'react'

/** Signs out after `minutes` without keyboard / mouse / touch (command-centre and shared
    devices). VITE_IDLE_MINUTES sets it at build time; 0 turns it off. The server's token
    lifetime (ACCESS_TOKEN_EXPIRE_MINUTES) still applies on top. Only user input counts:
    live updates re-render the page constantly and must not keep a session alive. */
export function useIdleLogout(enabled, onIdle, minutes = Number(import.meta.env.VITE_IDLE_MINUTES ?? 30)) {
  const idle = useRef(onIdle)
  useEffect(() => { idle.current = onIdle }, [onIdle])
  useEffect(() => {
    if (!enabled || !minutes) return undefined
    let timer
    const reset = () => {
      clearTimeout(timer)
      timer = setTimeout(() => idle.current?.(), minutes * 60 * 1000)
    }
    const events = ['pointerdown', 'keydown', 'wheel', 'touchstart']
    events.forEach((e) => window.addEventListener(e, reset, { passive: true }))
    reset()
    return () => { clearTimeout(timer); events.forEach((e) => window.removeEventListener(e, reset)) }
  }, [enabled, minutes])
}
