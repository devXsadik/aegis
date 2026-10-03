"""Runtime configuration entries (thresholds, alert rules)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.auth import operator_or_admin, admin_only
from backend.db.database import get_db
from backend.models.config_entry import ConfigEntry
from backend.models.user import User

router = APIRouter(prefix="/config", tags=["config"])


class ConfigEntryIn(BaseModel):
    value: str
    description: Optional[str] = None


class ConfigEntryOut(BaseModel):
    key: str
    value: Optional[str]
    description: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/", response_model=list[ConfigEntryOut])
def list_config(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    return db.query(ConfigEntry).order_by(ConfigEntry.key).all()


@router.get("/{key}")
def get_config(key: str, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    entry = db.query(ConfigEntry).filter(ConfigEntry.key == key).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Config key not found")
    return {"key": entry.key, "value": entry.value, "description": entry.description}


@router.put("/{key}")
def upsert_config(
    key: str,
    body: ConfigEntryIn,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    entry = db.query(ConfigEntry).filter(ConfigEntry.key == key).first()
    if entry:
        entry.value = body.value
        entry.description = body.description or entry.description
        entry.updated_by = admin.id
    else:
        entry = ConfigEntry(key=key, value=body.value, description=body.description, updated_by=admin.id)
        db.add(entry)
    db.commit()
    return {"status": "saved", "key": key}


@router.get("/thresholds/all")
def get_thresholds(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    """Merged threshold map for dashboard Settings page."""
    defaults = {
        "confidence_threshold": "0.5",
        "face_tolerance": "0.45",
        "weapon_conf_threshold": "0.4",
        "loiter_seconds": "15",
        "crowd_threshold": "5",
    }
    for row in db.query(ConfigEntry).filter(ConfigEntry.key.like("threshold.%")).all():
        defaults[row.key.replace("threshold.", "")] = row.value
    return defaults
