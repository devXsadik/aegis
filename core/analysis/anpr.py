import re
import time
from collections import Counter, defaultdict, deque
from typing import Callable, Optional, Set

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_NOT_PLATE = re.compile(r"[^A-Z0-9ঀ-৿]")
MIN_PLATE_LEN, MAX_PLATE_LEN = 4, 12


def normalize_plate(text: str) -> str:
    """Canonical plate text: upper-case Latin, Bengali letters kept, Bengali digits → ASCII,
    everything else (spaces, dashes, OCR noise) dropped. Used for both OCR reads and the
    watchlist, so "ঢাকা মেট্রো-গ ১২-৩৪৫৬" and "ঢাকামেট্রোগ123456" compare equal."""
    return _NOT_PLATE.sub("", (text or "").upper().translate(_BN_DIGITS))


def plausible_plate(plate: str) -> bool:
    """Cheap filter for OCR hits that are not plates (bumper stickers, shop signs)."""
    return MIN_PLATE_LEN <= len(plate) <= MAX_PLATE_LEN and any(c.isdigit() for c in plate)


class PlateDetector:
    """YOLO plate detector (one class: plate), run on a vehicle crop. Weights from training/
    (models/plate_yolo.pt); without them the recogniser falls back to OCR over the whole crop."""

    def __init__(self, model_path: str, conf: float = 0.35, device: str = "cpu"):
        from ultralytics import YOLO

        from core.detectors.device import lock_for, read_boxes
        self._read_boxes = read_boxes
        self.model = YOLO(model_path)
        self.conf = conf
        self.device = device
        self._lock = lock_for(device)

    def detect(self, roi) -> list:
        with self._lock:
            res = self.model(roi, conf=self.conf, verbose=False, device=self.device)
            boxes = self._read_boxes(res)
        return [((int(x1), int(y1), int(x2), int(y2)), float(c)) for x1, y1, x2, y2, c, _ in boxes]


def prepare_plate(crop):
    """Plate crop → OCR input: at least 64 px tall, grey, contrast-equalised (night, glare)."""
    import cv2
    h = crop.shape[0]
    if h and h < 64:
        f = 64 / h
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(grey)


def join_lines(reads) -> tuple:
    """Bangladeshi plates have two lines (city-class over the number): order the OCR fragments
    top-to-bottom, left-to-right and join them. reads: [(bbox_points, text, conf)]."""
    if not reads:
        return "", 0.0
    boxes = []
    for r in reads:
        ys = [p[1] for p in r[0]]
        xs = [p[0] for p in r[0]]
        boxes.append(((min(ys) + max(ys)) / 2, max(1.0, max(ys) - min(ys)), min(xs), r))
    boxes.sort(key=lambda b: b[0])
    lines, last = [], None
    for cy, hgt, x, r in boxes:           # a new line starts half a text-height below the last
        if last is None or cy - last > 0.5 * hgt:
            lines.append([])
            last = cy
        lines[-1].append((x, r))
    ordered = [r for line in lines for _, r in sorted(line, key=lambda t: t[0])]
    text = "".join(normalize_plate(t) for _, t, _ in ordered)
    conf = min(float(c) for _, _, c in ordered)
    return text, conf


class LicensePlateRecognizer:
    def __init__(self, languages: list = None, gpu: bool = False, plate_detector: "PlateDetector" = None):
        self.languages = languages or ["en"]
        self.gpu = gpu
        self._reader = None
        self.plate_detector = plate_detector

    @property
    def reader(self):
        if self._reader is None:
            import easyocr
            self._reader = easyocr.Reader(self.languages, gpu=self.gpu)
        return self._reader

    def detect_plates(self, roi):
        if self.plate_detector is not None:
            return self._detect_with_detector(roi)
        return self._ocr_whole(roi)

    def _detect_with_detector(self, roi):
        plates = []
        h, w = roi.shape[:2]
        for (x1, y1, x2, y2), det_conf in self.plate_detector.detect(roi):
            px, py = int((x2 - x1) * 0.06), int((y2 - y1) * 0.1)
            x1, y1, x2, y2 = max(0, x1 - px), max(0, y1 - py), min(w, x2 + px), min(h, y2 + py)
            crop = roi[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            reads = [r for r in self.reader.readtext(prepare_plate(crop)) if r[2] >= 0.2]
            text, conf = join_lines(reads)
            if not plausible_plate(text):
                continue
            plates.append({"bbox": (x1, y1, x2, y2), "plate_number": text,
                           "confidence": round(conf * det_conf, 4)})
        return plates

    def _ocr_whole(self, roi):
        results = self.reader.readtext(roi)
        plates = []
        for bbox, text, conf in results:
            if conf < 0.3:
                continue
            cleaned = normalize_plate(text)
            if not plausible_plate(cleaned):
                continue
            x_coords = [int(p[0]) for p in bbox]
            y_coords = [int(p[1]) for p in bbox]
            plates.append({
                "bbox": (min(x_coords), min(y_coords), max(x_coords), max(y_coords)),
                "plate_number": cleaned,
                "confidence": float(conf),
            })
        return plates


class PlateVoter:
    """Multi-read plate voting per vehicle track: one OCR read is never trusted on its own.

    A plate is confirmed when the same text was read `min_votes` times in the last
    `window` reads of that vehicle.
    """

    def __init__(self, window: int = 5, min_votes: int = 2):
        self.window = window
        self.min_votes = min_votes
        self._reads = defaultdict(lambda: deque(maxlen=window))

    def add(self, key, plate: Optional[str]) -> None:
        self._reads[key].append(plate)

    def confirmed(self, key) -> Optional[str]:
        reads = [r for r in self._reads.get(key, ()) if r]
        if not reads:
            return None
        plate, n = Counter(reads).most_common(1)[0]
        return plate if n >= self.min_votes else None

    def prune(self, live_keys) -> None:
        for k in [k for k in self._reads if k not in live_keys]:
            del self._reads[k]


class LicensePlateDatabase:
    """Watchlisted plates from an injected loader, refreshed every `cache_ttl` seconds."""

    def __init__(self, loader: Optional[Callable[[], Set[str]]] = None, cache_ttl: float = 60.0):
        self.loader = loader or (lambda: set())
        self.cache_ttl = cache_ttl
        self._cached = None
        self._loaded_at = 0.0

    @staticmethod
    def key(plate: str) -> str:
        """Compare by the canonical BD form when the text parses (Bangla and English agree),
        else by the plain normalized string."""
        from core.analysis.bd_plate import canonical
        return canonical(plate) or normalize_plate(plate)

    def _load_watchlist(self):
        if self._cached is None or time.time() - self._loaded_at > self.cache_ttl:
            self._cached = {self.key(p) for p in self.loader()}
            self._loaded_at = time.time()
        return self._cached

    def is_watchlisted(self, plate_number: str) -> bool:
        return self.key(plate_number) in self._load_watchlist()

    def invalidate_cache(self):
        self._cached = None
