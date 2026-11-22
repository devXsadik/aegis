/* Phone notifications (Web Push) for responders: register public/sw.js and subscribe this browser. */
import { apiFetch } from '../services/api'

export const pushSupported = () =>
  typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  && window.isSecureContext

function keyBytes(b64) {
  const s = atob((b64 + '='.repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(s, (c) => c.charCodeAt(0))
}

async function registration() {
  return (await navigator.serviceWorker.getRegistration('/')) || navigator.serviceWorker.register('/sw.js')
}

/** This browser's subscription, or null. */
export async function currentSubscription() {
  if (!pushSupported()) return null
  const reg = await navigator.serviceWorker.getRegistration('/')
  return reg ? reg.pushManager.getSubscription() : null
}

export async function turnOnPush() {
  if ((await Notification.requestPermission()) !== 'granted') {
    throw new Error('Notifications are blocked for this site. Allow them in the browser settings, then try again.')
  }
  const { public_key: key } = await apiFetch('/responder/push')
  const reg = await registration()
  await navigator.serviceWorker.ready
  const sub = (await reg.pushManager.getSubscription())
    || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) })
  await apiFetch('/responder/push', { method: 'POST', body: JSON.stringify({ endpoint: sub.endpoint }) })
  return sub
}

export async function turnOffPush() {
  const sub = await currentSubscription()
  if (!sub) return
  await apiFetch('/responder/push', { method: 'DELETE', body: JSON.stringify({ endpoint: sub.endpoint }) }).catch(() => {})
  await sub.unsubscribe()
}
