"""Optional public-demo daily run cap.

Active only when DEMO_BUCKET is set (the deployed app gets one; local/dev
runs don't, so nothing is required of the operator's environment). The
counter is a single GCS object per UTC day - get-then-put is not atomic, but
a demo-scale race just means the day's count can land a run or two over the
soft limit, which is acceptable here.

Cloud Run has no built-in per-IP rate limiting without a load balancer +
Cloud Armor, so a second, per-IP counter (keyed off the caller-supplied
client IP) is checked alongside the global one - cheap and sufficient at
demo traffic.
"""

import os
from datetime import datetime, timezone

from google.api_core.exceptions import NotFound

DAILY_LIMIT = int(os.environ.get("DEMO_DAILY_LIMIT", "100"))
PER_IP_DAILY_LIMIT = int(os.environ.get("DEMO_PER_IP_DAILY_LIMIT", "10"))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _check_and_increment_one(bucket, blob_name: str, limit: int) -> tuple[bool, int]:
    blob = bucket.blob(blob_name)
    try:
        used = int(blob.download_as_bytes().decode() or "0")
    except NotFound:
        used = 0
    except Exception:
        return True, 0
    if used >= limit:
        return False, used
    blob.upload_from_string(str(used + 1))
    return True, used + 1


def check_and_increment(client_ip: str | None = None) -> tuple[bool, int]:
    """Returns (allowed, runs_used_today) and increments the counter(s).

    With no DEMO_BUCKET (local/dev), every run is allowed. Quota-store
    outages fail open - the cap is a soft cost guard, never a demo breaker.
    When client_ip is given, a per-IP counter is checked in addition to the
    global one; either being over its limit blocks the run.
    """
    bucket_name = os.environ.get("DEMO_BUCKET", "")
    if not bucket_name:
        return True, 0
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    if client_ip:
        allowed, used = _check_and_increment_one(
            bucket, f"demo-runs/ip-{client_ip}/{_today()}", PER_IP_DAILY_LIMIT
        )
        if not allowed:
            return allowed, used

    return _check_and_increment_one(bucket, f"demo-runs/{_today()}", DAILY_LIMIT)
