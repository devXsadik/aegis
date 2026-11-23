"""Where case-evidence files live: this server's disk (default) or S3-compatible object storage.

EVIDENCE_STORE=s3 puts every file in a bucket (AWS S3, MinIO, Ceph, Wasabi …), so several API
servers share it and the disk of one machine is no longer the only copy:

    S3_BUCKET            bucket name (required)
    S3_ENDPOINT_URL      e.g. http://minio:9000 for MinIO; empty for AWS
    S3_REGION            default us-east-1
    S3_ACCESS_KEY / S3_SECRET_KEY   (or the usual AWS_* variables / instance role)
    S3_PREFIX            key prefix, default "evidence/"
    S3_OBJECT_LOCK_DAYS  write-once retention: each object is stored in COMPLIANCE mode for this
                         many days (bucket must be created with Object Lock enabled). Nobody, not
                         even an admin with the keys, can delete or overwrite it before then.

Files are sealed (AES-GCM) before they leave this process, so the storage provider only ever
sees ciphertext. Records keep the location they were written to (a path, or s3://bucket/key):
switching stores later leaves old files readable where they are.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Optional

from clock import utcnow

_client = None


class StoreError(RuntimeError):
    pass


def backend() -> str:
    return (os.getenv("EVIDENCE_STORE") or "local").strip().lower()


def _s3():
    global _client
    if _client is None:
        try:
            import boto3
        except ImportError as e:  # pragma: no cover - depends on the install
            raise StoreError("EVIDENCE_STORE=s3 needs boto3 (pip install boto3)") from e
        _client = boto3.client(
            "s3", endpoint_url=os.getenv("S3_ENDPOINT_URL") or None, region_name=os.getenv("S3_REGION") or "us-east-1",
            aws_access_key_id=os.getenv("S3_ACCESS_KEY") or None, aws_secret_access_key=os.getenv("S3_SECRET_KEY") or None)
    return _client


def set_client(client) -> None:
    """Tests install a fake."""
    global _client
    _client = client


def _bucket() -> str:
    b = os.getenv("S3_BUCKET", "").strip()
    if not b:
        raise StoreError("EVIDENCE_STORE=s3 needs S3_BUCKET")
    return b


def put(name: str, blob: bytes, local_dir: Path) -> str:
    """Store `blob` under `name` (content-addressed, e.g. ab/abcdef….bin); returns its location."""
    if backend() == "s3":
        bucket, key = _bucket(), os.getenv("S3_PREFIX", "evidence/") + name
        c = _s3()
        if _exists_s3(c, bucket, key):
            return f"s3://{bucket}/{key}"
        extra = {}
        days = int(os.getenv("S3_OBJECT_LOCK_DAYS", "0") or 0)
        if days > 0:
            extra = {"ObjectLockMode": "COMPLIANCE", "ObjectLockRetainUntilDate": utcnow() + timedelta(days=days)}
        c.put_object(Bucket=bucket, Key=key, Body=blob, ContentType="application/octet-stream", **extra)
        return f"s3://{bucket}/{key}"
    path = local_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(path)
    return str(path)


def _exists_s3(c, bucket: str, key: str) -> bool:
    try:
        c.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001 - 404 (or no permission): write it
        return False


def get(location: str) -> bytes:
    if location.startswith("s3://"):
        bucket, _, key = location[5:].partition("/")
        return _s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    return Path(location).read_bytes()


def health() -> dict:
    out: dict = {"backend": backend()}
    if backend() == "s3":
        try:
            _s3().head_bucket(Bucket=_bucket())
            out["ok"] = True
        except Exception as e:  # noqa: BLE001
            out.update(ok=False, error=str(e)[:200])
        out["object_lock_days"] = int(os.getenv("S3_OBJECT_LOCK_DAYS", "0") or 0)
    else:
        out["ok"] = True
    return out


def describe(location: Optional[str]) -> str:
    return "object storage" if (location or "").startswith("s3://") else "server disk"
