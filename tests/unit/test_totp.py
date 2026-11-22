"""TOTP against the RFC 6238 test vectors, drift window and input checks."""

import base64

from backend.auth import totp

# RFC 6238 appendix B, SHA-1 secret "12345678901234567890"; the RFC shows 8 digits, we use the last 6.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


def test_rfc6238_vectors():
    for t, eight in ((59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924"), (2000000000, "69279037")):
        assert totp.code_at(RFC_SECRET, t // 30) == eight[-6:]


def test_accepts_one_step_of_drift_and_rejects_the_rest():
    s = totp.new_secret()
    now = 1_700_000_000
    code = totp.code_at(s, now // 30)
    assert totp.matching_step(s, code, now) == now // 30
    assert totp.matching_step(s, totp.code_at(s, now // 30 - 1), now) == now // 30 - 1     # phone 30 s behind
    assert totp.matching_step(s, totp.code_at(s, now // 30 - 3), now) is None
    assert totp.matching_step(s, "12345", now) is None and totp.matching_step(s, "abcdef", now) is None
    assert totp.matching_step(s, f"{code[:3]} {code[3:]}", now) == now // 30                # "123 456" works


def test_secret_round_trip_and_uri():
    s = totp.new_secret()
    assert totp.open_secret(totp.seal_secret(s)) == s and totp.seal_secret(s) != s
    uri = totp.provisioning_uri(s, "ops admin")
    assert uri.startswith("otpauth://totp/Aegis%3Aops%20admin?secret=") and "issuer=Aegis" in uri
