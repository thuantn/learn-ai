"""AI providers, the provider and key in use, and the call itself. The key is written once and never read back."""
import base64
import binascii
import json
import logging
import os
import re
import secrets
import time
import urllib.error
import urllib.request

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import db

log = logging.getLogger("learn")

# Fixed here on purpose: a stolen admin account must not be able to send lesson text or the key to another address.
PROVIDERS = {
    "openrouter": {"label": "OpenRouter", "base": "https://openrouter.ai/api/v1", "zdr": True, "default_model": "deepseek/deepseek-v4.1-flash"},
    "opencode": {"label": "OpenCode Go", "base": "https://opencode.ai/inference/go/openai/v1", "zdr": False, "default_model": "glm-5.3-flash"},
}
KEY_RE = re.compile(r"[\x21-\x7e]{8,512}")
MODEL_RE = re.compile(r"[A-Za-z0-9._:/-]{1,100}")
ENV_MODEL = "deepseek/deepseek-v4.1-flash"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _open(req, timeout):
    return _opener.open(req, timeout=timeout)


def _master() -> bytes:
    """The 32-byte master key. ValueError carries the problem code."""
    raw = os.environ.get("KEY_ENCRYPTION_KEY")
    if not raw:
        raise ValueError("master_key_missing")
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (binascii.Error, ValueError):
        raise ValueError("master_key_bad") from None
    if len(key) != 32:
        raise ValueError("master_key_bad")
    return key


def _row():
    with db.connect() as c:
        return c.execute("SELECT * FROM ai_settings WHERE id=1").fetchone()


def _decrypt(row) -> str:
    """The stored key. ValueError carries the problem code."""
    blob = bytes(row["key_blob"])
    try:
        return AESGCM(_master()).decrypt(blob[:12], blob[12:], row["provider"].encode()).decode()
    except InvalidTag:
        raise ValueError("key_unreadable") from None


def current() -> dict | None:
    """What a call would use, or None. A stored setting that cannot be read never falls back to the .env key."""
    row = _row()
    if row:
        spec = PROVIDERS.get(row["provider"])
        if not spec:
            return None
        try:
            key = _decrypt(row)
        except ValueError:
            return None
        return {"provider": row["provider"], "model": row["model"], "key": key, "base": spec["base"], "zdr": spec["zdr"], "source": "admin"}
    key = os.environ.get("AI_API_KEY")
    if not key:
        return None
    return {
        "provider": "env", "model": os.environ.get("AI_MODEL", ENV_MODEL), "key": key,
        "base": os.environ.get("AI_BASE_URL", PROVIDERS["openrouter"]["base"]).rstrip("/"),
        "zdr": os.environ.get("AI_ZDR", "1") == "1", "source": "env",
    }


def status() -> dict:
    """What the admin screen shows. Never the key."""
    row = _row()
    if row:
        problem = None
        try:
            _decrypt(row)
        except ValueError as e:
            problem = str(e)
        spec = PROVIDERS.get(row["provider"], {})
        return {"provider": row["provider"], "model": row["model"], "last4": row["key_last4"], "source": "admin", "zdr": bool(spec.get("zdr")), "problem": problem}
    cfg = current()
    if cfg:
        return {"provider": cfg["provider"], "model": cfg["model"], "last4": cfg["key"][-4:], "source": "env", "zdr": cfg["zdr"], "problem": None}
    return {"provider": None, "model": None, "last4": None, "source": None, "zdr": False, "problem": None}


def save(provider: str, model: str, key: str | None, actor: str) -> None:
    """ValueError carries the problem code. No key keeps the stored one, only for the same provider."""
    spec = PROVIDERS.get(provider)
    if not spec:
        raise ValueError("provider_bad")
    model = (model or "").strip() or spec["default_model"]
    if not MODEL_RE.fullmatch(model):
        raise ValueError("model_bad")
    key = (key or "").strip()
    row = _row()
    if key:
        if not KEY_RE.fullmatch(key):
            raise ValueError("key_bad")
        nonce = secrets.token_bytes(12)
        blob = nonce + AESGCM(_master()).encrypt(nonce, key.encode(), provider.encode())
        last4 = key[-4:]
    elif row and row["provider"] == provider:
        blob, last4 = bytes(row["key_blob"]), row["key_last4"]
    else:
        raise ValueError("key_required")
    with db.connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO ai_settings(id, provider, model, key_blob, key_last4, updated_by, updated_at) VALUES(1,?,?,?,?,?,?)",
            (provider, model, blob, last4, actor, time.time()),
        )
        db.admin_log(c, actor, "ai_save", provider, f"model={model} key_changed={'yes' if key else 'no'}")


def _post(cfg, messages, max_tokens, timeout):
    body = {"model": cfg["model"], "messages": messages, "max_tokens": max_tokens}
    if cfg["zdr"]:
        body["provider"] = {"zdr": True}
    req = urllib.request.Request(
        cfg["base"] + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + cfg["key"], "Content-Type": "application/json"},
    )
    with _open(req, timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def call(messages, max_tokens=1500) -> str:
    """One request to the provider in use. A failure raises; there is no other provider to fall back to, on purpose."""
    cfg = current()
    if not cfg:
        raise ValueError("no_config")
    return _post(cfg, messages, max_tokens, 90)


def test() -> dict:
    """{ok, code} with a code the admin screen explains. The provider's own error text never reaches the browser."""
    cfg = current()
    if not cfg:
        return {"ok": False, "code": "no_config"}
    try:
        _post(cfg, [{"role": "user", "content": "Trả lời đúng một chữ: OK"}], 5, 30)
    except urllib.error.HTTPError as e:
        log.warning("ai test http %s", e.code)
        code = {401: "auth", 403: "auth", 404: "zdr_no_endpoint"}.get(e.code, "refused")
        return {"ok": False, "code": code}
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as e:
        log.warning("ai test failed %s", type(e).__name__)
        return {"ok": False, "code": "unreachable"}
    return {"ok": True, "code": "ok"}
