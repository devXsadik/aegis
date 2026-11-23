/* Every page of the dashboard, how pages are grouped, and how the URL maps to a page.
   Pure data plus routeFromHash(): shared by the shell, the sidebar and the search palette. */
import { Icons } from '../components/ui'
import { PAGE_VIEWS } from './permissions'

// Names are what an operator would call the page; `desc` is the one line shown under its title.
export const NAV = [
  {
    group: 'Monitor',
    pages: [
      { id: 'overview', label: 'Home', desc: 'What needs you right now, and how the system is doing.', icon: Icons.overview },
      { id: 'live', label: 'Live cameras', desc: 'Watch every camera as it happens.', icon: Icons.live },
      { id: 'map', label: 'Map', desc: 'Where your cameras are and where alerts came from.', icon: Icons.map },
      { id: 'command', label: 'Command map', desc: 'Targets on the move, lookouts, camera status and officers.', icon: Icons.dispatch },
    ],
  },
  {
    group: 'Respond',
    pages: [
      { id: 'alerts', label: 'Alerts', desc: 'Go through alerts one at a time and decide what happens next.', icon: Icons.alert },
      { id: 'respond', label: 'Responders', desc: 'Alerts to go to: directions, and on my way / on scene / resolved.', icon: Icons.dispatch },
      { id: 'incidents', label: 'Incidents', desc: 'Cases opened from alerts, and where each one stands.', icon: Icons.incident },
      { id: 'evidence', label: 'Evidence', desc: 'Snapshots and clips saved from detections.', icon: Icons.evidence },
      { id: 'shift', label: 'Shift log', desc: 'Notes during the shift, and the handover to the next one.', icon: Icons.clock },
    ],
  },
  {
    group: 'Investigate',
    pages: [
      { id: 'faces', label: 'People', desc: 'Who the system can recognise, and where watchlist people were seen.', icon: Icons.users },
      { id: 'vehicles', label: 'Vehicles', desc: 'Number plates read by the cameras.', icon: Icons.vehicle },
      { id: 'search', label: 'Vehicle search', desc: 'Find a vehicle by plate, type, colour or photo; start a lookout.', icon: Icons.search },
      { id: 'analytics', label: 'Analytics', desc: 'Trends over time, and everything the cameras detected.', icon: Icons.chart },
      { id: 'reports', label: 'Reports', desc: 'Summaries you can print or export.', icon: Icons.report },
    ],
  },
  {
    group: 'Set up',
    pages: [
      { id: 'cameras', label: 'Cameras', desc: 'Add cameras and check that each one is streaming.', icon: Icons.camera },
      { id: 'zones', label: 'Zones', desc: 'Draw the areas and lines each camera should watch.', icon: Icons.zone },
      { id: 'users', label: 'Users', desc: 'Who can sign in and what they are allowed to do.', icon: Icons.users },
      { id: 'settings', label: 'Settings', desc: 'Detection, notification and system options.', icon: Icons.settings },
    ],
  },
]
export const ALL_PAGES = NAV.flatMap((g) => g.pages)
// The pages used every shift: the phone's bottom tab bar (the sidebar has them all).
export const TAB_PAGES = ['overview', 'live', 'alerts', 'map'].map((id) => ALL_PAGES.find((p) => p.id === id))
// Officers on the move start from their responder list.
export const POLICE_TABS = ['respond', 'alerts', 'map', 'overview'].map((id) => ALL_PAGES.find((p) => p.id === id))
// Views inside a page (PAGE_VIEWS). An old link (#/watchlist, #/detection) opens its view.
export const VIEW_LABELS = { faces: 'Registry', watchlist: 'Watchlist sightings', analytics: 'Trends', detection: 'Detection history' }
// Views the search palette lists by their old names, so "watchlist" still finds them.
export const PALETTE_VIEWS = [
  { id: 'watchlist', label: 'Watchlist sightings', desc: 'Where watchlist people were seen (People page).', icon: Icons.watchlist },
  { id: 'detection', label: 'Detection history', desc: 'Everything the cameras detected (Analytics page).', icon: Icons.ai },
]
export const VIEW_HOME = Object.fromEntries(Object.entries(PAGE_VIEWS).flatMap(([home, views]) => views.map((v) => [v, home])))
export const THREAT = {
  low: { tone: 'ok', label: 'Threat level low' },
  high: { tone: 'warn', label: 'Threat level elevated' },
  critical: { tone: 'danger', label: 'Threat level critical' },
}

export function routeFromHash() {
  const [path, query = ''] = (window.location.hash || '#/overview').replace('#/', '').split('?')
  const view = new URLSearchParams(query).get('view') || (VIEW_HOME[path] ? path : null)
  const id = VIEW_HOME[path] || path
  return ALL_PAGES.some((p) => p.id === id) ? { page: id, view } : { page: 'overview', view: null }
}
