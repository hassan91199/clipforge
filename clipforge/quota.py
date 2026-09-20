"""Optional public-demo daily run cap.

Active only when DEMO_BUCKET is set (the deployed app gets one; local/dev
runs don't, so nothing is required of the operator's environment). The
counter is a single S3 object per UTC day - get-then-put is not atomic, but
a demo-scale race just means the day's count can land a run or two over the
soft limit, which is acceptable here.
"""

import os
from datetime import datetime, timezone

DAILY_LIMIT = int(os.environ.get("DEMO_DAILY_LIMIT", "100"))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_and_increment() -> tuple[bool, int]:
    """Returns (allowed, runs_used_today) and increments the counter.

    With no DEMO_BUCKET (local/dev), every run is allowed. Quota-store
    outages fail open - the cap is a soft cost guard, never a demo breaker.
    """
    bucket = os.environ.get("DEMO_BUCKET", "")
    if not bucket:
        return True, 0
    import boto3

    s3 = boto3.client("s3")
    key = f"demo-runs/{_today()}"
    try:
        used = int(s3.get_object(Bucket=bucket, Key=key)["Body"].read() or b"0")
    except s3.exceptions.NoSuchKey:
        used = 0
    except Exception:
        return True, 0
    if used >= DAILY_LIMIT:
        return False, used
    s3.put_object(Bucket=bucket, Key=key, Body=str(used + 1).encode())
    return True, used + 1
