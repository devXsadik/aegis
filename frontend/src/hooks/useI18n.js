import { useCallback, useSyncExternalStore } from 'react'
import { getLang, setLang, subscribeLang, translate } from '../lib/i18n'

/** `const { t, lang, setLang } = useI18n()` — re-renders when the language changes. */
export function useI18n() {
  const lang = useSyncExternalStore(subscribeLang, getLang, getLang)
  const t = useCallback((key, vars) => translate(lang, key, vars), [lang])
  return { t, lang, setLang }
}
