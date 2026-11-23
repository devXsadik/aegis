/* Jurisdiction map for Settings: every area outlined (thanas filled), the selected one
   highlighted, and — while drawing — two clicks set a rectangle. Lazy-loaded with Leaflet. */
import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const TILE_URL = import.meta.env.VITE_MAP_TILES || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || '#888'
const WEIGHT = { division: 1, district: 2, thana: 2, beat: 1 }

export default function AreaMap({ areas, selectedId, drawing, onSelect, onRect }) {
  const host = useRef(null)
  const map = useRef(null)
  const layer = useRef(null)
  const first = useRef(null)
  const cb = useRef({ onSelect, onRect, drawing })
  useEffect(() => { cb.current = { onSelect, onRect, drawing } }, [onSelect, onRect, drawing])

  useEffect(() => {
    const m = L.map(host.current, { scrollWheelZoom: true }).setView([23.78, 90.40], 12)
    L.tileLayer(TILE_URL, { maxZoom: 19, attribution: '© OpenStreetMap contributors' }).addTo(m)
    layer.current = L.layerGroup().addTo(m)
    m.on('click', (e) => {
      if (!cb.current.drawing) return
      if (!first.current) {
        first.current = L.circleMarker(e.latlng, { radius: 5, color: css('--warn') }).addTo(m)
        return
      }
      const a = first.current.getLatLng()
      m.removeLayer(first.current)
      first.current = null
      const [s, n] = [Math.min(a.lat, e.latlng.lat), Math.max(a.lat, e.latlng.lat)]
      const [w, ea] = [Math.min(a.lng, e.latlng.lng), Math.max(a.lng, e.latlng.lng)]
      const r = (x) => Math.round(x * 1e5) / 1e5
      cb.current.onRect?.({ type: 'Polygon', coordinates: [[[r(w), r(s)], [r(ea), r(s)], [r(ea), r(n)], [r(w), r(n)], [r(w), r(s)]]] })
    })
    map.current = m
    return () => { m.remove(); map.current = null }
  }, [])

  useEffect(() => {
    const m = map.current
    if (!m) return
    layer.current.clearLayers()
    const shown = []
    areas.filter((a) => a.geojson).forEach((a) => {
      const sel = a.id === selectedId
      const g = L.geoJSON(a.geojson, {
        style: {
          color: sel ? css('--warn') : a.level === 'thana' || a.level === 'beat' ? css('--primary') : css('--text-3'),
          weight: sel ? 3 : WEIGHT[a.level] || 1, dashArray: a.level === 'division' ? '6 6' : null,
          fillOpacity: sel ? 0.18 : a.level === 'thana' || a.level === 'beat' ? 0.06 : 0,
        },
      })
      g.bindTooltip(`${a.name_en}${a.name_bn ? ` · ${a.name_bn}` : ''}`, { sticky: true })
      g.on('click', (e) => { if (!cb.current.drawing) { L.DomEvent.stopPropagation(e); cb.current.onSelect?.(a.id) } })
      g.addTo(layer.current)
      if (sel || a.level === 'thana') shown.push(g)
    })
    const sel = areas.find((a) => a.id === selectedId && a.geojson)
    if (sel) m.fitBounds(L.geoJSON(sel.geojson).getBounds().pad(0.4), { maxZoom: 15 })
    else if (shown.length) m.fitBounds(L.featureGroup(shown).getBounds().pad(0.1))
  }, [areas, selectedId])

  useEffect(() => {
    host.current?.classList.toggle('drawing', !!drawing)
  }, [drawing])

  return <div ref={host} className="area-map" role="img" aria-label="Map of jurisdictions" />
}
