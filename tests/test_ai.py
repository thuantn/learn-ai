"""Tests for AI providers and the encrypted key."""
import base64
import http.server
import json
import pathlib
import threading

import pytest

from test_catalog import _make_package, _ready_client, ctx  # noqa: F401

KEY = "sk-test-abcd1234"
MASTER = base64.urlsafe_b64encode(b"m" * 32).decode()


@pytest.fixture
def ai(ctx, monkeypatch):
    monkeypatch.setenv("KEY_ENCRYPTION_KEY", MASTER)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    return ctx.main.ai


def _fake_reply(sent=None, text="được"):
    class Reply:
        def read(self):
            return json.dumps({"choices": [{"message": {"content": text}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout):
        if sent is not None:
            sent.append(req)
        return Reply()

    return fake


def _http_error(ai, code):
    def fake(req, timeout):
        raise ai.urllib.error.HTTPError(req.full_url, code, "lỗi của nhà cung cấp", {}, None)

    return fake


def test_key_is_encrypted_at_rest(ctx, ai):
    ai.save("openrouter", "", KEY, "admin")
    for f in pathlib.Path(ctx.db.path()).parent.iterdir():
        assert KEY.encode() not in f.read_bytes(), f.name
    st = ai.status()
    assert st["last4"] == "1234" and st["source"] == "admin" and st["zdr"] is True and KEY not in json.dumps(st)
    assert ai.current()["key"] == KEY


@pytest.mark.parametrize("master,problem", [
    (base64.urlsafe_b64encode(b"x" * 32).decode(), "key_unreadable"),
    ("không phải base64 !!!", "master_key_bad"),
    (base64.urlsafe_b64encode(b"short").decode(), "master_key_bad"),
    (None, "master_key_missing"),
])
def test_bad_master_key_keeps_app_running(ctx, ai, capsys, monkeypatch, master, problem):
    ai.save("openrouter", "", KEY, "admin")
    c = _ready_client(ctx, capsys)
    pid = ctx.catalog.install_version("an", _make_package(ctx.tmp / "p", slug="demo"))["id"]
    with ctx.db.connect() as conn:
        conn.execute("UPDATE packages SET ask_status='approved' WHERE id=?", (pid,))
    key = f"{pid}.demo"
    if master is None:
        monkeypatch.delenv("KEY_ENCRYPTION_KEY")
    else:
        monkeypatch.setenv("KEY_ENCRYPTION_KEY", master)
    assert ai.current() is None and ai.status()["problem"] == problem
    with c:
        assert c.get("/api/lessons").status_code == 200
        assert c.post(f"/api/lessons/{key}/frame", json={}).status_code == 200
        assert c.post("/api/ask", json={"lesson": key, "question": "x"}).status_code == 503
    # Back with the right master key, the stored key works again; nothing was lost.
    monkeypatch.setenv("KEY_ENCRYPTION_KEY", MASTER)
    assert ai.current()["key"] == KEY


def test_missing_master_key_refuses_save(ctx, ai, monkeypatch):
    monkeypatch.delenv("KEY_ENCRYPTION_KEY")
    with pytest.raises(ValueError, match="master_key_missing"):
        ai.save("openrouter", "", KEY, "admin")
    assert ai.status()["provider"] is None


def test_env_key_is_the_fallback_only_without_a_stored_setting(ctx, ai, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "khoa-trong-env")
    assert ai.current()["source"] == "env" and ai.status()["last4"] == "-env"
    ai.save("openrouter", "", KEY, "admin")
    assert ai.current()["key"] == KEY
    monkeypatch.setenv("KEY_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"x" * 32).decode())
    assert ai.current() is None, "a stored setting that cannot be read must not switch to another key"


def test_base_url_override_never_reaches_a_stored_setting(ctx, ai, monkeypatch):
    monkeypatch.setenv("AI_BASE_URL", "http://evil.example/v1")
    ai.save("openrouter", "", KEY, "admin")
    assert ai.current()["base"] == ai.PROVIDERS["openrouter"]["base"]


def test_key_required_when_provider_changes(ctx, ai):
    with pytest.raises(ValueError, match="key_required"):
        ai.save("openrouter", "", None, "admin")
    ai.save("openrouter", "", KEY, "admin")
    with pytest.raises(ValueError, match="key_required"):
        ai.save("opencode", "", "  ", "admin")
    assert ai.current()["provider"] == "openrouter"
    ai.save("openrouter", "other/model", None, "admin")
    assert ai.current()["key"] == KEY and ai.current()["model"] == "other/model"


@pytest.mark.parametrize("provider,model,key,code", [
    ("evil", "", KEY, "provider_bad"),
    ("openrouter", "bad model!", KEY, "model_bad"),
    ("openrouter", "m\nx", KEY, "model_bad"),
    ("openrouter", "", "short", "key_bad"),
    ("openrouter", "", "has space inside", "key_bad"),
    ("openrouter", "", "khóa-không-ascii", "key_bad"),
])
def test_input_is_validated(ctx, ai, provider, model, key, code):
    with pytest.raises(ValueError, match=code):
        ai.save(provider, model, key, "admin")


def test_a_new_nonce_each_save(ctx, ai):
    ai.save("openrouter", "", KEY, "admin")
    first = bytes(ai._row()["key_blob"])
    ai.save("openrouter", "", KEY, "admin")
    assert bytes(ai._row()["key_blob"])[:12] != first[:12]


def test_no_fallback_between_providers(ctx, ai, monkeypatch):
    ai.save("opencode", "", KEY, "admin")
    seen = []

    def fake(req, timeout):
        seen.append(req.full_url)
        raise ai.urllib.error.HTTPError(req.full_url, 500, "x", {}, None)

    monkeypatch.setattr(ai, "_open", fake)
    with pytest.raises(ai.urllib.error.HTTPError):
        ai.call([{"role": "user", "content": "x"}])
    assert seen == [ai.PROVIDERS["opencode"]["base"] + "/chat/completions"]


def test_zdr_flag_sent_only_for_zdr_providers(ctx, ai, monkeypatch):
    sent = []
    monkeypatch.setattr(ai, "_open", _fake_reply(sent))
    ai.save("openrouter", "", KEY, "admin")
    assert ai.call([{"role": "user", "content": "x"}]) == "được"
    ai.save("opencode", "", KEY, "admin")
    ai.call([{"role": "user", "content": "x"}])
    bodies = [json.loads(r.data) for r in sent]
    assert bodies[0]["provider"] == {"zdr": True} and "provider" not in bodies[1]
    assert sent[0].get_header("Authorization") == "Bearer " + KEY


def test_key_does_not_follow_a_redirect(ctx, ai, monkeypatch):
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/stolen")
            self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("AI_API_KEY", KEY)
        monkeypatch.setenv("AI_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
        with pytest.raises(ai.urllib.error.HTTPError):
            ai.call([{"role": "user", "content": "x"}])
        assert hits == ["/v1/chat/completions"]
    finally:
        server.shutdown()


@pytest.mark.parametrize("status,code", [(401, "auth"), (403, "auth"), (404, "zdr_no_endpoint"), (402, "refused")])
def test_ai_test_maps_errors(ctx, ai, monkeypatch, status, code):
    ai.save("openrouter", "", KEY, "admin")
    monkeypatch.setattr(ai, "_open", _http_error(ai, status))
    result = ai.test()
    assert result == {"ok": False, "code": code}


def test_ai_test_ok_and_unconfigured(ctx, ai, monkeypatch):
    assert ai.test() == {"ok": False, "code": "no_config"}
    ai.save("openrouter", "", KEY, "admin")
    monkeypatch.setattr(ai, "_open", _fake_reply())
    assert ai.test() == {"ok": True, "code": "ok"}


def test_key_never_leaks(ctx, ai, capsys, caplog):
    with caplog.at_level("DEBUG"):
        ai.save("openrouter", "", KEY, "admin")
    with ctx.db.connect() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM admin_log")]
    assert len(rows) == 1 and rows[0]["actor"] == "admin" and rows[0]["action"] == "ai_save"
    assert KEY not in json.dumps(rows) and KEY not in caplog.text and KEY not in capsys.readouterr().out
