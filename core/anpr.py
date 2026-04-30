"""
ANPR (Automatic Number Plate Recognition) Module
Uses EasyOCR for license plate detection and recognition
"""
import cv2
import numpy as np
import re
from typing import List, Dict, Optional


class LicensePlateRecognizer:
    """License plate recognition using OCR"""

    def __init__(self, languages: List[str] = None, gpu: bool = False):
        if languages is None:
            languages = ['en']
        self.languages = languages
        self.gpu = gpu
        self.reader = None
        self._init_reader()

    def _init_reader(self):
        """Initialize EasyOCR reader (lazy loading)"""
        try:
            import easyocr
            self.reader = easyocr.Reader(self.languages, gpu=self.gpu)
            print("ANPR: EasyOCR initialized")
        except Exception as e:
            print(f"ANPR: Failed to initialize EasyOCR: {e}")
            self.reader = None

    def detect_plates(self, frame) -> List[Dict]:
        """
        Detect and recognize license plates in frame
        Returns list of dicts: {bbox, text, confidence, plate_number}
        """
        if self.reader is None:
            self._init_reader()
            if self.reader is None:
                return []

        try:
            # Run OCR on the frame
            results = self.reader.readtext(frame)

            plates = []
            for (bbox, text, conf) in results:
                # Clean and validate license plate format
                cleaned = self._clean_plate_number(text)
                if cleaned and self._validate_plate(cleaned):
                    plates.append({
                        'bbox': [int(x) for x in np.array(bbox).flatten()],
                        'text': text,
                        'plate_number': cleaned,
                        'confidence': float(conf)
                    })

            return plates

        except Exception as e:
            print(f"ANPR error: {e}")
            return []

    def _clean_plate_number(self, text: str) -> str:
        """Clean OCR output to extract plate number"""
        # Remove spaces, special chars, convert to uppercase
        cleaned = re.sub(r'[^A-Z0-9]', '', text.upper())
        return cleaned

    def _validate_plate(self, plate: str) -> bool:
        """Validate if string looks like a license plate"""
        # Basic validation: 5-10 alphanumeric characters
        if len(plate) < 5 or len(plate) > 10:
            return False
        # Should have mix of letters and numbers
        has_letter = any(c.isalpha() for c in plate)
        has_number = any(c.isdigit() for c in plate)
        return has_letter and has_number


class LicensePlateDatabase:
    """Database of watchlisted license plates"""

    def __init__(self, db_path: str = "data/watchlisted_plates.txt"):
        self.db_path = db_path
        self.watchlisted = self._load_plates()

    def _load_plates(self) -> set:
        """Load watchlisted plates from file"""
        try:
            with open(self.db_path, 'r') as f:
                return set(line.strip().upper() for line in f if line.strip())
        except FileNotFoundError:
            return set()

    def is_watchlisted(self, plate_number: str) -> bool:
        """Check if plate is in watchlist"""
        return plate_number.upper() in self.watchlisted

    def add_plate(self, plate_number: str, reason: str = "suspicious"):
        """Add plate to watchlist"""
        self.watchlisted.add(plate_number.upper())
        with open(self.db_path, 'a') as f:
            f.write(f"\n{plate_number.upper()}")
