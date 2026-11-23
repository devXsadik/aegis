/* UI text in English and Bangla. `t('key', { n: 3 })` looks up the current language, falls back to
   English, then to the key itself, so a missing translation shows English instead of breaking.
   Add a key to `en` first; `bn` may lag behind. */

const STORAGE_KEY = 'aegis.lang'
export const LANGS = [
  { id: 'en', label: 'English' },
  { id: 'bn', label: 'বাংলা' },
]

const en = {
  'common.save': 'Save changes',
  'common.saving': 'Saving…',
  'common.discard': 'Discard',
  'common.discarded': 'Changes discarded',
  'common.retry': 'Try again',
  'common.cancel': 'Cancel',
  'common.open': 'Open',
  'common.search': 'Search',
  'common.loading': 'Loading…',
  'common.unsaved': '{n} unsaved change(s)',
  'common.unsavedLeave': 'You have unsaved changes. Leave this section and discard them?',
  'common.unsavedTitle': 'Discard unsaved changes?',
  'common.comingIn': 'Arrives in {phase}',
  'common.error': 'Something went wrong',

  'severity.critical': 'Critical',
  'severity.high': 'High',
  'severity.medium': 'Medium',
  'severity.low': 'Low',
  'severity.info': 'Info',

  'status.open': 'Open',
  'status.new': 'New',
  'status.acknowledged': 'Acknowledged',
  'status.verified_match': 'Verified match',
  'status.officer_dispatched': 'Officer dispatched',
  'status.investigating': 'Investigating',
  'status.in_progress': 'In progress',
  'status.target_located': 'Target located',
  'status.resolved': 'Resolved',
  'status.closed': 'Closed',
  'status.false_alarm': 'False alarm',

  'settings.title': 'Settings',
  'settings.nav': 'Settings sections',
  'settings.profile': 'Profile',
  'settings.profile.desc': 'Your account, language and how the dashboard looks.',
  'settings.notifications': 'Notifications',
  'settings.notifications.desc': 'Alert sound, phone alerts and outside channels.',
  'settings.cameras': 'Cameras',
  'settings.cameras.desc': 'Camera registry, streams and health.',
  'settings.jurisdictions': 'Jurisdictions',
  'settings.jurisdictions.desc': 'Divisions, districts, thanas and which officers cover them.',
  'settings.watchlists': 'Watchlists',
  'settings.watchlists.desc': 'People and vehicles the system looks for.',
  'settings.thresholds': 'Detection thresholds',
  'settings.thresholds.desc': 'How sure the system must be before it raises an alert.',
  'settings.vehicles': 'Vehicle classes & models',
  'settings.vehicles.desc': 'Vehicle types, colours and make/model lists.',
  'settings.users': 'Users & roles',
  'settings.users.desc': 'Accounts and what each role may do.',
  'settings.security': 'Security',
  'settings.security.desc': 'Two-step sign-in and session safety.',
  'settings.retention': 'Data retention',
  'settings.retention.desc': 'How long recordings and detections are kept, and backups.',
  'settings.system': 'System',
  'settings.system.desc': 'AI models, storage and the API.',
  'settings.language': 'Language',
  'settings.theme': 'Theme',
  'settings.theme.dark': 'Dark',
  'settings.theme.light': 'Light',
  'settings.sound': 'Alert sound',
  'settings.sound.on': 'On',
  'settings.sound.muted': 'Muted',
  'settings.saved': 'Saved — cameras pick this up within about 30 seconds',
  'settings.savedSome': 'Saved {ok} of {n}. {fail}',
  'settings.readonly': 'Read-only — only an admin can change these',

  'incidents.title': 'Incidents',
  'incidents.sub': 'Opened automatically for critical and high alerts',
  'incidents.new': 'New incident',
  'incidents.empty': 'No incidents yet',
  'incidents.emptyMsg': 'One opens automatically for each critical alert.',
  'incidents.emptyFiltered': 'No incidents match',
  'incidents.emptyFilteredMsg': 'Try another status or clear the search.',
  'incidents.clearFilters': 'Clear filters',
  'incidents.loadError': 'Could not load incidents',
  'incidents.searchPh': 'Ticket, title, camera or person',
  'incidents.statusChanged': '{ticket} is now {status}',
  'incidents.assigned': '{ticket} assigned to {name}',
  'incidents.unassigned': '{ticket} is unassigned',
  'incidents.noteSaved': 'Note added to {ticket}',
  'incidents.created': 'Incident {ticket} created',

  'respond.empty': 'Nothing to respond to right now',
  'respond.emptyMsg': 'New alerts for your cameras appear here as they happen.',
  'respond.emptyDone': 'Nothing resolved in the last 24 hours',
  'respond.loadError': 'Could not load your alerts',
}

