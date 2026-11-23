# Load-test plan — thousands of cameras

## What has to scale

| Flow | Rate at 5,000 cameras | Notes |
|---|---|---|
| Normalized events (AI cameras + our detectors) | 2,000–10,000 / s peak (0.4–2 per camera per second) | metadata + 10–30 KB crops |
| Frames pulled for video-only cameras | 5,000 × `sample_fps` (2–5) = 10–25k frames/s | stays on GPU workers, never on the bus |
| Watchlist matches | ~0.01–0.1 % of events | each raises alert + tracking + notifications |
| Dashboard / officer clients | 200 command-centre + 5,000 phones | WebSocket fan-out, push |
| Writes to Postgres | every event (detections, retention-bounded) | partition `detections` by day |

## Architecture under test

```
cameras ─► ingest API pods (stateless, N)  ─► Redis Streams `detections` (sharded by camera)
                                              └► matcher workers (scripts/worker.py, N, consumer group)
RTSP cameras ─► puller + GPU detector pods (per camera shard, sample_fps, priority boost on lookouts)
Postgres 16 + pgvector (HNSW for faces), `detections` partitioned daily, read replica for search
Object storage (MinIO / S3) for crops & evidence; MediaMTX relays near camera clusters
```

Set `INGEST_ASYNC=true` and `BUS_URL=redis://…` so the API only validates and queues.

## Tests

1. **Ingest baseline (single API pod, inline matching, SQLite dev box)** — establishes the per-event cost.
   `python scripts/simulate.py seed` then `python scripts/loadtest/ingest_bench.py --cameras 8 --rate 50 --seconds 60`.
2. **Ingest, queued** — 1, 2, 4 API pods behind the load balancer, 4 → 32 matcher workers;
   ramp 500 → 2,000 → 5,000 → 10,000 events/s (`--rate`), 15 min each. Watch `XLEN aegis:detections`
   (must stay flat), worker lag, API p95.
3. **Watchlist size** — 1k / 100k / 1M face vectors (pgvector HNSW `m=16, ef_search=64`) and 10k / 500k
   vehicle entries; match latency p95 per event.
4. **Hit storm** — `--plate-hit 0.01` (100× normal): alerts/s, incident attach rate, notification fan-out,
   escalation sweep time, WebSocket delivery delay to 200 dashboards (Locust users polling + sockets).
5. **Lookout churn** — 500 active tracks, sweep every 15 s: sweep duration must stay < 2 s.
6. **Soak** — 24 h at 60 % of max: memory of API / workers flat, retention purge keeps `detections`
   table size bounded, no growth in pool waits.
7. **Failure** — kill a worker (messages re-claimed via XAUTOCLAIM), restart Redis (API keeps 503-ing
   then recovers), Postgres fail-over (HA), camera flaps (offline alerts once per outage).

## Pass criteria

| Metric | Target |
|---|---|
| Ingest API p95 (queued mode) | < 50 ms |
| Event → alert on dashboard, p95 | < 2 s |
| Alert → officer notification, p95 | < 5 s (push), < 15 s (SMS) |
| Matcher lag (stream backlog) | < 5 s at sustained peak |
| Errors | < 0.1 % (no 5xx; 429 only above configured rate) |
| Face search (1M vectors) p95 | < 30 ms |

## Sizing guide (to be confirmed by the tests)

* Matcher worker: ~300–800 events/s each (CPU, no image work when cameras send attributes).
* GPU detector: one T4 ≈ 25–40 cameras at 4 fps (YOLOv8s 960 + plate + attributes, TensorRT FP16).
* Postgres: 8 vCPU / 32 GB handles ~5k inserts/s with daily partitions; search on a replica.

## Tools

* `scripts/loadtest/ingest_bench.py` — async event generator with latency percentiles (no extra deps).
* Locust (`pip install locust`) for mixed dashboard + officer traffic; one user class per role,
  WebSocket clients via `websocket-client`.
* Prometheus `/metrics` (already exposed) + Grafana: request latency, pool checkouts, stream length.
