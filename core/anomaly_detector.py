import numpy as np
from collections import defaultdict, deque
from datetime import datetime, timedelta


class AnomalyDetector:
    def __init__(self, crowd_threshold: int = 5, dwell_seconds: int = 300):
        self.crowd_threshold = crowd_threshold
        self.dwell_seconds = dwell_seconds
        self.zone_counts = defaultdict(int)
        self.dwell_times = defaultdict(lambda: defaultdict(float))

    def update(self, tracks, frame_shape):
        h, w = frame_shape[:2]
        zones = {
            "top_left": (0, 0, w // 2, h // 2),
            "top_right": (w // 2, 0, w, h // 2),
            "bottom_left": (0, h // 2, w // 2, h),
            "bottom_right": (w // 2, h // 2, w, h),
        }
        zone_assignments = defaultdict(list)
        now = datetime.now().timestamp()
        for track in tracks:
            if not track.is_confirmed():
                continue
            x1, y1, x2, y2 = map(int, track.to_ltrb())
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            for zone_name, (zx1, zy1, zx2, zy2) in zones.items():
                if zx1 <= cx <= zx2 and zy1 <= cy <= zy2:
                    zone_assignments[zone_name].append(track.track_id)
                    if track.track_id not in self.dwell_times[zone_name]:
                        self.dwell_times[zone_name][track.track_id] = now
                    break
        for zone in zones:
            self.zone_counts[zone] = len(zone_assignments[zone])
        anomalies = []
        for zone, count in self.zone_counts.items():
            if count >= self.crowd_threshold:
                anomalies.append({
                    "type": "crowd",
                    "zone": zone,
                    "count": count,
                    "severity": "high" if count >= self.crowd_threshold * 2 else "medium",
                })
        for zone, tracks_dict in self.dwell_times.items():
            for tid, start_time in list(tracks_dict.items()):
                if tid not in {t.track_id for t in tracks if t.is_confirmed()}:
                    continue
                if now - start_time > self.dwell_seconds:
                    anomalies.append({
                        "type": "dwell",
                        "zone": zone,
                        "track_id": tid,
                        "duration_seconds": int(now - start_time),
                        "severity": "medium",
                    })
        return anomalies