const bn = {
  'common.save': 'পরিবর্তন সংরক্ষণ',
  'common.saving': 'সংরক্ষণ হচ্ছে…',
  'common.discard': 'বাতিল',
  'common.discarded': 'পরিবর্তন বাতিল হয়েছে',
  'common.retry': 'আবার চেষ্টা করুন',
  'common.cancel': 'বাতিল',
  'common.open': 'খুলুন',
  'common.search': 'খুঁজুন',
  'common.loading': 'লোড হচ্ছে…',
  'common.unsaved': '{n}টি পরিবর্তন সংরক্ষণ হয়নি',
  'common.unsavedLeave': 'সংরক্ষণ না করা পরিবর্তন আছে। এই অংশ ছেড়ে সেগুলো বাতিল করবেন?',
  'common.unsavedTitle': 'পরিবর্তন বাতিল করবেন?',
  'common.comingIn': '{phase}-এ আসছে',
  'common.error': 'একটি সমস্যা হয়েছে',

  'severity.critical': 'জরুরি',
  'severity.high': 'উচ্চ',
  'severity.medium': 'মাঝারি',
  'severity.low': 'নিম্ন',
  'severity.info': 'তথ্য',

  'status.open': 'খোলা',
  'status.new': 'নতুন',
  'status.acknowledged': 'স্বীকৃত',
  'status.verified_match': 'মিল নিশ্চিত',
  'status.officer_dispatched': 'অফিসার প্রেরিত',
  'status.investigating': 'তদন্তাধীন',
  'status.in_progress': 'চলমান',
  'status.target_located': 'লক্ষ্য শনাক্ত',
  'status.resolved': 'সমাধান হয়েছে',
  'status.closed': 'বন্ধ',
  'status.false_alarm': 'ভুল সতর্কতা',

  'settings.title': 'সেটিংস',
  'settings.nav': 'সেটিংসের অংশসমূহ',
  'settings.profile': 'প্রোফাইল',
  'settings.profile.desc': 'আপনার অ্যাকাউন্ট, ভাষা ও ড্যাশবোর্ডের চেহারা।',
  'settings.notifications': 'বিজ্ঞপ্তি',
  'settings.notifications.desc': 'সতর্কতার শব্দ, ফোন সতর্কতা ও বাইরের চ্যানেল।',
  'settings.cameras': 'ক্যামেরা',
  'settings.cameras.desc': 'ক্যামেরার তালিকা, স্ট্রিম ও অবস্থা।',
  'settings.jurisdictions': 'এখতিয়ার',
  'settings.jurisdictions.desc': 'বিভাগ, জেলা, থানা ও দায়িত্বপ্রাপ্ত অফিসার।',
  'settings.watchlists': 'নজরতালিকা',
  'settings.watchlists.desc': 'যেসব ব্যক্তি ও যানবাহন খোঁজা হচ্ছে।',
  'settings.thresholds': 'শনাক্তকরণ সীমা',
  'settings.thresholds.desc': 'সতর্কতা দেওয়ার আগে সিস্টেমকে কতটা নিশ্চিত হতে হবে।',
  'settings.vehicles': 'যানবাহনের ধরন ও মডেল',
  'settings.vehicles.desc': 'যানবাহনের ধরন, রং ও নির্মাতা/মডেলের তালিকা।',
  'settings.users': 'ব্যবহারকারী ও ভূমিকা',
  'settings.users.desc': 'অ্যাকাউন্ট ও প্রতিটি ভূমিকার অনুমতি।',
  'settings.security': 'নিরাপত্তা',
  'settings.security.desc': 'দুই-ধাপ সাইন-ইন ও সেশনের নিরাপত্তা।',
  'settings.retention': 'তথ্য সংরক্ষণ',
  'settings.retention.desc': 'রেকর্ডিং ও শনাক্তকরণ কতদিন রাখা হবে, এবং ব্যাকআপ।',
  'settings.system': 'সিস্টেম',
  'settings.system.desc': 'এআই মডেল, স্টোরেজ ও এপিআই।',
  'settings.language': 'ভাষা',
  'settings.theme': 'থিম',
  'settings.theme.dark': 'গাঢ়',
  'settings.theme.light': 'হালকা',
  'settings.sound': 'সতর্কতার শব্দ',
  'settings.sound.on': 'চালু',
  'settings.sound.muted': 'বন্ধ',
  'settings.saved': 'সংরক্ষিত — প্রায় ৩০ সেকেন্ডের মধ্যে ক্যামেরায় কার্যকর হবে',
  'settings.savedSome': '{n}টির মধ্যে {ok}টি সংরক্ষিত। {fail}',
  'settings.readonly': 'শুধু দেখা যাবে — কেবল অ্যাডমিন পরিবর্তন করতে পারেন',

  'incidents.title': 'ঘটনা',
  'incidents.sub': 'জরুরি ও উচ্চ সতর্কতার জন্য স্বয়ংক্রিয়ভাবে খোলা হয়',
  'incidents.new': 'নতুন ঘটনা',
  'incidents.empty': 'এখনো কোনো ঘটনা নেই',
  'incidents.emptyMsg': 'প্রতিটি জরুরি সতর্কতায় স্বয়ংক্রিয়ভাবে একটি ঘটনা খোলে।',
  'incidents.emptyFiltered': 'মিলে যাওয়া কোনো ঘটনা নেই',
  'incidents.emptyFilteredMsg': 'অন্য অবস্থা বেছে নিন বা খোঁজ মুছে দিন।',
  'incidents.clearFilters': 'ফিল্টার মুছুন',
  'incidents.loadError': 'ঘটনাগুলো লোড করা যায়নি',
  'incidents.searchPh': 'টিকিট, শিরোনাম, ক্যামেরা বা ব্যক্তি',
  'incidents.statusChanged': '{ticket} এখন {status}',
  'incidents.assigned': '{ticket} দায়িত্ব পেলেন {name}',
  'incidents.unassigned': '{ticket} কারো দায়িত্বে নেই',
  'incidents.noteSaved': '{ticket}-এ নোট যোগ হয়েছে',
  'incidents.created': 'ঘটনা {ticket} তৈরি হয়েছে',

  'respond.empty': 'এই মুহূর্তে সাড়া দেওয়ার মতো কিছু নেই',
  'respond.emptyMsg': 'আপনার ক্যামেরার নতুন সতর্কতা এখানে সঙ্গে সঙ্গে দেখা যাবে।',
  'respond.emptyDone': 'গত ২৪ ঘণ্টায় কিছু সমাধান হয়নি',
  'respond.loadError': 'আপনার সতর্কতাগুলো লোড করা যায়নি',
}

