from deep_sort_realtime.deepsort_tracker import DeepSort


class HumanTracker:
    def __init__(self):
        self.tracker = DeepSort(
            max_age=50,             # keep lost track longer (default 30)
            n_init=3,               # confirm track after 3 detections
            max_iou_distance=0.7,   # stricter IoU matching
            max_cosine_distance=0.3,# stricter appearance matching
            nn_budget=100,          # appearance feature memory
        )

    def track(self, detections, frame):
        return self.tracker.update_tracks(detections, frame=frame)
