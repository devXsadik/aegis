import os
import yaml
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.auth.auth import admin_only
from backend.models.user import User
from backend.models.config_entry import ConfigEntry
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/config", tags=["config"])


class ConfigResponse(BaseModel):
    key: str
    value: Optional[str]
    description: Optional[str]

    class Config:
        from_attributes = True


class ConfigUpdate(BaseModel):
    value: str


@router.get("/", response_model=List[ConfigResponse])
def list_config(
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    return db.query(ConfigEntry).all()


@router.get("/{key}", response_model=ConfigResponse)
def get_config(
    key: str,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    entry = db.query(ConfigEntry).filter(ConfigEntry.key == key).first()
    if not entry:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    return entry


@router.put("/{key}")
def update_config(
    key: str,
    body: ConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    entry = db.query(ConfigEntry).filter(ConfigEntry.key == key).first()
    if not entry:
        entry = ConfigEntry(key=key, value=body.value)
        db.add(entry)
    else:
        entry.value = body.value
    entry.updated_by = user.id
    db.commit()
    return {"status": "updated", "key": key, "value": body.value}


@router.post("/reload")
def reload_config(user: User = Depends(admin_only)):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "config.yaml")
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="config.yaml not found")
    return {"status": "reloaded", "keys_loaded": list(cfg.keys()) if cfg else []}
