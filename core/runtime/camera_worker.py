"""Per-camera surveillance loop for single- and multi-camera operation."""

import copy
import os
import time
import logging
import threading
from typing import Callable, Optional

import cv2

from core.analysis.tamper import MESSAGES as TAMPER_MESSAGES
from core.analysis.zones import QUADRANT_ZONES
from core.runtime.runtime_config import RuntimeConfigSync
from core.visualization.hud import render_full_hud
from core.visualization.stream_overlay import StreamOverlay
from utils.media import open_capture, read_frame_with_reconnect, ContinuousRecorder
from utils.alerts import dispatch_alert, publish_event_clip, publish_frame, publish_heartbeat
from utils.system import FrameSkipper, ResourceMonitor
from paths import RECORDINGS_DIR

logger = logging.getLogger("HumanAnalysis")
DEFAULT_ZONE_NAMES = {z["name"] for z in QUADRANT_ZONES}      # used when a camera has no drawn zones


class _Failures:
    """Counts a recurring failure and logs the first one, then every `every`-th: a recording or
    stream that keeps failing must show up in the log without flooding it."""

    def __init__(self, camera_id: str, what: str, every: int = 200):
        self.camera_id, self.what, self.every, self.count = camera_id, what, every, 0

    def __call__(self, exc: Exception) -> None:
        self.count += 1
        if self.count == 1 or self.count % self.every == 0:
            logger.error(f"[{self.camera_id}] {self.what} failed ({self.count}x so far): {exc}")


def thermal_view(frame):
    return cv2.applyColorMap(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLORMAP_INFERNO)


def _register_dvr_segment(meta: dict) -> None:
    """Index a closed continuous segment in the backend VMS DB."""
    def _send():
        try:
            import httpx
            from utils.alerts.event_publisher import BACKEND_URL, INTERNAL_API_KEY

            # Prefer path relative-friendly absolute for server
            payload = {
                "camera_id": meta["camera_id"],
                "camera_location": meta.get("camera_location") or "",
                "started_at": meta["started_at"],
                "ended_at": meta.get("ended_at"),
                "duration_seconds": meta.get("duration_seconds"),
                "trigger": "continuous",
                "file_path": meta["file_path"],
                "file_sha256": meta.get("file_sha256"),
                "frame_count": meta.get("frame_count"),
                "thumbnail_path": meta.get("thumbnail_path"),
            }
            httpx.post(
                f"{BACKEND_URL}/api/v1/vms/segments",
                json=payload,
                headers={"X-Internal-Key": INTERNAL_API_KEY, "Content-Type": "application/json"},
                timeout=10.0,
            )
        except Exception as e:
            logger.warning("DVR segment register failed: %s", e)

    threading.Thread(target=_send, daemon=True).start()


