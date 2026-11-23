"""Security policy applied to every authenticated request (spec 14):

  MFA_REQUIRED=true          users without two-step sign-in may only reach the 2FA set-up,
                             /auth/me and sign-out until they turn it on
  ADMIN_IP_ALLOWLIST=CIDRs   admin accounts work only from these networks
                             (e.g. "10.20.0.0/16,192.168.1.10/32"); empty = anywhere"""

from __future__ import annotations

import ipaddress
import os
from typing import Optional

from fastapi import HTTPException, Request

MFA_EXEMPT = ("/api/v1/auth/2fa", "/api/v1/auth/me", "/api/v1/auth/logout", "/api/v1/auth/refresh")


def mfa_required() -> bool:
    return os.getenv("MFA_REQUIRED", "false").lower() in ("1", "true", "yes")


def mfa_setup_needed(user) -> bool:
    return mfa_required() and not bool(getattr(user, "totp_enabled", False))


def _allowlist():
    raw = os.getenv("ADMIN_IP_ALLOWLIST", "").strip()
    if not raw:
        return None
    nets = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            nets.append(ipaddress.ip_network(part, strict=False))
    return nets


def client_ip(request: Request) -> Optional[str]:
    # Behind a reverse proxy, set it to pass the real address (uvicorn --proxy-headers).
    return request.client.host if request.client else None


def enforce(user, request: Request) -> None:
    path = request.url.path
    if mfa_setup_needed(user) and not path.startswith(MFA_EXEMPT):
        raise HTTPException(status_code=403, detail={"message": "Turn on two-step sign-in to continue",
                                                     "mfa_setup_required": True})
    nets = _allowlist()
    if nets is not None and user.role == "admin":
        ip = client_ip(request)
        try:
            addr = ipaddress.ip_address(ip) if ip else None
        except ValueError:
            addr = None
        if addr is None or not any(addr in n for n in nets):
            raise HTTPException(status_code=403, detail="Admin access is only allowed from approved networks")
