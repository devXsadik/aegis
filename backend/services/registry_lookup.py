"""Vehicle registration lookup (e.g. BRTA) through a connector the deployment configures.

Nothing is contacted until VEHICLE_REGISTRY_URL is set, which needs a data-sharing agreement with
the registry. Each lookup needs a reason and a case / GD / FIR number, is limited to supervisors,
investigators and admins, is audit-logged with both, and the answer is not stored anywhere by this
system (it is shown once, and the audit log keeps only that a lookup happened).

Connector contract (adapt the registry's API behind a small gateway if it differs):
    GET {VEHICLE_REGISTRY_URL}?plate=<canonical plate>
    Authorization: Bearer {VEHICLE_REGISTRY_TOKEN}
    → 200 {"plate", "registered_owner", "vehicle_class", "make", "model", "colour", "year",
           "registration_valid_until", "fitness_valid_until", "tax_token_valid_until",
           "reported_stolen": bool}
    → 404 when the plate is not registered
"""

from __future__ import annotations

import os
from typing import Optional

FIELDS = ("plate", "registered_owner", "vehicle_class", "make", "model", "colour", "year",
          "registration_valid_until", "fitness_valid_until", "tax_token_valid_until", "reported_stolen")


class RegistryError(RuntimeError):
    def __init__(self, message: str, code: int = 502):
        super().__init__(message)
        self.code = code


def configured() -> bool:
    return bool(os.getenv("VEHICLE_REGISTRY_URL", "").strip())


def lookup(plate: str) -> Optional[dict]:
    """The registry's record for `plate` (only FIELDS), or None when not registered."""
    url = os.getenv("VEHICLE_REGISTRY_URL", "").strip()
    if not url:
        raise RegistryError("No vehicle registry is connected (VEHICLE_REGISTRY_URL)", 503)
    import requests
    headers = {"Accept": "application/json"}
    token = os.getenv("VEHICLE_REGISTRY_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(url, params={"plate": plate}, headers=headers,
                         timeout=float(os.getenv("VEHICLE_REGISTRY_TIMEOUT", "8")))
    except requests.RequestException as e:
        raise RegistryError(f"Registry not reachable: {e.__class__.__name__}") from e
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise RegistryError(f"Registry answered {r.status_code}")
    body = r.json()
    return {k: body.get(k) for k in FIELDS}
