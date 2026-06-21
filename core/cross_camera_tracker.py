import numpy as np
from collections import defaultdict


class CrossCameraTracker:
    def __init__(self, appearance_similarity_threshold: float = 0.6):
        self.threshold = appearance_similarity_threshold
        self.global_ids = {}
        self.next_global_id = 0
        self.camera_tracks = defaultdict(dict)

    def register_camera(self, camera_id: str):
        if camera_id not in self.camera_tracks:
            self.camera_tracks[camera_id] = {}

    def update(self, camera_id: str, local_track_id: int, feature: np.ndarray):
        self.register_camera(camera_id)
        if local_track_id in self.camera_tracks[camera_id]:
            global_id = self.camera_tracks[camera_id][local_track_id]
        else:
            global_id = None
        if global_id is None:
            best_match = self._find_match(feature, exclude=camera_id)
            if best_match is not None:
                global_id = best_match
            else:
                global_id = self.next_global_id
                self.next_global_id += 1
        self.camera_tracks[camera_id][local_track_id] = global_id
        self.global_ids[global_id] = feature
        return global_id

    def _find_match(self, feature: np.ndarray, exclude: str = None):
        best_id = None
        best_sim = self.threshold
        for gid, gfeat in self.global_ids.items():
            sim = np.dot(feature, gfeat) / (np.linalg.norm(feature) * np.linalg.norm(gfeat) + 1e-8)
            if sim > best_sim:
                best_sim = sim
                best_id = gid
        return best_id

    def get_global_id(self, camera_id: str, local_track_id: int):
        return self.camera_tracks.get(camera_id, {}).get(local_track_id, None)
