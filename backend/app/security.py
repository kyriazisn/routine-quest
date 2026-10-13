import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from threading import Lock

# Unambiguous alphabet for codes a human may read aloud or type (no 0/O, 1/I/L)
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_claim_code(length: int = 10) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


class RateLimiter:
    """
    In-process sliding-window limiter. Good enough for a single API instance;
    behind a load balancer use the reverse proxy / a shared store instead (docs/05 §Security).
    """

    def __init__(self, limit: int, window_s: int):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


magic_link_limiter = RateLimiter(limit=5, window_s=3600)
claim_limiter = RateLimiter(limit=20, window_s=600)
