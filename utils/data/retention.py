"""Evidence retention: after `evidence_days`, the stored images are purged.

The evidence row itself stays, with a PURGED entry appended to its custody chain: the chain is
append-only and references the row, so deleting it would break the record of what existed and
who handled it. Evidence attached to an incident that is not resolved or closed is kept whole
(a case in progress is a legal hold). A small JSON note per purged item goes to `archive_path`.
"""

import json
import os
from datetime import timedelta
from pathlib import Path

from backend.db.database import SessionLocal
from backend.models.evidence import Evidence
from clock import utcnow

OPEN_CASE = ("open", "investigating", "new", "acknowledged", "verified_match", "officer_dispatched",
             "in_progress", "target_located")


class RetentionPolicy:
    def __init__(self, config: dict = None):
        cfg = config or {}
        self.enabled = cfg.get("enabled", False)
        self.evidence_days = cfg.get("evidence_days", 90)
        self.archive_path = Path(cfg.get("archive_path", "evidence/archive")) if cfg.get("archive_path", True) else None
        self.dry_run = cfg.get("dry_run", False)

    def run(self) -> dict:
        if not self.enabled:
            return {"status": "disabled", "message": "Retention policy is disabled"}
        from backend.models.incident import Incident
        from backend.services.custody import append_custody

        cutoff = utcnow() - timedelta(days=self.evidence_days)
        stats = {"purged": 0, "held": 0, "errors": 0, "freed_bytes": 0}
        db = SessionLocal()
        try:
            held = {i for (i,) in db.query(Incident.evidence_id)
                    .filter(Incident.evidence_id.isnot(None), Incident.status.in_(OPEN_CASE))}
            expired = (db.query(Evidence)
                       .filter(Evidence.timestamp < cutoff,
                               (Evidence.frame_data.isnot(None)) | (Evidence.roi_data.isnot(None)))
                       .all())
            for ev in expired:
                if ev.id in held:
                    stats["held"] += 1
                    continue
                size = len(ev.frame_data or b"") + len(ev.roi_data or b"")
                if self.dry_run:
                    stats["purged"] += 1
                    stats["freed_bytes"] += size
                    continue
                try:
                    self._note(ev)
                    ev.frame_data = ev.roi_data = None
                    append_custody(db, ev.id, "PURGED", actor="RETENTION",
                                   details=f"images removed after {self.evidence_days} days")
                    db.commit()
                    stats["purged"] += 1
                    stats["freed_bytes"] += size
                except Exception as e:
                    print(f"Retention error evidence {ev.id}: {e}")
                    stats["errors"] += 1
                    db.rollback()
            return {"status": "completed", "cutoff": cutoff.isoformat(), "retention_days": self.evidence_days, **stats}
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            db.close()

    def _note(self, ev: Evidence) -> None:
        if not self.archive_path:
            return
        self.archive_path.mkdir(parents=True, exist_ok=True)
        note = {
            "id": ev.id, "timestamp": ev.timestamp.isoformat() if ev.timestamp else None,
            "camera_location": ev.camera_location, "track_id": ev.track_id, "person_name": ev.person_name,
            "is_criminal": ev.is_criminal, "weapon_present": ev.weapon_present, "category": ev.category,
            "content_sha256": ev.content_sha256, "purged_at": utcnow().isoformat(),
        }
        with open(self.archive_path / f"evidence_{ev.id}.json", "w") as f:
            json.dump(note, f, indent=2)


def run_retention(dry_run: bool = False) -> dict:
    import yaml
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root
    config_path = os.path.join(base_dir, "config", "config.yaml")
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        retention_cfg = dict(cfg.get("retention", {}))
        retention_cfg["dry_run"] = dry_run
        if not os.path.isabs(str(retention_cfg.get("archive_path", "evidence/archive"))):
            retention_cfg["archive_path"] = os.path.join(base_dir, retention_cfg.get("archive_path", "evidence/archive"))
        return RetentionPolicy(retention_cfg).run()
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import sys
    print(json.dumps(run_retention(dry_run="--dry-run" in sys.argv), indent=2))
