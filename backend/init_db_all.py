"""
Database Initialization Script
Creates all tables and sets up initial data
"""
from backend.db.database import Base, engine
from backend.models.user import User
from backend.models.known_person import KnownPerson
from backend.models.face_encoding import FaceEncoding
from backend.models.evidence import Evidence
from backend.models.audit_log import AuditLog
from backend.models.vehicle import LicensePlate, VehicleDetection
from backend.models.alert import Alert as AlertLog


def init_db():
    """Create all database tables"""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✓ All tables created successfully!")

    # Migrate: add columns that may not exist on existing tables
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_attempts INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS previous_hash VARCHAR(64)",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS hash VARCHAR(64)",
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as e:
                print(f"  Migration skipped ({e})")

    # List created tables
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"\nCreated {len(tables)} tables:")
    for table in sorted(tables):
        columns = inspector.get_columns(table)
        print(f"  - {table} ({len(columns)} columns)")


def create_admin_user():
    """Create default admin user if not exists"""
    from sqlalchemy.orm import sessionmaker
    from passlib.context import CryptContext
    from datetime import datetime

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        existing = session.query(User).filter_by(username="admin").first()
        if existing:
            print("\n✓ Admin user already exists")
            return

        admin = User(
            username="admin",
            email="admin@surveillance.system",
            hashed_password=pwd_context.hash("Admin123!"),
            role="admin",
            is_active=True,
            created_at=datetime.utcnow()
        )
        session.add(admin)
        session.commit()
        print("\n✓ Created default admin user:")
        print("  Username: admin")
        print("  Password: Admin123!")
        print("  ⚠️  Please change this password immediately!")

    except Exception as e:
        session.rollback()
        print(f"\n✗ Error creating admin: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    init_db()
    create_admin_user()
    print("\n✓ Database initialization complete!")
