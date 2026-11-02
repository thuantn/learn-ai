"""Sandboxed lesson file serving and signed lesson tokens."""
import base64
import hashlib
import hmac
import os
import pathlib

from . import catalog

LINK_TTL_SECONDS_DEFAULT = 21600


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


def _secret() -> bytes | None:
    s = os.environ.get("LINK_SECRET")
    return s.encode() if s else None


def make_token(user_id: int, lesson: str, now: float, secret: bytes | None = None) -> str:
    """Returns a base64url(payload).base64url(HMAC-SHA256) token.

    # ponytail: rowid can be reused after deleting the user with the largest rowid,
    # and the old token lives at most LINK_TTL_SECONDS; the receiver still needs access.
    Add a dedicated id column if user deletion becomes common.
    """
    if secret is None:
        secret = _secret()
    exp = now + int(os.environ.get("LINK_TTL_SECONDS", str(LINK_TTL_SECONDS_DEFAULT)))
    payload = f"{user_id}|{lesson}|{exp}"
    payload_b64 = _b64url_encode(payload.encode())
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


def read_token(token: str, now: float, secret: bytes | None = None) -> tuple[int, str] | None:
    """Verifies a token and returns (user_id, lesson), or None."""
    if secret is None:
        secret = _secret()
    if not secret or "." not in token:
        return None
    payload_b64, sig_b64 = token.split(".", 1)
    try:
        payload = _b64url_decode(payload_b64).decode("utf-8")
        user_id_str, lesson, exp_str = payload.split("|", 2)
        user_id = int(user_id_str)
        exp = float(exp_str)
    except (ValueError, UnicodeDecodeError):
        return None
    if now > exp:
        return None
    expected = hmac.new(secret, payload.encode(), hashlib.sha256).digest()
    try:
        got = _b64url_decode(sig_b64)
    except ValueError:
        return None
    if not hmac.compare_digest(expected, got):
        return None
    return user_id, lesson


def can_read(c, user_id: int, lesson: str) -> bool:
    """True if the user exists and has access to the lesson."""
    row = c.execute("SELECT name FROM users WHERE rowid=?", (user_id,)).fetchone()
    if not row:
        return False
    return catalog.lesson_for(c, row["name"], lesson) is not None


def learner_code(user_id: int, package_id: str, secret: bytes | None = None) -> str:
    """A per-user, per-package opaque code exposed to lesson pages."""
    if secret is None:
        secret = _secret()
    return hmac.new(secret, f"learner|{package_id}|{user_id}".encode(), hashlib.sha256).hexdigest()


def _sandbox_origin() -> str:
    return os.environ.get("PUBLIC_ORIGIN") or "'self'"


def page_headers(path: str) -> dict:
    """Headers for files served under /s/."""
    origin = _sandbox_origin()
    ext = pathlib.Path(path).suffix.lower()
    if ext == ".html":
        csp = (
            f"sandbox allow-scripts; default-src 'none'; script-src {origin}; style-src {origin} 'unsafe-inline'; "
            f"img-src {origin} data:; font-src {origin} data:; media-src {origin}; connect-src 'none'; "
            f"form-action 'none'; base-uri 'none'; object-src 'none'; frame-ancestors {origin}"
        )
        cache = "no-store"
    else:
        csp = "sandbox; default-src 'none'"
        cache = "private, max-age=300"
    headers = {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "Cross-Origin-Resource-Policy": "cross-origin",
        "Cache-Control": cache,
    }
    if ext == ".woff2":
        headers["Access-Control-Allow-Origin"] = "*"
    return headers
