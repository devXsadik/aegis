"""
Anomaly Detection Module
Detects unusual patterns in surveillance data using statistical analysis
"""
import numpy as np
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import json


class AnomalyDetector:
    """Detects anomalies in surveillance patterns"""

    def __init__(self):
        self.detection_history: Dict[str, List[dict]] = defaultdict(list)
        self.baseline_stats: Dict[str, dict] = {}
        self.learning_period_hours = 24

    def record_detection(self, camera_id: str, detection_type: str,
                       confidence: float, location: tuple, timestamp: datetime):
        """Record a detection event for analysis"""
        self.detection_history[camera_id].append({
            'type': detection_type,
            'confidence': confidence,
            'location': location,
            'timestamp': timestamp
        })
        # Keep last 1000 detections per camera
        if len(self.detection_history[camera_id]) > 1000:
            self.detection_history[camera_id] = self.detection_history[camera_id][-1000:]

    def detect_anomalies(self, camera_id: str) -> List[dict]:
        """
        Detect anomalies for a specific camera
        Returns list of anomaly descriptions
        """
        anomalies = []
        detections = self.detection_history.get(camera_id, [])

        if len(detections) < 10:
            return anomalies  # Not enough data

        # Check for sudden spike in detections
        recent = [d for d in detections if
                  (datetime.utcnow() - d['timestamp']).total_seconds() < 300]  # Last 5 min

        if len(recent) > 10:
            anomalies.append({
                'type': 'spike',
                'description': f'Sudden spike in activity: {len(recent)} detections in 5 minutes',
                'severity': 'medium'
            })

        # Check for unusual time patterns
        night_detections = [d for d in recent if d['timestamp'].hour < 6 or d['timestamp'].hour > 22]
        if len(night_detections) > 5:
            anomalies.append({
                'type': 'unusual_time',
                'description': 'Unusual activity during night hours',
                'severity': 'low'
            })

        # Check for loitering (many detections at same location)
        location_counts = defaultdict(int)
        for d in recent:
            loc = d['location']
            location_counts[loc] += 1

        for loc, count in location_counts.items():
            if count > 20:
                anomalies.append({
                    'type': 'loitering',
                    'description': f'Possible loitering detected at location {loc}',
                    'severity': 'medium',
                    'location': loc
                })

        return anomalies

    def get_camera_stats(self, camera_id: str) -> dict:
        """Get statistics for a camera"""
        detections = self.detection_history.get(camera_id, [])
        if not detections:
            return {'total': 0}

        types = defaultdict(int)
        for d in detections:
            types[d['type']] += 1

        return {
            'total': len(detections),
            'by_type': dict(types),
            'last_24h': len([d for d in detections if
                             (datetime.utcnow() - d['timestamp']).total_seconds() < 86400])
        }

    def save_state(self, filepath: str = 'data/anomaly_state.json'):
        """Save detector state to file"""
        state = {
            'detection_history': {
                k: [
                    {
                        'type': d['type'],
                        'confidence': d['confidence'],
                        'location': d['location'],
                        'timestamp': d['timestamp'].isoformat()
                    } for d in v
                ] for k, v in self.detection_history.items()
            }
        }
        with open(filepath, 'w') as f:
            json.dump(state, f)

    def load_state(self, filepath: str = 'data/anomaly_state.json'):
        """Load detector state from file"""
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)
            for camera_id, detections in state.get('detection_history', {}).items():
                self.detection_history[camera_id] = [
                    {
                        'type': d['type'],
                        'confidence': d['confidence'],
                        'location': tuple(d['location']),
                        'timestamp': datetime.fromisoformat(d['timestamp'])
                    } for d in detections
                ]
        except FileNotFoundError:
            pass
