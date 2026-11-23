"""Default managed lists for vehicles (Settings → Vehicle classes & models). Seeded once into
vehicle_catalog; admins add / rename / retire entries after that."""

from sqlalchemy.orm import Session

from backend.models.watchlist import VehicleCatalog

TYPES = [
    ("car", "Car", "প্রাইভেট কার"), ("suv", "SUV / jeep", "জিপ"), ("microbus", "Microbus", "মাইক্রোবাস"),
    ("pickup", "Pickup", "পিকআপ"), ("bus", "Bus", "বাস"), ("truck", "Truck", "ট্রাক"),
    ("covered_van", "Covered van", "কাভার্ড ভ্যান"), ("cng", "CNG auto-rickshaw", "সিএনজি"),
    ("easy_bike", "Battery auto / easy-bike", "ইজিবাইক"), ("leguna", "Leguna", "লেগুনা"),
    ("motorcycle", "Motorcycle", "মোটরসাইকেল"), ("ambulance", "Ambulance", "অ্যাম্বুলেন্স"), ("other", "Other", "অন্যান্য"),
]
COLORS = [
    ("white", "White", "সাদা"), ("black", "Black", "কালো"), ("silver", "Silver", "রুপালি"), ("grey", "Grey", "ধূসর"),
    ("red", "Red", "লাল"), ("blue", "Blue", "নীল"), ("green", "Green", "সবুজ"), ("yellow", "Yellow", "হলুদ"),
    ("orange", "Orange", "কমলা"), ("brown", "Brown", "বাদামি"), ("maroon", "Maroon", "মেরুন"), ("other", "Other", "অন্যান্য"),
]
MAKES = {
    "toyota": ("Toyota", ["axio", "premio", "allion", "corolla", "noah", "hiace", "probox", "land_cruiser_prado", "harrier", "chr"]),
    "honda": ("Honda", ["civic", "vezel", "grace", "cbr", "cb_hornet", "livo"]),
    "nissan": ("Nissan", ["sunny", "x_trail", "urvan"]),
    "mitsubishi": ("Mitsubishi", ["pajero", "lancer", "l200"]),
    "suzuki": ("Suzuki", ["swift", "alto", "gixxer"]),
    "hyundai": ("Hyundai", ["elantra", "tucson"]),
    "tata": ("Tata", ["ace", "lpt_1613"]),
    "ashok_leyland": ("Ashok Leyland", ["viking", "dost"]),
    "bajaj": ("Bajaj", ["re_cng", "pulsar", "discover", "platina"]),
    "tvs": ("TVS", ["apache", "metro"]),
    "yamaha": ("Yamaha", ["fz", "r15"]),
    "hero": ("Hero", ["splendor", "hunk"]),
    "mahindra": ("Mahindra", ["scorpio", "pickup"]),
    "isuzu": ("Isuzu", ["d_max", "npr"]),
}
MODEL_NAMES = {"chr": "C-HR", "x_trail": "X-Trail", "re_cng": "RE (CNG)", "d_max": "D-Max", "lpt_1613": "LPT 1613",
               "cb_hornet": "CB Hornet", "cbr": "CBR", "fz": "FZ", "r15": "R15", "npr": "NPR", "l200": "L200",
               "land_cruiser_prado": "Land Cruiser Prado"}


def _title(code: str) -> str:
    return MODEL_NAMES.get(code) or code.replace("_", " ").title()


def seed_defaults(db: Session) -> int:
    if db.query(VehicleCatalog.id).first():
        return 0
    rows = []
    for i, (c, en, bn) in enumerate(TYPES):
        rows.append(VehicleCatalog(kind="type", code=c, name_en=en, name_bn=bn, sort=i))
    for i, (c, en, bn) in enumerate(COLORS):
        rows.append(VehicleCatalog(kind="color", code=c, name_en=en, name_bn=bn, sort=i))
    for i, (make, (name, models)) in enumerate(sorted(MAKES.items())):
        rows.append(VehicleCatalog(kind="make", code=make, name_en=name, sort=i))
        for j, m in enumerate(models):
            rows.append(VehicleCatalog(kind="model", code=f"{make}_{m}", name_en=f"{name} {_title(m)}",
                                       parent_code=make, sort=j))
    rows.append(VehicleCatalog(kind="model", code="unknown", name_en="Unknown", sort=999))
    db.add_all(rows)
    return len(rows)


def codes(db: Session, kind: str) -> set:
    return {c for (c,) in db.query(VehicleCatalog.code).filter(VehicleCatalog.kind == kind, VehicleCatalog.active == True)}  # noqa: E712
