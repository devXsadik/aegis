import cv2
import numpy as np
import re
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.models.vehicle import LicensePlate


class LicensePlateRecognizer:
    def __init__(self, languages: list = None, gpu: bool = False):
        self.languages = languages or ["en"]
        self.gpu = gpu
        self._reader = None

    @property
    def reader(self):
        if self._reader is None:
            import easyocr
            self._reader = easyocr.Reader(self.languages, gpu=self.gpu)
        return self._reader

    def detect_plates(self, roi):
        results = self.reader.readtext(roi)
        plates = []
        for bbox, text, conf in results:
            if conf < 0.3:
                continue
            cleaned = re.sub(r"[^A-Z0-9]", "", text.upper())
            if len(cleaned) < 3:
                continue
            x_coords = [int(p[0]) for p in bbox]
            y_coords = [int(p[1]) for p in bbox]
            plates.append({
                "bbox": (min(x_coords), min(y_coords), max(x_coords), max(y_coords)),
                "plate_number": cleaned,
                "confidence": float(conf),
            })
        return plates


class LicensePlateDatabase:
    def __init__(self):
        self._cached = None

    def _load_watchlist(self):
        if self._cached is not None:
            return self._cached
        db: Session = SessionLocal()
        try:
            plates = db.query(LicensePlate).filter(LicensePlate.watchlisted == True).all()
            self._cached = {p.plate_number for p in plates}
            return self._cached
        finally:
            db.close()

    def is_watchlisted(self, plate_number: str) -> bool:
        return plate_number.upper() in self._load_watchlist()

    def invalidate_cache(self):
        self._cached = None
