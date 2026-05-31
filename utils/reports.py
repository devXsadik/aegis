import json
import os
from datetime import datetime
from typing import List, Optional, Dict
from pathlib import Path
from io import BytesIO

from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.models.evidence import Evidence
from backend.models.alert import Alert


class ReportGenerator:
    def __init__(self, output_dir: str = "reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def generate_incident_report(
        self,
        incident_id: str,
        incident_type: str,
        timestamp: datetime,
        camera_location: str,
        person_name: Optional[str] = None,
        track_id: Optional[int] = None,
        evidence_ids: List[int] = None,
        plate_number: Optional[str] = None,
        description: str = "",
        format: str = "json",
    ) -> str:
        report = {
            "report_id": f"RPT_{incident_id}",
            "generated_at": datetime.utcnow().isoformat(),
            "incident": {
                "type": incident_type,
                "timestamp": timestamp.isoformat(),
                "camera_location": camera_location,
                "person_name": person_name,
                "track_id": track_id,
                "license_plate": plate_number,
                "description": description,
            },
            "evidence_ids": evidence_ids or [],
            "recommendations": self._get_recommendations(incident_type),
        }

        if evidence_ids:
            db = SessionLocal()
            try:
                frames = db.query(Evidence).filter(Evidence.id.in_(evidence_ids)).all()
                report["evidence_details"] = [
                    {
                        "id": e.id,
                        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                        "person_name": e.person_name,
                        "is_criminal": e.is_criminal,
                        "weapon_present": e.weapon_present,
                        "has_frame": bool(e.frame_data),
                        "has_roi": bool(e.roi_data),
                    }
                    for e in frames
                ]
            finally:
                db.close()

        if format == "pdf":
            return self._generate_pdf(incident_id, report)
        report_path = self.output_dir / f"incident_{incident_id}.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        return str(report_path)

    def generate_daily_summary(self, date: datetime, stats: dict) -> str:
        summary = {
            "date": date.date().isoformat(),
            "generated_at": datetime.utcnow().isoformat(),
            "statistics": stats,
            "summary": self._generate_summary_text(stats),
        }
        report_path = self.output_dir / f"daily_{date.date().isoformat()}.json"
        with open(report_path, "w") as f:
            json.dump(summary, f, indent=2)
        return str(report_path)

    def create_evidence_bundle(self, incident_id: str, evidence_ids: List[int]) -> str:
        bundle = {"incident_id": incident_id, "created_at": datetime.utcnow().isoformat(), "evidence_ids": evidence_ids}
        db = SessionLocal()
        try:
            frames = db.query(Evidence).filter(Evidence.id.in_(evidence_ids)).all()
            bundle_dir = self.output_dir / f"bundle_{incident_id}"
            bundle_dir.mkdir(exist_ok=True)
            for ev in frames:
                if ev.frame_data:
                    (bundle_dir / f"frame_{ev.id}.jpg").write_bytes(ev.frame_data)
                if ev.roi_data:
                    (bundle_dir / f"roi_{ev.id}.jpg").write_bytes(ev.roi_data)
            bundle["path"] = str(bundle_dir)
            bundle["file_count"] = len(list(bundle_dir.iterdir()))
        finally:
            db.close()
        bundle_path = self.output_dir / f"bundle_{incident_id}.json"
        with open(bundle_path, "w") as f:
            json.dump(bundle, f, indent=2)
        return str(bundle_path)

    def _generate_pdf(self, incident_id: str, report: dict) -> str:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib import colors
        except ImportError:
            pdf_path = self.output_dir / f"incident_{incident_id}.json"
            with open(pdf_path, "w") as f:
                json.dump({**report, "_pdf_note": "Install reportlab for PDF generation"}, f, indent=2)
            return str(pdf_path)

        pdf_path = str(self.output_dir / f"incident_{incident_id}.pdf")
        doc = SimpleDocTemplate(pdf_path, pagesize=A4)
        styles = getSampleStyleSheet()
        elements = []

        elements.append(Paragraph(f"Incident Report: {report['report_id']}", styles["Title"]))
        elements.append(Spacer(1, 12))

        inc = report["incident"]
        data = [
            ["Type", inc["type"]],
            ["Timestamp", inc["timestamp"]],
            ["Location", inc["camera_location"]],
            ["Person", inc["person_name"] or "N/A"],
            ["License Plate", inc.get("license_plate") or "N/A"],
            ["Description", inc.get("description", "")],
        ]
        t = Table(data, colWidths=[120, 300])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.grey),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 12))

        elements.append(Paragraph("Recommendations", styles["Heading2"]))
        for r in report.get("recommendations", []):
            elements.append(Paragraph(f"&bull; {r}", styles["Normal"]))

        if report.get("evidence_details"):
            elements.append(Spacer(1, 12))
            elements.append(Paragraph("Evidence", styles["Heading2"]))
            for e in report["evidence_details"]:
                elements.append(Paragraph(
                    f"Evidence #{e['id']}: {e['person_name'] or 'Unknown'} | "
                    f"Criminal: {e['is_criminal']} | Weapon: {e['weapon_present']} | "
                    f"Frame: {'Yes' if e['has_frame'] else 'No'}",
                    styles["Normal"],
                ))

        doc.build(elements)
        return pdf_path

    def _get_recommendations(self, incident_type: str) -> List[str]:
        return {
            "CRIMINAL_DETECTED": [
                "Dispatch officer to location immediately",
                "Maintain visual contact with suspect",
                "Check for weapons or suspicious behavior",
            ],
            "WEAPON_DETECTED": [
                "Alert armed response team",
                "Establish safe distance",
                "Monitor for additional suspects",
            ],
            "SUSPICIOUS_VEHICLE": [
                "Run license plate through databases",
                "Monitor vehicle movement",
                "Coordinate with traffic enforcement",
            ],
        }.get(incident_type, ["Investigate further", "Document all observations"])

    def _generate_summary_text(self, stats: dict) -> str:
        lines = [
            f"Total detections: {stats.get('total_detections', 0)}",
            f"Criminals detected: {stats.get('criminals', 0)}",
            f"Weapons detected: {stats.get('weapons', 0)}",
            f"Vehicles detected: {stats.get('vehicles', 0)}",
            f"Alerts sent: {stats.get('alerts_sent', 0)}",
        ]
        return "\n".join(lines)


def generate_report(evidence_id: int, format: str = "json") -> str:
    db = SessionLocal()
    try:
        ev = db.query(Evidence).filter(Evidence.id == evidence_id).first()
        if not ev:
            return "Evidence not found"
        gen = ReportGenerator()
        path = gen.generate_incident_report(
            incident_id=str(ev.id),
            incident_type=(ev.category or "detection").upper(),
            timestamp=ev.timestamp or datetime.utcnow(),
            camera_location=ev.camera_location,
            person_name=ev.person_name,
            track_id=ev.track_id,
            evidence_ids=[ev.id],
            description=f"Auto-generated report for evidence #{ev.id}",
            format=format,
        )
        return path
    finally:
        db.close()
