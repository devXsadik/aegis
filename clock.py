"""Current UTC time as a naive datetime.

Drop-in for the deprecated `datetime.utcnow()`. Stays naive on purpose: DB columns and
stored ISO strings are naive UTC, and comparing aware with naive values raises.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
