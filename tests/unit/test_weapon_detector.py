"""Person-crop weapon detection: crop geometry, mapping back, merging, and which images are sent."""
import numpy as np

from core.detectors import weapon_detector as wd


class FakeBoxes:
    def __init__(self, rows):
        import torch
        rows = torch.tensor(rows, dtype=torch.float32).reshape(-1, 6)
        self.xyxy, self.conf, self.cls = rows[:, :4], rows[:, 4], rows[:, 5]

    def __len__(self):
        return len(self.conf)


class FakeResult:
    def __init__(self, rows):
        self.boxes = FakeBoxes(rows)


class FakeModel:
    """Finds a 'knife' at a fixed spot of every crop (not of the full frame)."""
    names = {0: "blade", 1: "firearm"}

    def __init__(self):
        self.calls = []

    def __call__(self, images, **kw):
        self.calls.append([im.shape for im in images])
        out = []
        for im in images:
            if im.shape[:2] == (1080, 1920):
                out.append(FakeResult([]))
            else:
                out.append(FakeResult([[100, 200, 160, 260, 0.8, 0]]))
        return out


def make(mode="both", **kw):
    d = wd.WeaponDetector.__new__(wd.WeaponDetector)
    d.model, d.names = FakeModel(), FakeModel.names
    d.conf_threshold, d.device, d.mode = 0.4, "cpu", mode
    d.crop_size, d.max_crops, d.min_person_px = kw.get("crop_size", 640), kw.get("max_crops", 4), kw.get("min_person_px", 40)
    import threading
    d._lock = threading.Lock()
    return d


def test_crop_region_widens_and_clips():
    assert wd.crop_region((100, 100, 200, 300), (1080, 1920)) == (65, 76, 235, 324)
    assert wd.crop_region((0, 0, 50, 100), (1080, 1920))[:2] == (0, 0)
    assert wd.crop_region((1900, 1000, 1920, 1080), (1080, 1920))[2:] == (1920, 1080)


def test_to_frame_inverts_the_enlargement():
    assert wd.to_frame((100, 200, 160, 260), (500, 300, 600, 500), 2.0) == (550, 400, 580, 430)


def test_merge_keeps_the_best_of_overlapping_boxes():
    a = {"bbox": (0, 0, 100, 100), "score": 0.5}
    b = {"bbox": (5, 5, 100, 100), "score": 0.9}
    c = {"bbox": (300, 300, 350, 350), "score": 0.4}
    assert wd.merge([a, b, c]) == [b, c]


def test_person_crops_are_enlarged_and_mapped_back():
    d = make("both")
    frame = np.zeros((1080, 1920, 3), np.uint8)
    people = [([1000, 500, 1060, 660], 0.9, 0)]                # a distant person, 160 px tall
    dets = d.detect(frame, people=people)
    shapes = d.model.calls[0]
    assert shapes[0] == (1080, 1920, 3) and len(shapes) == 2   # one batched call: frame + one crop
    assert max(shapes[1][:2]) == 640                           # enlarged to crop_size
    assert len(dets) == 1 and dets[0]["class_name"] == "blade"
    x1, y1, x2, y2 = dets[0]["bbox"]
    region = wd.crop_region(people[0][0], frame.shape)
    assert region[0] <= x1 < x2 <= region[2] and region[1] <= y1 < y2 <= region[3]
    assert x2 - x1 < 60                                        # shrunk back to frame scale


def test_full_mode_ignores_people_and_tiny_people_are_skipped():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    d = make("full")
    d.detect(frame, people=[([1000, 500, 1060, 660], 0.9, 0)])
    assert len(d.model.calls[0]) == 1
    d = make("person_crop")
    d.detect(frame, people=[([1000, 500, 1010, 530], 0.9, 0)])  # 30 px tall: below min_person_px
    assert d.model.calls[0] == [(1080, 1920, 3)]                # → whole frame instead


def test_person_crop_without_people_falls_back_to_the_full_frame():
    d = make("person_crop")
    d.detect(np.zeros((1080, 1920, 3), np.uint8), people=[])
    assert d.model.calls[0] == [(1080, 1920, 3)]


def test_at_most_max_crops_people_most_confident_first():
    d = make("person_crop", max_crops=2)
    people = [([100 * i, 100, 100 * i + 60, 300], 0.5 + i / 10, 0) for i in range(4)]
    crops = d._crops(np.zeros((1080, 1920, 3), np.uint8), people)
    assert len(crops) == 2 and crops[0][0][0] < 400 and crops[0][0][0] > crops[1][0][0]
