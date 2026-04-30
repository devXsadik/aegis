"""
Tests for ANPR (License Plate Recognition) Module
"""
import pytest
import numpy as np
from core.anpr import LicensePlateRecognizer, LicensePlateDatabase


@pytest.fixture
def anpr():
    return LicensePlateRecognizer(languages=['en'], gpu=False)


@pytest.fixture
def sample_plate_image():
    """Create a simple test image with text"""
    img = np.ones((100, 400, 3), dtype=np.uint8) * 255
    return img


class TestLicensePlateRecognizer:
    def test_init(self, anpr):
        assert anpr.languages == ['en']
        assert anpr.gpu == False

    def test_clean_plate_number(self, anpr):
        assert anpr._clean_plate_number("ABC 123") == "ABC123"
        assert anpr._clean_plate_number("XY-789") == "XY789"
        assert anpr._clean_plate_number("12 34 56") == "123456"

    def test_validate_plate(self, anpr):
        assert anpr._validate_plate("ABC123") == True
        assert anpr._validate_plate("XY789") == True
        assert anpr._validate_plate("123") == False  # Too short
        assert anpr._validate_plate("ABCDEFGHIJKL") == False  # Too long
        assert anpr._validate_plate("ABCDE") == False  # No numbers
        assert anpr._validate_plate("12345") == False  # No letters


class TestLicensePlateDatabase:
    def test_init(self, tmp_path):
        db_path = tmp_path / "test_plates.txt"
        db = LicensePlateDatabase(str(db_path))
        assert db.watchlisted == set()

    def test_add_and_check_plate(self, tmp_path):
        db_path = tmp_path / "test_plates.txt"
        db = LicensePlateDatabase(str(db_path))
        
        db.add_plate("ABC123", "stolen")
        assert db.is_watchlisted("ABC123") == True
        assert db.is_watchlisted("XYZ789") == False

    def test_case_insensitive(self, tmp_path):
        db_path = tmp_path / "test_plates.txt"
        db = LicensePlateDatabase(str(db_path))
        
        db.add_plate("abc123")
        assert db.is_watchlisted("ABC123") == True
        assert db.is_watchlisted("Abc123") == True
