/* Aegis service worker: phone notifications for responders (backend/services/web_push.py).
   A push carries no data on purpose; on a push we ask our own API (with the signed-in
   session cookie) for this officer's alerts and show the newest one still to do. */
const API = '/api/v1/responder/alerts?hours=1'
const LABEL = {
  CRIMINAL_DETECTED: 'Watchlist match', WEAPON_DETECTED: 'Weapon', PERSON_TRACKED: 'Tracked subject',
  FALL_SUSPECTED: 'Possible fall', SUSPICIOUS_BEHAVIOR: 'Suspicious behaviour', FIRE_DETECTED: 'Fire or smoke',
}

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  event.waitUntil((async () => {
    let title = 'New alert'
    let body = 'Open Aegis to see it.'
    let tag = 'aegis-alert'
    try {
      const r = await fetch(API, { credentials: 'include', cache: 'no-store' })
      if (r.ok) {
        const a = (await r.json()).alerts.find((x) => x.status !== 'resolved')
        if (a) {
          const what = LABEL[a.type] || a.type.replace(/_/g, ' ').toLowerCase()
          title = `${what}${a.person_name && a.person_name !== 'Unknown' ? `: ${a.person_name}` : ''}`
          body = `${a.camera}${a.location && a.location !== a.camera ? ` · ${a.location}` : ''} · ${a.severity}`
          tag = `aegis-alert-${a.id}`
        }
      } else if (r.status === 401) {
        body = 'Sign in to Aegis to see it.'
      }
    } catch { /* offline: the generic notice still tells them to look */ }
    await self.registration.showNotification(title, {
      body, tag, renotify: true, requireInteraction: true, icon: '/logo-seal.svg', badge: '/favicon.svg',
      vibrate: [300, 120, 300, 120, 300], data: { url: '/#/respond' },
    })
  })())
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil((async () => {
    const url = event.notification.data?.url || '/#/respond'
    const open = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    const tab = open.find((c) => new URL(c.url).origin === self.location.origin)
    if (tab) { await tab.focus(); return tab.navigate(url) }
    return self.clients.openWindow(url)
  })())
})
