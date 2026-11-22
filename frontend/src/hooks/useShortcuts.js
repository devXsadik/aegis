import { useEffect, useRef } from 'react'

/** ⌘K search, N notifications, C quick answers, Esc closes every overlay. Never while typing. */
export function useShortcuts(handlers) {
  const ref = useRef(handlers)
  useEffect(() => { ref.current = handlers })
  useEffect(() => {
    const onKey = (e) => {
      const t = e.target
      const typing = t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)
      const cmdK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k'
      if (typing && !cmdK && e.key !== 'Escape') return
      const h = ref.current
      if (cmdK) { e.preventDefault(); h.palette() }
      else if (e.key.toLowerCase() === 'n' && !e.metaKey && !e.ctrlKey) h.notifications()
      else if (e.key.toLowerCase() === 'c' && !e.metaKey && !e.ctrlKey) h.answers()
      else if (e.key === 'Escape') h.closeAll()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
