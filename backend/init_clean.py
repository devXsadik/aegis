"""
Clean Database Initialization
Creates all tables in correct order
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from passlib.context import CryptContext

# Database connection
DATABASE_URL = "postgresql://surveillance:6Xv!Kf3n@qP#4LmZ9*r@localhost:5432/surveillance_db"
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

def init_db():
    print("Creating database tables...")

    # Import all models to register them
    from backend.models.user import User
    from backend.models.known_person import KnownPerson
    from backend.models.face_encoding import FaceEncoding
    from backend.models.evidence import Evidence
    from backend.models.audit_log import AuditLog
    from backend.models.vehicle import LicensePlate, VehicleDetection

    # Import Base from a central location
    from backend.db.database import Base

    # Create all tables
    Base.metadata.create_all(bind=engine)
    print("✓ All tables created successfully!")

    # List tables
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"\nCreated {len(tables)} tables:")
    for table in sorted(tables):
        print(f"  - {table}")


def create_admin():
    print("\nCreating admin user...")
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    session = Session()
    try:
        # Check if admin exists
        existing = session.query(User).filter_by(username="admin").first()
        if existing:
            print("  ✓ Admin user already exists")
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
        print("  ✓ Created admin user")
        print("    Username: admin")
        print("    Password: Admin123!")
        print("    ⚠️  CHANGE THIS PASSWORD IMMEDIATELY!")

    except Exception as e:
        session.rollback()
        print(f"  ✗ Error: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    init_db()
    create_admin()
    print("\n✓ Database initialization complete!")