export const DICTS = { en, bn }

function readStored() {
  try {
    const v = globalThis.localStorage?.getItem(STORAGE_KEY)
    return DICTS[v] ? v : 'en'
  } catch {
    return 'en'
  }
}

let current = readStored()
const listeners = new Set()

export const getLang = () => current

export function setLang(lang) {
  if (!DICTS[lang] || lang === current) return
  current = lang
  try { globalThis.localStorage?.setItem(STORAGE_KEY, lang) } catch { /* private mode */ }
  if (globalThis.document) document.documentElement.lang = lang
  listeners.forEach((fn) => fn())
}

export function subscribeLang(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

const BN_DIGITS = '০১২৩৪৫৬৭৮৯'
/** ASCII digits → Bangla digits (for numbers shown inside Bangla text). */
export const toBnDigits = (s) => String(s).replace(/[0-9]/g, (d) => BN_DIGITS[d])

export function translate(lang, key, vars) {
  let s = DICTS[lang]?.[key] ?? en[key] ?? key
  if (vars) {
    s = s.replace(/\{(\w+)\}/g, (m, name) => {
      if (!(name in vars)) return m
      const v = vars[name]
      return lang === 'bn' && typeof v === 'number' ? toBnDigits(v) : String(v)
    })
  }
  return s
}

export const t = (key, vars) => translate(current, key, vars)

if (globalThis.document) document.documentElement.lang = current
