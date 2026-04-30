"""
Report Generation Module
Generates PDF reports for incidents with evidence bundles
"""
from datetime import datetime
from typing import List, Optional, Dict
import json
from pathlib import Path


class ReportGenerator:
    """Generates incident reports and evidence bundles"""

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
        description: str = ""
    ) -> str:
        """
        Generate an incident report as JSON (can be converted to PDF later)
        Returns path to generated report
        """
        report = {
            'report_id': f"RPT_{incident_id}",
            'generated_at': datetime.utcnow().isoformat(),
            'incident': {
                'type': incident_type,
                'timestamp': timestamp.isoformat(),
                'camera_location': camera_location,
                'person_name': person_name,
                'track_id': track_id,
                'license_plate': plate_number,
                'description': description
            },
            'evidence_ids': evidence_ids or [],
            'recommendations': self._get_recommendations(incident_type)
        }

        report_path = self.output_dir / f"incident_{incident_id}.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        return str(report_path)

    def generate_daily_summary(self, date: datetime, stats: dict) -> str:
        """Generate daily activity summary report"""
        summary = {
            'date': date.date().isoformat(),
            'generated_at': datetime.utcnow().isoformat(),
            'statistics': stats,
            'summary': self._generate_summary_text(stats)
        }

        report_path = self.output_dir / f"daily_{date.date().isoformat()}.json"
        with open(report_path, 'w') as f:
            json.dump(summary, f, indent=2)

        return str(report_path)

    def create_evidence_bundle(
        self,
        incident_id: str,
        evidence_paths: List[str],
        metadata: Optional[Dict] = None
    ) -> str:
        """
        Create an evidence bundle (in production, this would create a ZIP)
        For now, creates a metadata file
        """
        bundle = {
            'incident_id': incident_id,
            'created_at': datetime.utcnow().isoformat(),
            'evidence_files': evidence_paths,
            'metadata': metadata or {}
        }

        bundle_path = self.output_dir / f"bundle_{incident_id}.json"
        with open(bundle_path, 'w') as f:
            json.dump(bundle, f, indent=2)

        return str(bundle_path)

    def _get_recommendations(self, incident_type: str) -> List[str]:
        """Get recommended actions based on incident type"""
        recommendations = {
            'CRIMINAL_DETECTED': [
                'Dispatch officer to location immediately',
                'Maintain visual contact with suspect',
                'Check for weapons or suspicious behavior',
                'Coordinate with nearby units for perimeter control'
            ],
            'WEAPON_DETECTED': [
                'Alert armed response team',
                'Establish safe distance',
                'Monitor for additional suspects',
                'Prepare for possible escalation'
            ],
            'SUSPICIOUS_VEHICLE': [
                'Run license plate through databases',
                'Monitor vehicle movement',
                'Check for wanted persons in vehicle',
                'Coordinate with traffic enforcement'
            ]
        }
        return recommendations.get(incident_type, [
            'Investigate further',
            'Document all observations',
            'Maintain surveillance'
        ])

    def _generate_summary_text(self, stats: dict) -> str:
        """Generate human-readable summary from stats"""
        lines = []
        lines.append(f"Total detections: {stats.get('total_detections', 0)}")
        lines.append(f"Unique persons: {stats.get('unique_persons', 0)}")
        lines.append(f"Criminals detected: {stats.get('criminals', 0)}")
        lines.append(f"Vehicles detected: {stats.get('vehicles', 0)}")
        lines.append(f"Alerts sent: {stats.get('alerts_sent', 0)}")
        return "\n".join(lines)
