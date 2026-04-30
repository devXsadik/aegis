"""
Tests for Face Recognition DB Module
"""
import pytest
import numpy as np
from unittest.mock import Mock, patch
from core.face_recognizer_db import FaceRecognizerDB


class TestFaceRecognizerDB:
    def test_init(self):
        with patch('core.face_recognizer_db.SessionLocal') as mock_session:
            recognizer = FaceRecognizerDB(tolerance=0.5)
            assert recognizer.tolerance == 0.5
            assert len(recognizer.known_encodings) == 0

    @patch('core.face_recognizer_db.face_recognition')
    @patch('core.face_recognizer_db.SessionLocal')
    def test_recognize_person(self, mock_session, mock_fr):
        # Mock database query
        mock_db = Mock()
        mock_db.query.return_value.all.return_value = []
        mock_session.return_value = mock_db

        recognizer = FaceRecognizerDB()
        
        # Mock face encoding detection
        mock_fr.face_encodings.return_value = [np.random.rand(128)]
        mock_fr.compare_faces.return_value = [False]

        test_image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        result = recognizer.recognize_person(test_image)
        
        assert result is None  # No match

    @patch('core.face_recognizer_db.SessionLocal')
    def test_load_encodings_empty(self, mock_session):
        mock_db = Mock()
        mock_db.query.return_value.all.return_value = []
        mock_session.return_value = mock_db
        mock_session.return_value.__enter__ = Mock(return_value=mock_db)
        mock_session.return_value.__exit__ = Mock(return_value=False)

        recognizer = FaceRecognizerDB()
        assert len(recognizer.known_encodings) == 0
