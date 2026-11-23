"""Officer evidence: sealed storage, SHA-256 identity, versioning (originals never change),
admin-only soft delete, and a hash-chained custody record for every upload / view / download."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from backend.models.case_evidence import EvidenceItem, EvidenceItemCustody
from backend.models.user import User
from backend.utils.at_rest import seal, unseal
from clock import utcnow

MAX_BYTES = int(os.getenv("EVIDENCE_MAX_MB", "100")) * 1024 * 1024
TYPES = {
    "image": ("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"),
    "video": ("video/mp4", "video/quicktime", "video/webm", "video/x-matroska", "video/3gpp"),
    "audio": ("audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/webm", "audio/ogg", "audio/aac"),
    "pdf": ("application/pdf",),
}
MAGIC = {b"\xff\xd8\xff": "image", b"\x89PNG": "image", b"%PDF": "pdf", b"RIFF": "media", b"ID3": "audio",
         b"\x1aE\xdf\xa3": "video", b"OggS": "audio"}


class EvidenceError(ValueError):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def uploads_dir() -> Path:
    from paths import UPLOADS_DIR
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOADS_DIR


def kind_of(content_type: str, data: bytes) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    for kind, types in TYPES.items():
        if ct in types:
            break
    else:
        raise EvidenceError(f"File type {ct or 'unknown'} is not accepted (images, video, audio, PDF)", 415)
    head = data[:12]
    if kind == "pdf" and not head.startswith(b"%PDF"):
        raise EvidenceError("The file says PDF but is not one", 415)
    if kind == "image" and ct in ("image/jpeg", "image/png") and not (head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG")):
        raise EvidenceError("The file says image but is not one", 415)
    if kind == "video" and ct == "video/mp4" and b"ftyp" not in data[:64]:
        raise EvidenceError("The file says MP4 video but is not one", 415)
    return kind


def store(data: bytes) -> Tuple[str, bool, str]:
    """Write sealed bytes under the SHA-256 of the original. Returns (path, encrypted, sha256)."""
    sha = hashlib.sha256(data).hexdigest()
    folder = uploads_dir() / sha[:2]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha}.bin"
    blob, enc = seal(data)
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(path)
    return str(path), enc, sha


def read(item: EvidenceItem) -> bytes:
    data = unseal(Path(item.storage_path).read_bytes(), item.encrypted)
    if hashlib.sha256(data).hexdigest() != item.sha256:
        raise EvidenceError("Stored file does not match its SHA-256: integrity failure", 500)
    return data


def custody(db: Session, item: EvidenceItem, action: str, user: Optional[User], details: str = "",
            ip: Optional[str] = None) -> EvidenceItemCustody:
    prev = (db.query(EvidenceItemCustody.record_hash).filter(EvidenceItemCustody.item_id == item.id)
            .order_by(EvidenceItemCustody.id.desc()).first())
    prev_hash = prev[0] if prev else None
    at = utcnow()
    actor = user.username if user else "SYSTEM"
    record = hashlib.sha256(f"{item.id}|{action}|{actor}|{item.sha256}|{prev_hash or ''}|{details}|{at.isoformat()}".encode()).hexdigest()
    row = EvidenceItemCustody(item_id=item.id, action=action, actor=actor, actor_id=user.id if user else None,
                              sha256=item.sha256, prev_hash=prev_hash, record_hash=record, details=details,
                              ip_address=ip, at=at)
    db.add(row)
    return row


def verify_chain(db: Session, item: EvidenceItem) -> dict:
    rows = db.query(EvidenceItemCustody).filter(EvidenceItemCustody.item_id == item.id).order_by(EvidenceItemCustody.id).all()
    prev = None
    for r in rows:
        at = r.at.replace(tzinfo=None) if r.at.tzinfo else r.at
        expect = hashlib.sha256(f"{item.id}|{r.action}|{r.actor}|{r.sha256}|{prev or ''}|{r.details or ''}|{at.isoformat()}".encode()).hexdigest()
        if r.prev_hash != prev or r.record_hash != expect:
            return {"ok": False, "broken_at": r.id, "records": len(rows)}
        prev = r.record_hash
    try:
        read(item)
        file_ok = True
    except Exception:
        file_ok = False
    return {"ok": file_ok, "chain_ok": True, "file_ok": file_ok, "records": len(rows)}


def create(db: Session, *, incident_id: int, data: bytes, content_type: str, filename: Optional[str], user: Optional[User],
           description: Optional[str] = None, location: Optional[str] = None, lat=None, lng=None, captured_at=None,
           device_info: Optional[str] = None, source: str = "upload", camera_id: Optional[str] = None,
           parent: Optional[EvidenceItem] = None, ip: Optional[str] = None, kind: Optional[str] = None) -> EvidenceItem:
    if not data:
        raise EvidenceError("Empty file")
    if len(data) > MAX_BYTES:
        raise EvidenceError(f"File larger than {MAX_BYTES // (1024 * 1024)} MB", 413)
    kind = kind or kind_of(content_type, data)
    sha = hashlib.sha256(data).hexdigest()
    dup = db.query(EvidenceItem).filter(EvidenceItem.sha256 == sha, EvidenceItem.deleted_at.is_(None)).first()
    if dup and parent is None:
        raise EvidenceError(f"Identical file already stored as {dup.ref} (incident #{dup.incident_id})", 409)
    path, enc, _ = store(data)
    item = EvidenceItem(ref=f"EV-{uuid.uuid4().hex[:8].upper()}", incident_id=incident_id, kind=kind,
                        description=description, location=location, lat=lat, lng=lng, captured_at=captured_at,
                        camera_id=camera_id, original_filename=(filename or "")[:255] or None, content_type=content_type,
                        size=len(data), sha256=sha, storage_path=path, encrypted=enc, source=source,
                        uploaded_by=user.id if user else None, device_info=(device_info or "")[:300] or None,
                        version=(parent.version + 1) if parent else 1, parent_id=parent.id if parent else None,
                        faces_status="pending" if kind in ("image", "video", "snapshot") else "skipped")
    db.add(item)
    db.flush()
    custody(db, item, "VERSIONED" if parent else ("CAPTURED" if source == "system" else "UPLOADED"), user,
            f"{filename or ''} {len(data)} bytes" + (f" (v{item.version} of {parent.ref})" if parent else ""), ip)
    return item


def attach_snapshot(db: Session, incident_id: int, data: bytes, camera_id: Optional[str], description: str) -> Optional[EvidenceItem]:
    """System-captured alert snapshot → incident evidence (skips exact duplicates)."""
    try:
        return create(db, incident_id=incident_id, data=data, content_type="image/jpeg", filename=None, user=None,
                      description=description, source="system", camera_id=camera_id, captured_at=utcnow(), kind="snapshot")
    except EvidenceError:
        return None
