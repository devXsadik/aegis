"""
API Integration Tests
Tests FastAPI endpoints with TestClient
"""
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.db.database import Base, engine
from backend.models import User, FaceEncoding, Evidence
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@pytest.fixture(scope="module")
def test_db():
    """Create test database tables"""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_db):
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    """Get auth headers with admin token"""
    # Create admin user in DB
    from backend.db.database import SessionLocal
    db = SessionLocal()
    user = User(
        username="testadmin",
        email="test@test.com",
        hashed_password=pwd_context.hash("testpass123"),
        role="admin"
    )
    db.add(user)
    db.commit()
    db.close()

    # Login
    response = client.post("/auth/login", json={
        "username": "testadmin",
        "password": "testpass123"
    })
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestAuthAPI:
    def test_login_success(self, client):
        # First create a user
        from backend.db.database import SessionLocal
        db = SessionLocal()
        user = User(
            username="logintest",
            email="login@test.com",
            hashed_password=pwd_context.hash("password123"),
            role="viewer"
        )
        db.add(user)
        db.commit()
        db.close()

        response = client.post("/auth/login", json={
            "username": "logintest",
            "password": "password123"
        })
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_login_failure(self, client):
        response = client.post("/auth/login", json={
            "username": "nonexistent",
            "password": "wrong"
        })
        assert response.status_code == 401


class TestEvidenceAPI:
    def test_list_evidence_empty(self, client, auth_headers):
        response = client.get("/evidence/", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_evidence_unauthorized(self, client):
        response = client.get("/evidence/")
        assert response.status_code == 403


class TestVehicleAPI:
    def test_list_plates_empty(self, client, auth_headers):
        response = client.get("/vehicles/plates", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_add_watchlisted_plate(self, client, auth_headers):
        response = client.post("/vehicles/plates", json={
            "plate_number": "ABC123",
            "reason": "stolen"
        }, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["watchlisted"] == True


class TestAnalyticsAPI:
    def test_get_summary(self, client, auth_headers):
        response = client.get("/analytics/summary", headers=auth_headers)
        assert response.status_code == 200
        assert "total_detections" in response.json()