class InferenceWorker(threading.Thread):
    """Runs the (slow) AI pipeline off the video path.

    The camera loop keeps reading, recording and streaming at full frame rate and just
    hands this worker the newest frame whenever it is free (older frames are dropped, so
    latency never builds up). A frame that makes a stage raise is skipped instead of
    taking the whole camera down; `max_consecutive_errors` failures in a row mark the
    worker failed so the caller can rebuild the camera.
    """

    def __init__(self, pipeline, config_sync, run_kwargs: dict, camera_id: str,
                 max_consecutive_errors: int = 20):
        super().__init__(name=f"infer-{camera_id}", daemon=True)
        self.pipeline = pipeline
        self.config_sync = config_sync
        self.run_kwargs = run_kwargs
        self.camera_id = camera_id
        self.max_consecutive_errors = max_consecutive_errors
        self.failed = False
        self._cond = threading.Condition()
        self._pending = None
        self._halt = False
        self._result = None
        self.result_seq = 0
        self.last_infer_seconds = 0.0
        self._busy_since = None          # monotonic start of the inference running now
        self._last_done = time.monotonic()

    def stalled_for(self) -> float:
        """Seconds the current inference has been running (0 when idle)."""
        busy = self._busy_since
        return time.monotonic() - busy if busy is not None else 0.0

    def result_age(self) -> float:
        """Seconds since the last finished inference (or since start)."""
        return time.monotonic() - self._last_done

    def submit(self, frame) -> None:
        with self._cond:
            self._pending = frame
            self._cond.notify()

    def latest(self):
        """(ctx, seq) of the most recent finished inference, or (None, 0)."""
        return self._result, self.result_seq

    def stop(self) -> None:
        with self._cond:
            self._halt = True
            self._cond.notify()

    def run(self) -> None:
        errors = 0
        while True:
            with self._cond:
                while self._pending is None and not self._halt:
                    self._cond.wait(timeout=1.0)
                if self._halt:
                    return
                frame, self._pending = self._pending, None
            started = time.time()
            self._busy_since = time.monotonic()
            try:
                self.config_sync.maybe_sync()
                ctx = self.pipeline.run(frame, **self.run_kwargs)
            except Exception as e:  # noqa: BLE001
                self._busy_since = None
                errors += 1
                logger.exception(f"[{self.camera_id}] inference failed ({errors}/{self.max_consecutive_errors}): {e}")
                if errors >= self.max_consecutive_errors:
                    self.failed = True
                    return
                continue
            errors = 0
            self._busy_since = None
            self._last_done = time.monotonic()
            self.last_infer_seconds = time.time() - started
            self._result = ctx
            self.result_seq += 1


