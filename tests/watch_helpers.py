"""Watchlist governance fields for test fixtures: an approved entry valid for a day."""
from datetime import timedelta

from clock import utcnow


def approved(**extra) -> dict:
    now = utcnow()
    return dict(wl_status="active", case_no="TEST-FIR-1", legal_basis="Test warrant issued for the test suite",
                issuing_authority="Test court", starts_at=now - timedelta(minutes=1),
                expires_at=now + timedelta(days=1), **extra)
