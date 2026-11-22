/* Admin: building floor plans drawn under the cameras on the operations map. */
import { useState } from 'react'
import { Card, Icons, useConfirm } from './ui'
import { addFloorPlan, deleteFloorPlan, updateFloorPlan } from '../services/api'

/** A box in the middle of the current view, 40% of its width, with the image's proportions. */
function startBounds(view, w, h) {
  const b = view?.bounds?.()
  const c = b ? b.getCenter() : { lat: 23.8103, lng: 90.4125 }
  const spanLng = b ? (b.getEast() - b.getWest()) * 0.4 : 0.002
  const kx = Math.cos((c.lat * Math.PI) / 180)          // a degree of longitude is shorter away from the equator
  const spanLat = (spanLng * kx * h) / w
  return [[c.lat - spanLat / 2, c.lng - spanLng / 2], [c.lat + spanLat / 2, c.lng + spanLng / 2]]
    .map((p) => p.map((v) => Number(v.toFixed(7))))
}

const imageSize = (file) => new Promise((resolve) => {
  const img = new Image()
  img.onload = () => { resolve([img.naturalWidth, img.naturalHeight]); URL.revokeObjectURL(img.src) }
  img.onerror = () => resolve([4, 3])
  img.src = URL.createObjectURL(file)
})

export function FloorPlansCard({ plans, editId, setEditId, viewRef, reload, toast }) {
  const [ask, confirmDialog] = useConfirm()
  const [name, setName] = useState('')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [inputKey, setInputKey] = useState(0)     // remounts the file field to empty it

  const upload = async () => {
    setBusy(true)
    try {
      const [w, h] = await imageSize(file)
      const plan = await addFloorPlan(name.trim(), file, startBounds(viewRef.current, w, h))
      setName(''); setFile(null); setInputKey((k) => k + 1)
      await reload()
      setEditId(plan.id)
      toast('Floor plan added. Drag its corners onto the building, then Done.', 'ok')
    } catch (e) {
      toast(e.message || 'Could not add the floor plan', 'danger')
    } finally {
      setBusy(false)
    }
  }
  const change = async (p, changes) => {
    try { await updateFloorPlan(p.id, changes); reload() } catch (e) { toast(e.message || 'Could not save', 'danger') }
  }
  const remove = async (p) => {
    if (!(await ask({ title: 'Remove floor plan', message: `Remove "${p.name}" from the map?`, confirmLabel: 'Remove', danger: true }))) return
    try { await deleteFloorPlan(p.id); if (editId === p.id) setEditId(null); reload() } catch (e) { toast(e.message || 'Could not remove', 'danger') }
  }

  return (
    <Card title="Floor plans" sub="Building plans under the cameras (PNG or JPEG)">
      <div className="fp-list">
        {plans.map((p) => (
          <div key={p.id} className={`fp-row ${editId === p.id ? 'on' : ''}`}>
            <b>{p.name}</b>
            <label className="fp-opacity" title="See-through">
              <input type="range" min={0.1} max={1} step={0.05} defaultValue={p.opacity} aria-label={`${p.name} opacity`}
                onPointerUp={(e) => change(p, { opacity: Number(e.target.value) })} onKeyUp={(e) => change(p, { opacity: Number(e.target.value) })} />
            </label>
            <button type="button" className="btn btn-sm" onClick={() => setEditId(editId === p.id ? null : p.id)}>{editId === p.id ? 'Done' : 'Adjust'}</button>
            <button type="button" className="btn btn-sm btn-ghost" aria-label={`Remove ${p.name}`} onClick={() => remove(p)}><Icons.close /></button>
          </div>
        ))}
      </div>
      <div className="fp-add">
        <input className="input" placeholder="Name, e.g. HQ ground floor" aria-label="Floor plan name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
        <input key={inputKey} className="input" type="file" accept="image/png,image/jpeg" aria-label="Floor plan image" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        <button type="button" className="btn btn-sm btn-primary" disabled={busy || !file || !name.trim()} onClick={upload}>{busy ? 'Adding…' : 'Add to map'}</button>
      </div>
      {confirmDialog}
    </Card>
  )
}
