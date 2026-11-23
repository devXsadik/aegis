"""Evidence package: one incident, everything about it, in a ZIP that proves it is intact.

    README.txt          what is inside and how to check it
    incident.json       the case: details, notes, timeline
    alert.json          the alert it came from (if any)
    evidence/<id>_frame.jpg, <id>_roi.jpg, <id>.json   stills (decrypted) + hashes + custody chain
    captures/<id>.jpg   zoomed stills taken while the subject was in view
    video/<name>.mp4    the original recordings around the alert, unaltered
    MANIFEST.sha256     SHA-256 of every file above (`sha256sum -c MANIFEST.sha256`)
    SIGNATURE.txt       HMAC-SHA256 of the manifest with this system's key: proves it came from here

Exporting appends an EXPORTED record to each still's custody chain.
"""

import hashlib
import hmac
import io
import json
import os
import zipfile
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.user import User

NEAR_ALERT = timedelta(minutes=2)        # stills from the alert's camera this close to it
VIDEO_AROUND = timedelta(seconds=60)     # recordings covering this window around the alert
MAX_STILLS = 20
MAX_VIDEOS = 5


def _key() -> bytes:
    explicit = os.getenv("EVIDENCE_SIGNING_KEY")
    if explicit:
        return explicit.encode()
    # Derived, so the raw session key never signs anything directly.
    return hmac.new(os.getenv("SECRET_KEY", "").encode(), b"aegis-evidence-package", hashlib.sha256).digest()


def sign(manifest: bytes) -> str:
    return hmac.new(_key(), manifest, hashlib.sha256).hexdigest()


def _iso(dt):
    return dt.isoformat() if dt else None


def _jpeg(ev, data: Optional[bytes]) -> Optional[bytes]:
    if not data:
        return None
    if ev.encrypted:
        from backend.utils.encryption import EncryptionManager
        return EncryptionManager().decrypt(data)
    return data


MAX_ITEMS = 200


def _thumb(data: bytes) -> Optional[bytes]:
    """Small JPEG for the report (identification only; the original is in the package)."""
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        h, w = img.shape[:2]
        s = 480 / max(h, w)
        if s < 1:
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None
    except Exception:
        return None


def _case_report(db: Session, inc, alert, stills: dict, items_info: list, actor) -> bytes:
    from backend.models.custody import CustodyRecord
    from backend.models.dispatch import IncidentMessage
    from backend.models.incident import IncidentAssignment
    from backend.models.jurisdiction import Jurisdiction, OfficerProfile
    from backend.services import case_report, reports
    from clock import utcnow
    events = sorted(inc.events, key=lambda e: e.created_at or inc.created_at)
    officers = []
    for a in db.query(IncidentAssignment).filter(IncidentAssignment.incident_id == inc.id).order_by(IncidentAssignment.assigned_at):
        u, p = db.get(User, a.user_id), db.get(OfficerProfile, a.user_id)
        officers.append({"name": (p.full_name if p and p.full_name else (u.username if u else a.user_id)),
                         "rank": p.rank if p else None, "badge_no": p.badge_no if p else None, "state": a.state,
                         "assigned_at": a.assigned_at, "out_of_area": a.out_of_area})
    area = db.get(Jurisdiction, inc.jurisdiction_id) if inc.jurisdiction_id else None
    still_rows = [{"id": e.id, "time": e.timestamp, "camera": e.camera_location, "sha256": e.content_sha256,
                   "records": db.query(CustodyRecord).filter(CustodyRecord.evidence_id == e.id).count()} for e in stills.values()]
    return case_report.build_pdf({
        "incident": inc, "alert": alert, "events": events, "notes": sorted(inc.notes, key=lambda n: n.created_at or inc.created_at),
        "messages": db.query(IncidentMessage).filter(IncidentMessage.incident_id == inc.id).order_by(IncidentMessage.created_at).all(),
        "officers": officers, "stages": reports.stage_times(inc, events), "area": area.name_en if area else None,
        "stills": still_rows, "items": items_info, "actor": actor.username, "made": utcnow(),
    })


