from backend.main import app
from backend.db.database import SessionLocal
from backend.models.known_person import KnownPerson

db = SessionLocal()
p1 = db.query(KnownPerson).filter(KnownPerson.person_id == 'CRIMINAL_001_Sadik').first()
p2 = db.query(KnownPerson).filter(KnownPerson.person_id == 'CRIMINAL_002_Tarik').first()

if p1 and p2:
    # We swap their properties
    p1.person_id = 'TEMP'
    p1.name = 'TEMP'
    db.commit()

    p2.person_id = 'CRIMINAL_001_Sadik'
    p2.name = 'Sadik'
    db.commit()

    p1 = db.query(KnownPerson).filter(KnownPerson.person_id == 'TEMP').first()
    p1.person_id = 'CRIMINAL_002_Tarik'
    p1.name = 'Tarik'
    db.commit()

    print("Swap complete!")
else:
    print("Could not find both persons in DB")

db.close()
