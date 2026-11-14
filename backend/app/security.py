"""Protection for a public deployment: owner login, rate limits and a daily AI budget.

Owner login
    Set OWNER_PASSWORD to require a login for every owner screen and API. Customer pages
    (/public/*), the website chat (/agent/chat) and /health stay open: the quote link token is
    the customer's key. GUEST_VIEWER=1 (default) adds a read-only "demo" login for portfolio
    visitors: they can look at everything but every write (POST/PATCH/PUT/DELETE) is refused,
    so they can't change data or spend AI credit through the owner screens.
    Without OWNER_PASSWORD nothing changes (local development, tests).

Rate limits
    Per client IP, in memory: chat messages and login attempts.

Daily AI budget
    AI_DAILY_CALLS (default 200) caps model calls per day across the whole system, so spam or
    a bug can't burn the API credit. Over the cap the AI features answer "not available now"
    and everything else keeps working. Counted in STORE_DIR/ai_usage.json.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
from collections import defaultdict, deque
from datetime import date

from app.repositories.store import STORE_DIR

PUBLIC_PREFIXES = ("/health", "/auth/", "/public/", "/agent/chat", "/docs", "/redoc",
                   "/openapi.json")
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
TOKEN_DAYS = 7


# ---------------------------------------------------------------- owner login

def owner_password() -> str:
    return os.environ.get("OWNER_PASSWORD", "")


def auth_required() -> bool:
    return bool(owner_password())


def guest_allowed() -> bool:
    return auth_required() and os.environ.get("GUEST_VIEWER", "1") == "1"


def _secret() -> bytes:
    extra = os.environ.get("AUTH_SECRET", "")
    return hashlib.sha256(f"{owner_password()}|{extra}|zit-dvash".encode()).digest()


def make_token(role: str, now: float | None = None) -> str:
    body = json.dumps({"role": role, "exp": int((now or time.time()) + TOKEN_DAYS * 86400)})
    payload = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_token(token: str | None, now: float | None = None) -> str | None:
    """Role ('owner' | 'viewer') of a valid token, else None. Changing the password logs
    everyone out, because the signing key depends on it."""
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    good = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except ValueError:
        return None
    if data.get("exp", 0) < (now or time.time()):
        return None
    return data.get("role") if data.get("role") in ("owner", "viewer") else None


def check_password(password: str) -> bool:
    return auth_required() and hmac.compare_digest(password.encode(), owner_password().encode())


STATIC_EXT = (".js", ".css", ".ico", ".png", ".svg", ".jpg", ".webp", ".woff", ".woff2", ".map",
              ".txt", ".webmanifest")


def is_public(method: str, path: str) -> bool:
    """Customer-facing API, health, docs and the app's own static files. Everything else
    (owner API) needs a login. Page navigations are answered earlier with the app itself."""
    if path.startswith(PUBLIC_PREFIXES) or path == "/":
        return True
    return method in ("GET", "HEAD") and path.endswith(STATIC_EXT)


# ---------------------------------------------------------------- rate limits

class RateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__("rate limited")
        self.retry_after = retry_after


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: int) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                raise RateLimited(int(window_s - (now - q[0])) + 1)
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
CHAT_PER_MINUTE = int(os.environ.get("CHAT_PER_MINUTE", "12"))
LOGIN_PER_MINUTE = 5


def client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def limit_chat(request) -> None:
    limiter.hit(f"chat:{client_ip(request)}", CHAT_PER_MINUTE, 60)


def limit_login(request) -> None:
    limiter.hit(f"login:{client_ip(request)}", LOGIN_PER_MINUTE, 60)


# ---------------------------------------------------------------- daily AI budget

class AiBudgetExceeded(Exception):
    pass


class AiBudget:
    def __init__(self):
        self._lock = threading.Lock()

    @staticmethod
    def limit() -> int:
        return int(os.environ.get("AI_DAILY_CALLS", "200"))

    @staticmethod
    def _path():
        return STORE_DIR / "ai_usage.json"

    def used_today(self) -> int:
        try:
            data = json.loads(self._path().read_text())
        except (OSError, ValueError):
            return 0
        return int(data.get(date.today().isoformat(), 0))

    def spend(self) -> None:
        """Count one model call; refuse when today's cap is reached (0 = no cap)."""
        cap = self.limit()
        with self._lock:
            today = date.today().isoformat()
            try:
                data = json.loads(self._path().read_text())
            except (OSError, ValueError):
                data = {}
            used = int(data.get(today, 0))
            if cap and used >= cap:
                raise AiBudgetExceeded(f"daily AI cap of {cap} calls reached")
            self._path().parent.mkdir(parents=True, exist_ok=True)
            self._path().write_text(json.dumps({today: used + 1}))


ai_budget = AiBudget()