def build_package(db: Session, incident_id: int, actor) -> tuple[str, bytes]:
    """(file name, ZIP bytes). Raises LookupError when the incident does not exist."""
    from backend.models.alert import Alert
    from backend.models.capture import AlertCapture
    from backend.models.custody import CustodyRecord
    from backend.models.evidence import Evidence
    from backend.models.incident import Incident
    from backend.models.recording import RecordingClip
    from backend.services.custody import append_custody, sha256_bytes
    from backend.auth.guards import safe_media_path
    from clock import utcnow
    from paths import RECORDINGS_DIR, ROOT

    inc = db.query(Incident).filter(Incident.id == incident_id).first()
    if not inc:
        raise LookupError("Incident not found")
    alert = db.query(Alert).filter(Alert.id == inc.alert_id).first() if inc.alert_id else None
    anchor = (alert.timestamp if alert else inc.created_at).replace(tzinfo=None)
    camera_id = (alert.camera_id if alert else None) or inc.camera_id
    location = (alert.camera_location if alert else None) or inc.camera_location

    files: dict[str, bytes] = {}
    files["incident.json"] = json.dumps({
        "ticket_id": inc.ticket_id, "title": inc.title, "description": inc.description,
        "type": inc.incident_type, "priority": inc.priority, "status": inc.status,
        "camera_id": inc.camera_id, "camera_location": inc.camera_location, "lat": inc.lat, "lng": inc.lng,
        "person_name": inc.person_name, "plate_number": inc.plate_number,
        "assigned_to": inc.assigned_name, "created_by": inc.created_by_name,
        "created_at": _iso(inc.created_at), "resolved_at": _iso(inc.resolved_at),
        "notes": [{"at": _iso(n.created_at), "by": n.author_name, "text": n.body} for n in inc.notes],
        "timeline": [{"at": _iso(e.created_at), "by": e.actor, "event": e.event_type, "message": e.message}
                     for e in sorted(inc.events, key=lambda e: e.created_at or anchor)],
    }, indent=2).encode()
    if alert:
        files["alert.json"] = json.dumps({
            "id": alert.id, "type": alert.alert_type, "severity": alert.severity, "time": _iso(alert.timestamp),
            "camera_id": alert.camera_id, "camera_location": alert.camera_location, "track_id": alert.track_id,
            "person_name": alert.person_name, "plate_number": alert.plate_number, "message": alert.message,
            "review_status": alert.review_status, "review_note": alert.review_note,
            "acknowledged_at": _iso(alert.acknowledged_at), "escalated_at": _iso(alert.escalated_at),
        }, indent=2).encode()

    # Stills: the incident's own evidence, plus what the alert's camera saved around the alert.
    q = db.query(Evidence)
    near = q.filter(Evidence.timestamp >= anchor - NEAR_ALERT, Evidence.timestamp <= anchor + NEAR_ALERT)
    if location:
        near = near.filter(Evidence.camera_location == location)
    stills = {e.id: e for e in near.order_by(Evidence.timestamp).limit(MAX_STILLS)}
    if inc.evidence_id and inc.evidence_id not in stills:
        own = q.filter(Evidence.id == inc.evidence_id).first()
        if own:
            stills[own.id] = own
    for ev in stills.values():
        frame, roi = _jpeg(ev, ev.frame_data), _jpeg(ev, ev.roi_data)
        if frame:
            files[f"evidence/{ev.id}_frame.jpg"] = frame
        if roi:
            files[f"evidence/{ev.id}_roi.jpg"] = roi
        append_custody(db, ev.id, "EXPORTED", actor=actor.username, actor_id=actor.id,
                       details=f"evidence package {inc.ticket_id}")
        chain = db.query(CustodyRecord).filter(CustodyRecord.evidence_id == ev.id).order_by(CustodyRecord.id).all()
        files[f"evidence/{ev.id}.json"] = json.dumps({
            "id": ev.id, "time": _iso(ev.timestamp), "camera_location": ev.camera_location, "track_id": ev.track_id,
            "person_name": ev.person_name, "category": ev.category, "reasons": ev.reasons,
            "stored_sha256": ev.content_sha256,
            "frame_sha256_now": sha256_bytes(ev.frame_data) if ev.frame_data else None,
            "custody": [{"at": _iso(c.created_at), "action": c.action, "actor": c.actor,
                         "sha256": c.sha256_hash, "prev_hash": c.prev_hash, "record_hash": c.record_hash,
                         "details": c.details} for c in chain],
        }, indent=2).encode()

    # Case evidence (uploads, field photos, system snapshots): original files + custody chain.
    from backend.models.case_evidence import EvidenceItem
    from backend.services import case_evidence as cev
    items_info = []
    for item in (db.query(EvidenceItem).filter(EvidenceItem.incident_id == inc.id, EvidenceItem.deleted_at.is_(None))
                 .order_by(EvidenceItem.uploaded_at).limit(MAX_ITEMS)):
        try:
            data = cev.read(item)
        except Exception:
            data = None
        ext = (item.original_filename or "").rsplit(".", 1)[-1][:8] if "." in (item.original_filename or "") else "bin"
        if data is not None:
            files[f"case_evidence/{item.ref}.{ext}"] = data
        cev.custody(db, item, "EXPORTED", actor, f"evidence package {inc.ticket_id}")
        check = cev.verify_chain(db, item)
        chain = db.query(cev.EvidenceItemCustody).filter(cev.EvidenceItemCustody.item_id == item.id).order_by(cev.EvidenceItemCustody.id).all()
        files[f"case_evidence/{item.ref}.json"] = json.dumps({
            "ref": item.ref, "kind": item.kind, "filename": item.original_filename, "content_type": item.content_type,
            "description": item.description, "location": item.location, "captured_at": _iso(item.captured_at),
            "uploaded_at": _iso(item.uploaded_at), "sha256": item.sha256, "file_present": data is not None,
            "custody": [{"at": _iso(c.at), "action": c.action, "actor": c.actor, "sha256": c.sha256,
                         "prev_hash": c.prev_hash, "record_hash": c.record_hash, "details": c.details} for c in chain],
        }, indent=2).encode()
        uploader = db.get(User, item.uploaded_by) if item.uploaded_by else None
        items_info.append({"ref": item.ref, "kind": item.kind, "filename": item.original_filename, "description": item.description,
                           "uploaded_at": item.uploaded_at, "by": uploader.username if uploader else None, "sha256": item.sha256,
                           "chain_ok": bool(check.get("chain_ok")) and bool(check.get("file_ok")), "records": check.get("records", 0),
                           "thumb": _thumb(data) if data is not None and item.kind == "image" else None})

    caps = db.query(AlertCapture)
    caps = caps.filter(AlertCapture.alert_id == alert.id) if alert else caps.filter(False)
    for c in caps.order_by(AlertCapture.timestamp).limit(MAX_STILLS):
        from backend.utils.at_rest import unseal
        files[f"captures/{c.id}.jpg"] = unseal(c.image_data, c.encrypted)

    if camera_id:
        clips = (db.query(RecordingClip)
                 .filter(RecordingClip.camera_id == camera_id,
                         RecordingClip.started_at <= anchor + VIDEO_AROUND,
                         RecordingClip.ended_at >= anchor - VIDEO_AROUND)
                 .order_by(RecordingClip.started_at).limit(MAX_VIDEOS).all())
        for clip in clips:
            try:
                path = safe_media_path(clip.file_path, RECORDINGS_DIR, ROOT)
            except Exception:
                continue
            if path.exists():
                files[f"video/{path.name}"] = path.read_bytes()

    files["CASE_REPORT.pdf"] = _case_report(db, inc, alert, stills, items_info, actor)
    manifest = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())).encode()
    made = utcnow()
    readme = (
        f"Evidence package {inc.ticket_id} — {inc.title}\n"
        f"Exported {made.isoformat()}Z by {actor.username}.\n\n"
        f"{len(stills)} still(s), {sum(n.startswith('captures/') for n in files)} capture(s), "
        f"{sum(n.startswith('video/') for n in files)} recording(s), "
        f"{sum(n.startswith('case_evidence/') and not n.endswith('.json') for n in files)} case evidence file(s).\n"
        "CASE_REPORT.pdf: the case for court — summary, response times, officers, evidence with SHA-256\n"
        "and custody-chain check, messages, notes and the full timeline.\n\n"
        "Check that nothing was changed:\n"
        "  1. In this folder run:  sha256sum -c MANIFEST.sha256   (every line must say OK)\n"
        "  2. SIGNATURE.txt is an HMAC-SHA256 of MANIFEST.sha256 made with this system's key; upload the\n"
        "     ZIP to the system's package check (POST /api/v1/incidents/package/verify) to confirm it.\n"
        "  3. evidence/<id>.json lists each still's custody chain; each record_hash links to the previous.\n\n"
        "Video is the original recording, unaltered (MPEG-4; plays in VLC).\n"
    ).encode()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", readme)
        for name, data in sorted(files.items()):
            z.writestr(name, data)
        z.writestr("MANIFEST.sha256", manifest)
        z.writestr("SIGNATURE.txt", f"HMAC-SHA256 {sign(manifest)}\n")
    return f"{inc.ticket_id}_evidence_package.zip", buf.getvalue()


def verify_package(data: bytes) -> dict:
    """Check a package: every file matches the manifest, and the manifest matches the signature."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        manifest = z.read("MANIFEST.sha256")
        signature = z.read("SIGNATURE.txt").decode().split()[-1]
    except (zipfile.BadZipFile, KeyError, IndexError, UnicodeDecodeError):
        return {"ok": False, "error": "Not an evidence package (no manifest or signature)"}
    listed, changed = set(), []
    for line in manifest.decode().splitlines():
        digest, name = line.split("  ", 1)
        listed.add(name)
        try:
            if hashlib.sha256(z.read(name)).hexdigest() != digest:
                changed.append(name)
        except KeyError:
            changed.append(name)
    extra = sorted(set(z.namelist()) - listed - {"README.txt", "MANIFEST.sha256", "SIGNATURE.txt"})
    signed = hmac.compare_digest(sign(manifest), signature)
    return {"ok": signed and not changed and not extra, "signature_valid": signed,
            "files_checked": len(listed), "changed_or_missing": changed, "unlisted_files": extra}
