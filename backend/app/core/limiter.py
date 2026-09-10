import time
from collections import defaultdict

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

_rate_store: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str, limit: int, window_s: int = 60) -> bool:
    now = time.monotonic()
    bucket = _rate_store[key]
    cutoff = now - window_s
    while bucket and bucket[0] <= cutoff:
        bucket.pop(0)
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


def is_limited(request, limit: int, window_s: int = 60, prefix: str = "") -> bool:
    client = getattr(request.client, "host", "unknown") if request.client else "unknown"
    key = f"{prefix}:{client}" if prefix else client
    return check_rate_limit(key, limit, window_s)
