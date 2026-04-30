"""
Analytics Module
Generates heatmaps, dwell time analysis, and movement patterns
"""
import numpy as np
from typing import Dict, List, Tuple
from collections import defaultdict
from datetime import datetime, timedelta
import cv2


class HeatmapGenerator:
    """Generates heatmaps from detection positions"""

    def __init__(self, frame_width: int, frame_height: int,
                 grid_size: int = 50):
        self.w = frame_width
        self.h = frame_height
        self.grid_size = grid_size
        self.grid_w = frame_width // grid_size + 1
        self.grid_h = frame_height // grid_size + 1
        self.heatmap = np.zeros((self.grid_h, self.grid_w), dtype=np.float32)
        self.timestamps = defaultdict(list)  # grid cell -> list of timestamps

    def add_detection(self, x: int, y: int, timestamp: datetime):
        """Add a detection point to the heatmap"""
        grid_x = int(x / self.w * self.grid_w)
        grid_y = int(y / self.h * self.grid_h)
        grid_x = min(grid_x, self.grid_w - 1)
        grid_y = min(grid_y, self.grid_h - 1)

        self.heatmap[grid_y, grid_x] += 1.0
        self.timestamps[(grid_y, grid_x)].append(timestamp)

    def get_heatmap_image(self, frame=None, alpha: float = 0.5) -> np.ndarray:
        """
        Generate heatmap overlay image
        Returns RGB image with heatmap overlay
        """
        # Normalize heatmap
        if self.heatmap.max() > 0:
            normalized = self.heatmap / self.heatmap.max() * 255
        else:
            normalized = self.heatmap

        # Create color heatmap (BGR)
        heatmap_color = cv2.applyColorMap(
            normalized.astype(np.uint8),
            cv2.COLORMAP_JET
        )

        # Resize to frame size
        heatmap_resized = cv2.resize(heatmap_color, (self.w, self.h))

        if frame is not None:
            # Overlay on frame
            overlay = cv2.addWeighted(frame, 1 - alpha, heatmap_resized, alpha, 0)
            return overlay

        return heatmap_resized

    def get_hotspots(self, threshold: float = 0.7) -> List[dict]:
        """Get hotspot locations (top N% activity areas)"""
        if self.heatmap.max() == 0:
            return []

        threshold_value = self.heatmap.max() * threshold
        hotspots = []

        for y in range(self.grid_h):
            for x in range(self.grid_w):
                if self.heatmap[y, x] >= threshold_value:
                    hotspots.append({
                        'x': int(x * self.grid_size),
                        'y': int(y * self.grid_size),
                        'count': int(self.heatmap[y, x]),
                        'intensity': float(self.heatmap[y, x] / self.heatmap.max())
                    })

        return sorted(hotspots, key=lambda h: h['count'], reverse=True)


class DwellTimeAnalyzer:
    """Analyzes dwell time and movement patterns"""

    def __init__(self):
        self.track_data: Dict[int, List[Tuple[datetime, Tuple[int, int]]]] = {}
        self.dwell_threshold = 300  # 5 minutes in seconds

    def update_track(self, track_id: int, timestamp: datetime,
                     position: Tuple[int, int]):
        """Update track with new position"""
        if track_id not in self.track_data:
            self.track_data[track_id] = []

        self.track_data[track_id].append((timestamp, position))

        # Keep last 1000 points
        if len(self.track_data[track_id]) > 1000:
            self.track_data[track_id] = self.track_data[track_id][-1000:]

    def get_dwell_zones(self, track_id: int) -> List[dict]:
        """
        Identify zones where person dwelled for extended periods
        Returns list of {zone, start_time, end_time, duration}
        """
        if track_id not in self.track_data:
            return []

        points = self.track_data[track_id]
        if len(points) < 2:
            return []

        zones = []
        current_zone = None
        zone_start = None

        for i, (timestamp, pos) in enumerate(points):
            zone = self._get_zone(pos)

            if zone != current_zone:
                if current_zone is not None and zone_start is not None:
                    duration = (timestamp - zone_start).total_seconds()
                    if duration >= self.dwell_threshold:
                        zones.append({
                            'zone': current_zone,
                            'start': zone_start,
                            'end': timestamp,
                            'duration': duration
                        })
                current_zone = zone
                zone_start = timestamp

        return zones

    def _get_zone(self, pos: Tuple[int, int]) -> str:
        """Determine zone from position (simplified)"""
        x, y = pos
        if x < 640:  # Assuming 1280x720
            return 'left'
        elif x < 1280:
            return 'right'
        return 'center'

    def get_movement_pattern(self, track_id: int) -> dict:
        """Analyze movement pattern for a track"""
        if track_id not in self.track_data:
            return {}

        points = self.track_data[track_id]
        if len(points) < 5:
            return {'pattern': 'insufficient_data'}

        # Calculate direction changes
        directions = []
        for i in range(1, len(points)):
            prev_pos = points[i-1][1]
            curr_pos = points[i][1]
            dx = curr_pos[0] - prev_pos[0]
            dy = curr_pos[1] - prev_pos[1]
            directions.append((dx, dy))

        # Detect patterns
        if all(abs(d[0]) < 5 and abs(d[1]) < 5 for d in directions):
            return {'pattern': 'stationary', 'confidence': 0.9}
        elif sum(d[0] for d in directions) > 100:
            return {'pattern': 'moving_left_to_right', 'confidence': 0.8}
        elif sum(d[0] for d in directions) < -100:
            return {'pattern': 'moving_right_to_left', 'confidence': 0.8}
        else:
            return {'pattern': 'erratic_movement', 'confidence': 0.6}
