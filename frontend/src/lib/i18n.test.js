import { describe, expect, it } from 'vitest'
import { DICTS, toBnDigits, translate } from './i18n'

describe('i18n', () => {
  it('looks up the language, then English, then the key', () => {
    expect(translate('bn', 'settings.title')).toBe('সেটিংস')
    expect(translate('en', 'settings.title')).toBe('Settings')
    expect(translate('bn', 'no.such.key')).toBe('no.such.key')
  })

  it('fills {vars} and writes numbers in Bangla digits for bn', () => {
    expect(translate('en', 'common.unsaved', { n: 3 })).toBe('3 unsaved change(s)')
    expect(translate('bn', 'common.unsaved', { n: 12 })).toBe('১২টি পরিবর্তন সংরক্ষণ হয়নি')
    expect(translate('bn', 'incidents.created', { ticket: 'INC-0042' })).toContain('INC-0042')
  })

  it('leaves unknown placeholders alone', () => {
    expect(translate('en', 'common.comingIn', {})).toBe('Arrives in {phase}')
  })

  it('converts digits', () => {
    expect(toBnDigits('12-3456')).toBe('১২-৩৪৫৬')
  })

  it('every Bangla key exists in English', () => {
    const missing = Object.keys(DICTS.bn).filter((k) => !(k in DICTS.en))
    expect(missing).toEqual([])
  })
})
