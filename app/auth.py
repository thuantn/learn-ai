"""Passwords, sessions and failed-login limits."""
import asyncio
import hashlib
import math
import os
import secrets
import socket
import time
from collections import defaultdict

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

from . import db

# OWASP minimum for Argon2id.
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
HASHING = asyncio.Semaphore(2)  # each Argon2 call uses about 19 MB

MIN_PASSWORD, MAX_PASSWORD = 15, 256
IDLE_SECONDS, ABSOLUTE_SECONDS = 7 * 86400, 30 * 86400
TOUCH_EVERY = 3600
# ponytail: short list of long common passwords; load a full breach list if accounts ever open up.
COMMON = {
    "123456789012345", "1234567890123456", "12345678901234567890", "passwordpassword", "password12345678",
    "qwertyuiopasdfgh", "qwertyuiopasdfghjkl", "1q2w3e4r5t6y7u8i9o0p", "adminadminadmin", "iloveyouiloveyou",
    "matkhaumatkhau12", "abcdefghijklmnop", "aaaaaaaaaaaaaaa", "111111111111111", "000000000000000",
}


def password_problem(name, password):
    if len(password) < MIN_PASSWORD:
        return f"Mật khẩu phải có ít nhất {MIN_PASSWORD} ký tự."
    if len(password) > MAX_PASSWORD:
        return f"Mật khẩu dài tối đa {MAX_PASSWORD} ký tự."
    low = password.lower()
    if low in COMMON or len(set(low)) < 5 or name.lower() in low:
        return "Mật khẩu này quá dễ đoán. Hãy chọn mật khẩu khác."
    return None


def hash_password(password):
    return HASHER.hash(password)


def verify_password(stored, password):
    try:
        return HASHER.verify(stored or DUMMY_HASH, password) and bool(stored)
    except (Argon2Error, InvalidHashError):
        return False


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(c, user):
    token = secrets.token_urlsafe(32)
    now = time.time()
    c.execute("INSERT INTO sessions VALUES(?,?,?,?)", (_hash_token(token), user, now, now))
    return token


def lookup_session(token):
    """Returns (user, must_change), or None. Writes last_seen at most hourly, so audio requests never write."""
    if not token or len(token) > 128:
        return None
    key = _hash_token(token)
    now = time.time()
    with db.connect() as c:
        row = c.execute(
            "SELECT s.user, s.created_at, s.last_seen, u.must_change FROM sessions s JOIN users u ON u.name=s.user WHERE s.token_hash=?",
            (key,),
        ).fetchone()
        if not row:
            return None
        if now - row["last_seen"] > IDLE_SECONDS or now - row["created_at"] > ABSOLUTE_SECONDS:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (key,))
            return None
        if now - row["last_seen"] > TOUCH_EVERY:
            c.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (now, key))
    return row["user"], bool(row["must_change"])


def end_session(token):
    with db.connect() as c:
        c.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token or ""),))


class LoginLimiter:
    """In-memory, so it resets on restart. Runs before hashing, so floods never reach Argon2."""

    IP_MAX, IP_WINDOW = 30, 900
    PAIR_FREE = 5
    PAIR_MAX_WAIT = 900
    ACCOUNT_MAX, ACCOUNT_WINDOW = 100, 3600

    def __init__(self):
        self.ip = defaultdict(list)
        self.pair = {}
        self.account = defaultdict(list)

    @staticmethod
    def _recent(items, window, now):
        items[:] = [t for t in items if now - t < window]
        return len(items)

    def blocked(self, ip, name):
        now = time.time()
        if self._recent(self.ip[ip], self.IP_WINDOW, now) >= self.IP_MAX:
            return True
        if self._recent(self.account[name], self.ACCOUNT_WINDOW, now) >= self.ACCOUNT_MAX:
            return True
        fails, until = self.pair.get((name, ip), (0, 0))
        return now < until

    def failed(self, ip, name):
        now = time.time()
        self.ip[ip].append(now)
        self.account[name].append(now)
        fails = self.pair.get((name, ip), (0, 0))[0] + 1
        wait = 0 if fails < self.PAIR_FREE else min(30 * 2 ** (fails - self.PAIR_FREE), self.PAIR_MAX_WAIT)
        self.pair[(name, ip)] = (fails, now + wait)
        if len(self.pair) > 10000:  # ponytail: drop everything under a huge flood; the IP limit still applies
            self.pair.clear()
        if len(self.ip) > 10000:
            self.ip.clear()
        if len(self.account) > 10000:
            self.account.clear()

    def succeeded(self, ip, name):
        self.pair.pop((name, ip), None)


class ProxyIp:
    """Trusts cf-connecting-ip only from the tunnel container's own address."""

    def __init__(self, host, ttl=60):
        self.host, self.ttl = host, ttl
        self.addr, self.at = None, -math.inf

    def trusted(self, peer):
        if not self.host:
            return False
        if time.monotonic() - self.at > self.ttl:
            try:
                self.addr = socket.gethostbyname(self.host)
            except OSError:
                self.addr = None
            self.at = time.monotonic()
        return peer == self.addr

    def client(self, peer, header):
        if header and self.trusted(peer):
            return header.strip()[:64]
        return peer or "unknown"


def cookie_name():
    return "__Host-session" if os.environ.get("COOKIE_SECURE", "1") == "1" else "session"
