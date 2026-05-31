from backend.db.database import Base, engine
from backend.models import user, face_encoding, evidence, audit_log, alert, camera, config_entry, vehicle

if __name__ == "__main__":
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)

    # Add new columns for existing tables (safe to run repeatedly)
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
            except Exception:
                pass

    print("Database initialized successfully!")
