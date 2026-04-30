from backend.db.database import Base, engine
from backend.models import user, face_encoding, evidence, audit_log

if __name__ == "__main__":
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully!")
