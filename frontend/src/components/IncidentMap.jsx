/* Small map for one incident: the camera, its jurisdiction outline, and (Phase 9) the target's
   movement trail with direction arrows. Loaded lazily, so Leaflet stays out of the main bundle. */
import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const TILE_URL = import.meta.env.VITE_MAP_TILES || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'

export default function IncidentMap({ lat, lng, area, trail = [], label }) {
  const host = useRef(null)
  useEffect(() => {
    if (!host.current) return undefined
    const map = L.map(host.current, { zoomControl: true, attributionControl: true, scrollWheelZoom: false })
    L.tileLayer(TILE_URL, { maxZoom: 19, attribution: '© OpenStreetMap contributors' }).addTo(map)
    const layers = []
    if (area?.geojson) {
      const g = L.geoJSON(area.geojson, { style: { color: css('--primary'), weight: 2, fillOpacity: 0.08, dashArray: '4 4' } })
      g.addTo(map)
      layers.push(g)
    }
    const pts = trail.filter((p) => p.lat != null && p.lng != null).map((p) => [p.lat, p.lng])
    if (pts.length > 1) {
      const line = L.polyline(pts, { color: css('--danger'), weight: 3 }).addTo(map)
      layers.push(line)
      trail.forEach((p, i) => {
        if (p.lat == null) return
        L.circleMarker([p.lat, p.lng], { radius: 5, color: css('--danger'), fillOpacity: 1 })
          .bindTooltip(`${i + 1}. ${p.label || ''}${p.direction ? ` → ${p.direction}` : ''}`)
          .addTo(map)
      })
    }
    if (lat != null && lng != null) {
      const m = L.circleMarker([lat, lng], { radius: 9, color: '#fff', weight: 2, fillColor: css('--danger'), fillOpacity: 1 })
        .bindTooltip(label || 'Camera', { permanent: false })
        .addTo(map)
      layers.push(m)
    }
    const group = L.featureGroup(layers)
    if (layers.length) map.fitBounds(group.getBounds().pad(0.3), { maxZoom: 16 })
    else map.setView([23.8103, 90.4125], 12)
    const t = setTimeout(() => map.invalidateSize(), 120)   // drawer animates open
    return () => { clearTimeout(t); map.remove() }
  }, [lat, lng, area, trail, label])
  return <div ref={host} className="inc-map" role="img" aria-label={`Map: ${label || 'incident location'}`} />
}