def run_camera_loop(
    pipeline,
    criminal_names,
    source,
    camera_id: str,
    camera_location: str,
    target_fps: int = 30,
    show_window: bool = True,
    window_title: Optional[str] = None,
    camera_name: str = "",
    camera_lat: Optional[float] = None,
    camera_lng: Optional[float] = None,
    stop_event: Optional[threading.Event] = None,
    on_stall: Optional[Callable[[], None]] = None,
    tamper=None,
):
    """Run the CV pipeline on one video source until quit or stream end.

    If one inference runs longer than INFERENCE_STALL_SECONDS (a hung model or face worker),
    the loop stops and calls `on_stall`. The stuck thread cannot be killed and may hold the
    shared model lock, so the caller restarts the whole pipeline process."""
    cap = open_capture(source)
    frame_skipper = FrameSkipper(target_fps=target_fps)
    config_sync = RuntimeConfigSync(pipeline, camera_id=camera_id)
    resource_monitor = ResourceMonitor()
    perf_enabled = os.getenv("PERF_MONITOR", "false").lower() == "true"

    start_time = time.time()
    thermal_mode = False
    last_heartbeat = 0.0
    sent_flags = []
    heartbeat_interval = float(os.getenv("HEARTBEAT_INTERVAL", "5"))
    stall_limit = float(os.getenv("INFERENCE_STALL_SECONDS", "120"))
    last_stream = 0.0
    stream_interval = 1.0 / float(os.getenv("STREAM_FPS", "5"))
    stream_width = int(os.getenv("STREAM_WIDTH", "1280"))
    stream_quality = int(os.getenv("STREAM_QUALITY", "80"))
    # "clean": people marked, nothing else (dashboard default). "full": the whole HUD in the stream.
    overlay = StreamOverlay() if os.getenv("STREAM_HUD", "clean").lower() != "full" else None
    fps_counter = 0
    fps_window_start = time.time()
    current_fps = 0.0

    dvr_enabled = os.getenv("DVR_ENABLED", "true").lower() == "true"
    dvr = None
    if dvr_enabled:
        dvr = ContinuousRecorder(
            camera_id=camera_id,
            out_dir=RECORDINGS_DIR / camera_id / "continuous",
            segment_seconds=float(os.getenv("DVR_SEGMENT_SECONDS", "60")),
            target_fps=float(os.getenv("DVR_FPS", "8")),
            width=int(os.getenv("DVR_WIDTH", "960")),
            camera_location=camera_location,
            on_segment=_register_dvr_segment,
        )
        logger.info(
            "DVR continuous recording ON for %s (segment=%ss)",
            camera_id, os.getenv("DVR_SEGMENT_SECONDS", "60"),
        )

    title = window_title or f"AI-SSS — {camera_location or camera_id}"
    logger.info(f"Camera worker started: {camera_id} @ {camera_location}")

    worker = InferenceWorker(
        pipeline, config_sync, camera_id=camera_id,
        run_kwargs=dict(camera_id=camera_id, camera_location=camera_location,
                        camera_name=camera_name, camera_lat=camera_lat, camera_lng=camera_lng),
    )
    worker.start()
    ctx = None
    clip_seq = 0
    dvr_failed = _Failures(camera_id, "DVR recording")
    stream_failed = _Failures(camera_id, "Publishing the live stream")
    try:
        while True:
            if stop_event and stop_event.is_set():
                break
            if worker.failed or not worker.is_alive():
                logger.error(f"Inference worker for {camera_id} failed; restarting camera")
                break
            if worker.stalled_for() > stall_limit:
                logger.error(f"[{camera_id}] inference stuck for {worker.stalled_for():.0f}s; restarting the pipeline")
                if on_stall:
                    on_stall()
                break
            cap, frame = read_frame_with_reconnect(cap, source)
            if frame is None:
                logger.error(f"Stream lost for {camera_id}")
                break

            if frame_skipper.should_process():
                worker.submit(thermal_view(frame) if thermal_mode else frame.copy())   # HUD draws in place

            # Overlay the latest AI result on the *current* frame (boxes trail by one
            # inference, the video itself never does).
            result, result_seq = worker.latest()
            if result is not None:
                ctx = copy.copy(result)
                ctx.frame = frame
                ctx.timestamp = time.time()

            # Covered / blurred / moved / frozen camera: checked on the raw picture once a second.
            if tamper is not None:
                people = [b for b, _, _ in (result.human_detections if result is not None else [])]
                kind = tamper.check(frame, time.time(), people)
                if kind:
                    logger.warning(f"[{camera_id}] camera tamper: {kind}")
                    dispatch_alert(
                        alert_type="CAMERA_TAMPER", severity="high",
                        camera_id=camera_id, camera_location=camera_location, camera_name=camera_name,
                        camera_lat=camera_lat, camera_lng=camera_lng,
                        message=f"{TAMPER_MESSAGES[kind]} — {camera_name or camera_location or camera_id}",
                    )

            # Continuous DVR writes raw (pre-HUD) frames for forensic fidelity
            if dvr is not None:
                try:
                    dvr.write(frame)
                except Exception as e:
                    dvr_failed(e)

            fps_counter += 1
            elapsed = time.time() - fps_window_start
            if elapsed >= 1.0:
                current_fps = fps_counter / elapsed
                fps_counter = 0
                fps_window_start = time.time()

            now = time.time()
            # Red alerts in view (shown as flags on the Live page): a change goes out within a second.
            flags = getattr(ctx, "live_flags", None) or []
            if now - last_heartbeat >= heartbeat_interval or (flags != sent_flags and now - last_heartbeat >= 1.0):
                sent_flags = flags
                analytics_snapshot = None
                try:
                    analytics_stage = next((s for s in pipeline.stages if s.name == "analytics"), None)
                    if analytics_stage and hasattr(analytics_stage, "analytics"):
                        a = analytics_stage.analytics
                        analytics_snapshot = {
                            "dwell_stats": a.get_dwell_stats(),
                            "traffic_flow": a.get_traffic_flow(),
                            "heatmap": a.get_heatmap_grid(),
                            "track_count": len(ctx.tracks) if ctx is not None and hasattr(ctx, "tracks") else 0,
                        }
                    # People per zone, its limit and whether it is armed now: "Lobby 7 / 12" on the dashboard.
                    behavior = next((s for s in pipeline.stages if s.name == "behavior"), None)
                    zones_det = getattr(behavior, "anomaly_detector", None)
                    if zones_det is not None and analytics_snapshot is not None:
                        analytics_snapshot["occupancy"] = {
                            z.name: {"count": zones_det.zone_counts.get(z.name, 0), "limit": z.max_people,
                                     "armed": z.armed(now), "type": z.type}
                            for z in zones_det.zones if z.name not in DEFAULT_ZONE_NAMES     # drawn zones only
                        }
                except Exception as e:
                    logger.debug(f"[{camera_id}] analytics snapshot skipped: {e}")
                publish_heartbeat(
                    camera_id=camera_id,
                    camera_location=camera_location,
                    fps=round(current_fps, 1),
                    threat_score=ctx.threat_score if ctx is not None else 0,
                    frame_number=ctx.frame_number if ctx is not None else 0,
                    analytics=analytics_snapshot,
                    flags=flags,
                    infer_ms=round(worker.last_infer_seconds * 1000),
                    ai_age_s=round(worker.result_age(), 1),
                )
                last_heartbeat = now

            stream_due = now - last_stream >= stream_interval
            display = None
            if show_window or (stream_due and overlay is None):
                perf_stats = resource_monitor.get_stats() if perf_enabled else None
                display = (
                    render_full_hud(frame.copy(), ctx, start_time, criminal_names, perf_stats, thermal_mode)
                    if ctx is not None else frame
                )

            if stream_due:
                last_stream = now
                try:
                    if overlay is not None:
                        # Resize first, then draw: cheaper, and text/lines are crisp at stream size.
                        scale = min(1.0, stream_width / frame.shape[1])
                        stream_img = cv2.resize(frame, None, fx=scale, fy=scale,
                                                interpolation=cv2.INTER_AREA) if scale < 1 else frame.copy()
                        overlay.render(stream_img, ctx, scale, now)
                    else:
                        stream_img = display
                        if stream_img.shape[1] > stream_width:
                            scale = stream_width / stream_img.shape[1]
                            stream_img = cv2.resize(
                                stream_img, (stream_width, int(stream_img.shape[0] * scale)),
                            )
                    ok, buf = cv2.imencode(".jpg", stream_img, [cv2.IMWRITE_JPEG_QUALITY, stream_quality])
                    if ok:
                        jpeg = buf.tobytes()
                        publish_frame(camera_id, jpeg)
                        if ctx is not None and ctx.threat_score and ctx.threat_score >= 40 and result_seq != clip_seq:
                            clip_seq = result_seq
                            alert_type = "THREAT"
                            if getattr(ctx, "confirmed_weapons", None):
                                alert_type = "WEAPON_DETECTED"
                            elif getattr(ctx, "active_criminals", None):
                                alert_type = "CRIMINAL_DETECTED"
                            publish_event_clip(
                                camera_id, jpeg,
                                camera_location=camera_location,
                                alert_type=alert_type,
                            )
                except Exception as e:
                    stream_failed(e)        # never let streaming break the CV loop

            if show_window:
                cv2.imshow(title, display)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                elif key == ord("t"):
                    thermal_mode = not thermal_mode
                elif key == ord("s"):
                    stats = pipeline.get_stats()
                    logger.info(f"[{camera_id}] Pipeline stats: {stats}")
    except Exception as e:
        logger.exception(f"Camera worker crashed for {camera_id}: {e}")
    finally:
        worker.stop()
        worker.join(timeout=5)
        if dvr is not None:
            dvr.close()
        cap.release()
        if show_window:
            try:
                cv2.destroyWindow(title)
            except Exception:
                pass
        logger.info(f"Camera worker stopped: {camera_id}")
