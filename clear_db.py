from backend.db.database import SessionLocal
from backend.models.known_person import KnownPerson
from backend.models.face_encoding import FaceEncoding
from backend.models.person_image import PersonImage
from backend.models.evidence import Evidence
from backend.models.incident import Incident

db = SessionLocal()
db.query(FaceEncoding).delete()
db.query(PersonImage).delete()
db.query(Evidence).delete()
db.query(Incident).delete()
db.query(KnownPerson).delete()
db.commit()
print("Cleared DB tables!")
