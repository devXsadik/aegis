#!/usr/bin/env python3
"""Create demo admin user for graduation defense demo."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.database import SessionLocal, init_db
from backend.models.user import User
from backend.auth.auth import hash_password


def seed_demo_user():
    if os.getenv("ENVIRONMENT", "development") == "production":
        print("Skipping demo user seed in production.")
        return
    init_db()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == "admin").first()
        if existing:
            print("Demo user 'admin' already exists.")
            return
        user = User(
            username="admin",
            email="admin@ai-sss.local",
            hashed_password=hash_password("admin123"),
            role="admin",
            is_active=True,
        )
        db.add(user)
        db.commit()
        print("Created demo admin user:")
        print("  username: admin")
        print("  password: admin123")
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_user()
