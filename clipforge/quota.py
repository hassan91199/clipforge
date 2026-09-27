"""Optional public-demo daily run cap.

Active only when DEMO_BUCKET is set (the deployed app gets one; local/dev
runs don't, so nothing is required of the operator's environment). The
counter is a single S3 object per UTC day - get-then-put is not atomic, but
a demo-scale race just means the day's count can land a run or two over the
soft limit, which is acceptable here.

App Runner has no built-in per-IP rate limiting without a WAF in front of
it, so a second, per-IP counter (keyed off the caller-supplied client IP) is
checked alongside the global one - cheap and sufficient at demo traffic.

The instance's App Runner task role grants s3:GetObject/PutObject on this
bucket directly (see infra/modules/quota), so boto3 picks up credentials
ambiently - no explicit key needed.
"""

import os
from datetime import datetime, timezone

DAILY_LIMIT = int(os.environ.get("DEMO_DAILY_LIMIT", "100"))
PER_IP_DAILY_LIMIT = int(os.environ.get("DEMO_PER_IP_DAILY_LIMIT", "10"))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _check_and_increment_one(client, bucket: str, key: str, limit: int) -> tuple[bool, int]:
    try:
        used = int(client.get_object(Bucket=bucket, Key=key)["Body"].read().decode() or "0")
    except client.exceptions.NoSuchKey:
        used = 0
    except Exception:
        return True, 0
    if used >= limit:
        return False, used
    client.put_object(Bucket=bucket, Key=key, Body=str(used + 1).encode())
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

    import boto3

    client = boto3.client("s3")

    if client_ip:
        allowed, used = _check_and_increment_one(
            client, bucket_name, f"demo-runs/ip-{client_ip}/{_today()}", PER_IP_DAILY_LIMIT
        )
        if not allowed:
            return allowed, used

    return _check_and_increment_one(client, bucket_name, f"demo-runs/{_today()}", DAILY_LIMIT)
