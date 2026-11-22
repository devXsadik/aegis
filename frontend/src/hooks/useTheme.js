import { useEffect, useState } from 'react'

function normalizeTheme(t) {
  return t === 'light' ? 'light' : 'dark'
}

function applyTheme(t) {
  const theme = normalizeTheme(t)
  document.documentElement.setAttribute('data-theme', theme)
  document.documentElement.style.colorScheme = theme
  try { localStorage.setItem('ai_sss_theme', theme) } catch { /* ignore */ }
  return theme
}

/** Dark or light, remembered on this device. */
export function useTheme() {
  const [theme, setThemeState] = useState(() => {
    try {
      return applyTheme(localStorage.getItem('ai_sss_theme') || 'dark')
    } catch {
      return applyTheme('dark')
    }
  })
  useEffect(() => { applyTheme(theme) }, [theme])
  return [theme, (t) => setThemeState(applyTheme(t))]
}
