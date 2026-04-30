"""
Performance Optimizations Module
Includes frame skipping, caching, and resource management
"""
import time
from functools import lru_cache
import numpy as np


class FrameSkipper:
    """Skip frames intelligently to maintain target FPS"""

    def __init__(self, target_fps: int = 30):
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps
        self.last_frame_time = 0
        self.frame_count = 0
        self.skip_count = 0

    def should_process(self) -> bool:
        """Check if we should process this frame"""
        current_time = time.time()
        elapsed = current_time - self.last_frame_time

        if elapsed >= self.frame_interval:
            self.last_frame_time = current_time
            self.frame_count += 1
            return True

        self.skip_count += 1
        return False

    def get_stats(self) -> dict:
        total = self.frame_count + self.skip_count
        skip_rate = (self.skip_count / total * 100) if total > 0 else 0
        return {
            'processed': self.frame_count,
            'skipped': self.skip_count,
            'skip_rate': f"{skip_rate:.1f}%"
        }


class DetectionCache:
    """Cache detection results for similar frames"""

    def __init__(self, max_size: int = 100):
        self.cache = {}
        self.max_size = max_size

    def get_key(self, frame, region: tuple) -> str:
        """Generate cache key from frame hash and region"""
        frame_hash = hash(frame.tobytes())
        return f"{frame_hash}_{region}"

    def get(self, key: str):
        """Get cached result"""
        if key in self.cache:
            return self.cache[key]
        return None

    def set(self, key: str, value):
        """Cache detection result"""
        if len(self.cache) >= self.max_size:
            # Remove oldest entry (simple FIFO)
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
        self.cache[key] = value


class ResourceMonitor:
    """Monitor system resources during surveillance"""

    def __init__(self):
        self.start_time = time.time()
        self.peak_memory = 0

    def get_stats(self) -> dict:
        """Get resource usage stats"""
        import psutil
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            cpu_percent = process.cpu_percent(interval=0.1)

            return {
                'cpu_percent': cpu_percent,
                'memory_mb': memory_info.rss / 1024 / 1024,
                'uptime_seconds': time.time() - self.start_time
            }
        except ImportError:
            return {'error': 'psutil not installed'}
