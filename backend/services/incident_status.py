"""Incident status state machine — the one source for the backend and the dashboard
(served at GET /api/v1/incidents/statuses).

A change is allowed only along TRANSITIONS. Closing or calling a false alarm needs a note,
and so does re-opening. Re-opening a closed / false-alarm incident is a command decision."""

from __future__ import annotations

from typing import Optional

STATUSES = [
    {"id": "new", "label": "New", "color": "danger", "desc": "Raised, nobody has looked yet."},
    {"id": "acknowledged", "label": "Acknowledged", "color": "info", "desc": "An operator has seen it."},
    {"id": "verified_match", "label": "Verified match", "color": "purple",
     "desc": "An operator confirmed the face / vehicle match."},
    {"id": "officer_dispatched", "label": "Officer dispatched", "color": "cyan",
     "desc": "Officers are on their way."},
    {"id": "in_progress", "label": "In progress", "color": "warn", "desc": "Being worked on."},
    {"id": "target_located", "label": "Target located", "color": "orange",
     "desc": "Officers have found the person or vehicle."},
    {"id": "resolved", "label": "Resolved", "color": "ok", "desc": "Handled; waiting to be closed."},
    {"id": "closed", "label": "Closed", "color": "muted", "desc": "Finished. Needs a closing note."},
    {"id": "false_alarm", "label": "False alarm", "color": "muted",
     "desc": "Not a real match or event. Needs a note; feeds accuracy stats."},
]
STATUS_IDS = [s["id"] for s in STATUSES]

TRANSITIONS: dict[str, list[str]] = {
    "new": ["acknowledged", "verified_match", "officer_dispatched", "in_progress", "false_alarm", "closed"],
    "acknowledged": ["verified_match", "officer_dispatched", "in_progress", "false_alarm", "closed"],
    "verified_match": ["officer_dispatched", "in_progress", "target_located", "false_alarm"],
    "officer_dispatched": ["in_progress", "target_located", "resolved", "false_alarm"],
    "in_progress": ["officer_dispatched", "target_located", "resolved", "false_alarm"],
    "target_located": ["in_progress", "resolved"],
    "resolved": ["closed", "in_progress"],
    "closed": ["in_progress"],
    "false_alarm": ["acknowledged"],
}

NOTE_REQUIRED = {"closed", "false_alarm"}
CONFIRM_REQUIRED = {"closed", "false_alarm"}
# Leaving these needs supervisor/admin and a note (re-opening a finished case).
COMMAND_ONLY_FROM = {"closed", "false_alarm"}
OPEN_STATUSES = frozenset(set(STATUS_IDS) - {"resolved", "closed", "false_alarm"})
DONE_STATUSES = frozenset({"resolved", "closed", "false_alarm"})

# Rows written before the v2 machine.
LEGACY = {"open": "new", "investigating": "in_progress"}


def normalize(status: Optional[str]) -> Optional[str]:
    return LEGACY.get(status, status) if status else status


class TransitionError(ValueError):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def check(current: str, target: str, *, role: str, note: Optional[str]) -> None:
    """Raise TransitionError if `role` may not move an incident from `current` to `target`."""
    current, target = normalize(current), normalize(target)
    if target not in STATUS_IDS:
        raise TransitionError(f"Unknown status '{target}'. Allowed: {', '.join(STATUS_IDS)}")
    if target == current:
        return
    if target not in TRANSITIONS.get(current, []):
        raise TransitionError(f"Cannot go from {current} to {target}", 409)
    if current in COMMAND_ONLY_FROM and role not in ("admin", "supervisor"):
        raise TransitionError("Only a supervisor or admin can re-open a finished incident", 403)
    if (target in NOTE_REQUIRED or current in COMMAND_ONLY_FROM) and not (note or "").strip():
        raise TransitionError(f"A note is required to move to {target}")


def spec() -> dict:
    return {
        "statuses": STATUSES,
        "transitions": TRANSITIONS,
        "note_required": sorted(NOTE_REQUIRED),
        "confirm_required": sorted(CONFIRM_REQUIRED),
        "command_only_from": sorted(COMMAND_ONLY_FROM),
    }
