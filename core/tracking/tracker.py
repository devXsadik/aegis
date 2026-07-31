from deep_sort_realtime.deepsort_tracker import DeepSort


class HumanTracker:
    def __init__(self):
        self.tracker = DeepSort(
            max_age=50,             # keep lost track longer (default 30)
            n_init=2,               # confirm track after 2 detections (better for low FPS)
            max_iou_distance=0.9,   # looser IoU matching for low FPS
            max_cosine_distance=0.4,# looser appearance matching
            nn_budget=100,          # appearance feature memory
        )

    def track(self, detections, frame):
        return self.tracker.update_tracks(detections, frame=frame)
