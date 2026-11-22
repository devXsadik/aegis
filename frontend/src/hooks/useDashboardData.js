import { useCallback, useEffect, useState } from 'react'
import {
  fetchAlerts, fetchAnalyticsLocations, fetchAnalyticsSummary, fetchAnalyticsTrends, fetchAuditLogs,
  fetchCameras, fetchEvidence, fetchIncidentReport, fetchKnownPersons, fetchMapCameras, fetchMapEvents,
  fetchReviewCount, fetchVehicleDetections, fetchVehiclePlates,
} from '../services/api'
import { can, canViewPage } from '../lib/permissions'
import { formatEvent } from '../lib/events'

/** The data pages share: loaded once at sign-in (only what this role may read: a 403 used to
    show "Some data could not be loaded"), refreshed when its page opens, and the review count
    every 15 s. `loadFailed` / `retry` drive the banner. */
export function useDashboardData({ authed, role, page, reloadTick }) {
  const [events, setEvents] = useState([])
  const [cameras, setCameras] = useState([])
  const [mapCameras, setMapCameras] = useState([])
  const [mapEvents, setMapEvents] = useState([])
  const [knownPersons, setKnownPersons] = useState([])
  const [evidence, setEvidence] = useState([])
  const [report, setReport] = useState(null)
  const [summary, setSummary] = useState(null)
  const [trends, setTrends] = useState([])
  const [locations, setLocations] = useState([])
  const [plates, setPlates] = useState([])
  const [vehicleDetections, setVehicleDetections] = useState([])
  const [auditLogs, setAuditLogs] = useState([])
  const [reviewPending, setReviewPending] = useState(0)
  const [escalation, setEscalation] = useState({ after: 0, types: [] })   // backup paging limit, for queue timers
  const [loadFailed, setLoadFailed] = useState([])                        // labels of preload requests that failed

  const ops = can(role, 'data.view')
  const sees = useCallback((...ids) => ids.some((id) => canViewPage(role, id)), [role])
  const reloadKnownPersons = useCallback(() => fetchKnownPersons().then(setKnownPersons).catch(() => {}), [])
  const reloadCameras = useCallback(() => { fetchCameras().then(setCameras).catch(() => {}) }, [])
  const reloadVehicles = useCallback(() => {
    fetchVehiclePlates().then(setPlates).catch(() => {})
    fetchVehicleDetections().then(setVehicleDetections).catch(() => {})
  }, [])

  useEffect(() => {
    if (!authed || !role || !ops) return
    const failed = new Set()
    const load = (label, promise, apply) => promise.then(apply).catch(() => {
      failed.add(label)
      setLoadFailed([...failed])
    })
    load('alerts', fetchAlerts(50), (alerts) => setEvents(alerts.map((a) => formatEvent(a))))
    load('cameras', fetchCameras(), setCameras)
    load('map cameras', fetchMapCameras(), setMapCameras)
    if (sees('evidence', 'faces')) load('evidence', fetchEvidence(60), setEvidence)
    load('summary', fetchAnalyticsSummary(24), setSummary)
    load('trends', fetchAnalyticsTrends(7), setTrends)
    load('locations', fetchAnalyticsLocations(24), setLocations)
    if (sees('map')) load('map events', fetchMapEvents(24), setMapEvents)
    if (sees('faces', 'watchlist')) load('persons', fetchKnownPersons(), setKnownPersons)
    if (sees('reports', 'analytics', 'incidents')) load('report', fetchIncidentReport(24), setReport)
    if (can(role, 'audit.view')) load('audit log', fetchAuditLogs(50), setAuditLogs)
    if (sees('vehicles')) reloadVehicles()
  }, [authed, role, ops, sees, reloadVehicles, reloadTick])

  useEffect(() => {
    if (!authed || !ops || !canViewPage(role, page)) return
    if (page === 'faces') fetchKnownPersons().then(setKnownPersons).catch(() => {})
    if (page === 'evidence' || page === 'faces') fetchEvidence(60).then(setEvidence).catch(() => {})
    if (page === 'map') {
      fetchMapCameras().then(setMapCameras).catch(() => {})
      fetchMapEvents(24).then(setMapEvents).catch(() => {})
    }
    if (page === 'analytics' || page === 'overview') {
      fetchAnalyticsSummary(24).then(setSummary).catch(() => {})
      fetchAnalyticsTrends(7).then(setTrends).catch(() => {})
      fetchAnalyticsLocations(24).then(setLocations).catch(() => {})
    }
    if (page === 'cameras') fetchCameras().then(setCameras).catch(() => {})
    if (page === 'vehicles') reloadVehicles()
    if (page === 'users' && can(role, 'audit.view')) fetchAuditLogs(50).then(setAuditLogs).catch(() => {})
    if (page === 'reports') fetchIncidentReport(24).then(setReport).catch(() => {})
  }, [authed, ops, role, page, reloadVehicles])

  const refreshReviewCount = useCallback(() => {
    fetchReviewCount().then((r) => {
      setReviewPending(r.pending || 0)
      setEscalation({ after: r.escalate_after_seconds ?? 0, types: r.escalated_types || [] })
    }).catch(() => {})
  }, [])
  useEffect(() => {
    if (!authed || !ops) return undefined
    refreshReviewCount()
    const t = setInterval(refreshReviewCount, 15000)
    return () => clearInterval(t)
  }, [authed, ops, refreshReviewCount])

  return {
    events, setEvents, cameras, mapCameras, mapEvents, knownPersons, evidence, report, summary, trends,
    locations, plates, vehicleDetections, auditLogs, reviewPending, escalation, loadFailed, setLoadFailed,
    reloadKnownPersons, reloadCameras, reloadVehicles, refreshReviewCount,
    profileFailed: () => setLoadFailed((f) => [...new Set([...f, 'profile'])]),
  }
}
