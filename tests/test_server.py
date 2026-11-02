"""Security and behaviour checks. No network: the AI API is replaced by a stub."""
import base64
import importlib
import json
import pathlib
import sqlite3
import sys
import time

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ORIGIN = "https://testserver"
GOOD = "ngựa vàng chạy qua cầu mây"


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    (tmp_path / "content").mkdir()
    src = ROOT / "sample"
    audio = tmp_path / "content" / "demo1" / "audio"
    audio.mkdir(parents=True)
    (audio / "short.mp3").write_bytes(b"0123456789")
    (audio / "long.mp3").write_bytes(b"abcdefghij" * 100)
    (tmp_path / "content" / "demo1" / "lesson.html").write_text((src / "demo1" / "lesson.html").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "content" / "manifest.json").write_text((src / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "content" / "secret.txt").write_text("không được phục vụ", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CONTENT_DIR", str(tmp_path / "content"))
    monkeypatch.setenv("PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setenv("AI_DAILY_LIMIT", "3")
    for name in ("app.main", "app.cli", "app.auth", "app.db"):
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    cli = importlib.import_module("app.cli")
    return main, cli, tmp_path


def client(main):
    return TestClient(main.app, base_url=ORIGIN, headers={"Origin": ORIGIN}, follow_redirects=False)


def add_user(cli, capsys, name):
    cli.main(["add-user", name])
    return capsys.readouterr().out.rsplit(": ", 1)[1].strip()


def login(c, name, password):
    return c.post("/login", json={"username": name, "password": password})


def ready_user(main, cli, capsys, name="an"):
    temp = add_user(cli, capsys, name)
    c = client(main)
    assert login(c, name, temp).status_code == 200
    assert c.post("/api/change-password", json={"password": GOOD}).status_code == 200
    return c


def test_everything_needs_a_session(ctx):
    main, _, _ = ctx
    with client(main) as c:
        for path in ("/", "/content/demo1/lesson.html", "/content/demo1/audio/long.mp3", "/change-password"):
            r = c.get(path)
            assert r.status_code == 303 and r.headers["location"] == "/login", path
        for path in ("/api/me", "/api/lessons", "/api/cards/due", "/api/doc/demo1doc"):
            assert c.get(path).status_code == 401, path
        assert c.post("/api/ask", json={"lesson": "demo1", "question": "x"}).status_code == 401
        assert c.get("/login").status_code == 200
        assert c.get("/healthz").status_code == 200


def test_forged_cookie_refused(ctx):
    main, _, _ = ctx
    with client(main) as c:
        c.cookies.set("__Host-session", "A" * 43)
        assert c.get("/api/me").status_code == 401
        c.cookies.set("__Host-session", "A" * 5000)
        assert c.get("/api/me").status_code == 401


def test_login_errors_are_identical(ctx, capsys):
    main, cli, _ = ctx
    temp = add_user(cli, capsys, "an")
    with client(main) as c:
        a = login(c, "an", "sai mật khẩu rồi nhé")
        b = login(c, "khong-co-ai", "sai mật khẩu rồi nhé")
        assert a.status_code == b.status_code == 401
        assert a.json() == b.json()
        assert login(c, "an", temp).status_code == 200


def test_cookie_attributes_and_nothing_in_clear(ctx, capsys, caplog):
    main, cli, tmp = ctx
    temp = add_user(cli, capsys, "an")
    with client(main) as c:
        r = login(c, "an", temp)
        cookie = r.headers["set-cookie"]
        for part in ("__Host-session=", "HttpOnly", "Secure", "SameSite=strict", "Path=/"):
            assert part.lower() in cookie.lower(), part
        assert "domain" not in cookie.lower()
        token = cookie.split("=", 1)[1].split(";")[0]
    raw = (tmp / "data" / "learn.db").read_bytes() + (tmp / "data" / "learn.db-wal").read_bytes()
    assert temp.encode() not in raw and token.encode() not in raw
    assert temp not in caplog.text and token not in caplog.text


def test_failed_logins_get_blocked_without_blocking_others(ctx, capsys):
    main, cli, _ = ctx
    temp = add_user(cli, capsys, "an")
    with client(main) as c:
        codes = [login(c, "an", "sai mật khẩu rồi nhé").status_code for _ in range(6)]
        assert codes[:5] == [401] * 5 and codes[5] == 429
        assert login(c, "an", temp).status_code == 429
    # Same account from another address still works, so outsiders cannot lock the owner out.
    main.limiter.pair.clear()
    assert main.limiter.blocked("9.9.9.9", "an") is False
    main.limiter.failed("9.9.9.9", "an")
    assert main.limiter.blocked("8.8.8.8", "an") is False


def test_limiter_ip_and_account_caps(ctx):
    main, _, _ = ctx
    lim = main.auth.LoginLimiter()
    for i in range(lim.IP_MAX):
        lim.failed("1.1.1.1", f"u{i}")
    assert lim.blocked("1.1.1.1", "khac")
    lim = main.auth.LoginLimiter()
    for i in range(lim.ACCOUNT_MAX):
        lim.failed(f"10.0.0.{i}", "an")
    assert lim.blocked("2.2.2.2", "an") and not lim.blocked("2.2.2.2", "binh")


def test_forged_ip_header_is_ignored_unless_from_tunnel(ctx, monkeypatch):
    main, _, _ = ctx
    p = main.auth.ProxyIp("tunnel")
    monkeypatch.setattr(main.auth.socket, "gethostbyname", lambda h: "172.30.0.2")
    assert p.client("172.30.0.9", "1.2.3.4") == "172.30.0.9"
    assert p.client("172.30.0.2", "1.2.3.4") == "1.2.3.4"
    assert main.auth.ProxyIp("").client("172.30.0.2", "1.2.3.4") == "172.30.0.2"


def test_temp_password_must_be_changed_first(ctx, capsys):
    main, cli, _ = ctx
    temp = add_user(cli, capsys, "an")
    with client(main) as c:
        assert login(c, "an", temp).json()["must_change"] is True
        assert c.get("/api/me").status_code == 403
        assert c.get("/api/lessons").status_code == 403
        assert c.get("/").headers["location"] == "/change-password"
        assert c.get("/content/demo1/lesson.html").headers["location"] == "/change-password"
        assert c.get("/change-password").status_code == 200
        for weak in ("ngắn", "passwordpassword", "aaaaaaaaaaaaaaaaaaaa", "an-an-an-an-an-an-an", temp):
            assert c.post("/api/change-password", json={"password": weak}).status_code == 400, weak
        old = c.cookies.get("__Host-session")
        assert c.post("/api/change-password", json={"password": GOOD}).status_code == 200
        assert c.cookies.get("__Host-session") != old
        assert c.get("/api/me").status_code == 200
        assert c.post("/api/change-password", json={"password": GOOD + "x"}).status_code == 403
    with client(main) as stale:
        stale.cookies.set("__Host-session", old)
        assert stale.get("/api/me").status_code == 401


def test_logout_ends_session_on_server(ctx, capsys):
    main, cli, _ = ctx
    c = ready_user(main, cli, capsys)
    with c:
        token = c.cookies.get("__Host-session")
        assert c.post("/logout").status_code == 200
        c.cookies.set("__Host-session", token)
        assert c.get("/api/me").status_code == 401


def test_session_expiry(ctx, capsys):
    main, cli, tmp = ctx
    c = ready_user(main, cli, capsys)
    with c:
        assert c.get("/api/me").status_code == 200
        db = sqlite3.connect(tmp / "data" / "learn.db")
        db.execute("UPDATE sessions SET last_seen=?", (time.time() - 8 * 86400,))
        db.commit()
        assert c.get("/api/me").status_code == 401
    c2 = client(main)
    with c2:
        assert login(c2, "an", GOOD).status_code == 200
        db.execute("UPDATE sessions SET created_at=?", (time.time() - 31 * 86400,))
        db.commit()
        assert c2.get("/api/me").status_code == 401
    db.close()


def test_last_seen_written_at_most_hourly(ctx, capsys, tmp_path):
    main, cli, tmp = ctx
    c = ready_user(main, cli, capsys)
    with c:
        db = sqlite3.connect(tmp / "data" / "learn.db")
        t = time.time() - 600
        db.execute("UPDATE sessions SET last_seen=?", (t,))
        db.commit()
        c.get("/api/me")
        assert db.execute("SELECT last_seen FROM sessions").fetchone()[0] == t
        db.execute("UPDATE sessions SET last_seen=?", (time.time() - 4000,))
        db.commit()
        c.get("/api/me")
        assert time.time() - db.execute("SELECT last_seen FROM sessions").fetchone()[0] < 60
        db.close()


def test_foreign_origin_and_no_origin_refused(ctx, capsys):
    main, cli, _ = ctx
    temp = add_user(cli, capsys, "an")
    with TestClient(main.app, base_url=ORIGIN) as c:
        body = {"username": "an", "password": temp}
        assert c.post("/login", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
        assert c.post("/login", json=body).status_code == 403


def test_nothing_else_is_reachable(ctx, capsys):
    main, cli, _ = ctx
    c = ready_user(main, cli, capsys)
    with c:
        for path in ("/docs", "/redoc", "/openapi.json", "/content/secret.txt", "/content/manifest.json", "/content/demo1/", "/content/../data/learn.db",
                     "/content/%2e%2e/secret.txt", "/static/../../app/main.py", "/static/%2e%2e/%2e%2e/app/main.py", "/content/demo1/../secret.txt", "/data/learn.db"):
            assert c.get(path).status_code == 404, path


def test_security_headers(ctx):
    main, _, _ = ctx
    with client(main) as c:
        h = c.get("/login").headers
        assert "default-src 'self'" in h["content-security-policy"] and "'unsafe-inline'" not in h["content-security-policy"].split("style-src")[0]
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff" and "max-age" in h["strict-transport-security"] and h["referrer-policy"] == "same-origin"
        assert c.get("/api/me").headers["cache-control"] == "no-store"
        


def test_body_limit(ctx, capsys):
    main, cli, _ = ctx
    c = ready_user(main, cli, capsys)
    with c:
        big = {"episode": "demo1:long", "seconds": 1, "pad": "x" * 20000}
        assert c.put("/api/listen", json=big).status_code == 400
        assert c.put("/api/doc/demo1doc", json={"pad": "x" * (3 * 1024 * 1024)}).status_code == 400


def test_users_cannot_see_each_other(ctx, capsys):
    main, cli, _ = ctx
    a = ready_user(main, cli, capsys, "an")
    b = ready_user(main, cli, capsys, "binh")
    with a, b:
        a.post("/api/lessons/demo1/start")
        a.put("/api/listen", json={"episode": "demo1:long", "seconds": 3, "user": "binh"})
        a.put("/api/doc/demo1doc", json={"quiz": {"q0": 0}, "chat": ["bí mật của an"], "user": "binh"})
        assert b.get("/api/doc/demo1doc").json()["data"] is None
        assert b.get("/api/cards/due").json()["cards"] == []
        assert b.get("/api/lessons").json()["lessons"][0]["tracks"]["long"]["position"] == 0
        card = a.get("/api/cards/due").json()["cards"][0]["id"]
        assert b.post(f"/api/cards/{card}/review", json={"rating": 3}).status_code == 404
        assert b.get("/api/doc/demo1doc?user=an").json()["data"] is None


def test_cards_open_on_start_and_fsrs_order(ctx, capsys):
    main, cli, _ = ctx
    c = ready_user(main, cli, capsys)
    with c:
        assert c.get("/api/lessons").json()["due_total"] == 0
        assert c.post("/api/lessons/nope/start").status_code == 404
        assert c.post("/api/lessons/demo1/start").status_code == 200
        assert c.get("/api/lessons").json()["lessons"][0]["status"] == "in_progress"
        cards = c.get("/api/cards/due").json()["cards"]
        assert {x["id"] for x in cards} == {"demo1-c1", "demo1-c2"}
        forget = c.post("/api/cards/demo1-c1/review", json={"rating": 1}).json()["due"]
        easy = c.post("/api/cards/demo1-c2/review", json={"rating": 4}).json()["due"]
        assert forget < easy
        for bad in (0, 5, "3", True, None):
            assert c.post("/api/cards/demo1-c1/review", json={"rating": bad}).status_code == 400
        c.post("/api/lessons/demo1/finish")
        c.post("/api/lessons/demo1/start")
        assert c.get("/api/lessons").json()["lessons"][0]["status"] == "done"


def test_wrong_quiz_answer_makes_one_card_and_right_makes_none(ctx, capsys):
    main, cli, _ = ctx
    c = ready_user(main, cli, capsys)
    with c:
        c.put("/api/doc/demo1doc", json={"quiz": {"q0": 1}})
        assert c.get("/api/cards/due").json()["cards"] == []
        for _ in range(2):
            c.put("/api/doc/demo1doc", json={"quiz": {"q0": 0, "q99": 1, "q0x": "a"}})
        cards = c.get("/api/cards/due").json()["cards"]
        assert len(cards) == 1 and cards[0]["id"] == "demo1-q0" and cards[0]["wrong"] and cards[0]["a"].startswith("2")
        due = c.post("/api/cards/demo1-q0/review", json={"rating": 4}).json()["due"]
        c.put("/api/doc/demo1doc", json={"quiz": {"q0": 2}})
        assert c.get("/api/cards/due").json()["cards"] == [] and due > time.time()


def test_listen_position(ctx, capsys):
    main, cli, _ = ctx
    c = ready_user(main, cli, capsys)
    with c:
        for bad in ({"episode": "demo1:other", "seconds": 1}, {"episode": "x:long", "seconds": 1}, {"episode": "demo1:long", "seconds": "1"}, {"episode": "demo1:long", "seconds": True}):
            assert c.put("/api/listen", json=bad).status_code == 400
        c.put("/api/listen", json={"episode": "demo1:long", "seconds": 999})
        lesson = c.get("/api/lessons").json()["lessons"][0]
        assert lesson["track"] == "long" and lesson["tracks"]["long"]["position"] == 0  # at the end, so it restarts


def test_audio_range(ctx, capsys):
    main, cli, _ = ctx
    c = ready_user(main, cli, capsys)
    with c:
        r = c.get("/content/demo1/audio/long.mp3", headers={"Range": "bytes=10-19"})
        assert r.status_code == 206 and r.content == b"abcdefghij" and r.headers["content-range"].startswith("bytes 10-19/")


def test_ask_disabled_without_key(ctx, capsys):
    main, cli, _ = ctx
    c = ready_user(main, cli, capsys)
    with c:
        r = c.post("/api/ask", json={"lesson": "demo1", "question": "x"})
        assert r.status_code == 503 and r.json()["code"] == "disabled"


def test_ask_server_controls_prompt_and_limits(ctx, capsys, monkeypatch):
    main, cli, _ = ctx
    monkeypatch.setenv("AI_API_KEY", "khoa-bi-mat")
    sent = []
    monkeypatch.setattr(main, "call_ai", lambda m: (sent.append(m), "**được**")[1])
    c = ready_user(main, cli, capsys)
    with c:
        r = c.post("/api/ask", json={"lesson": "demo1", "question": "Vì sao?", "model": "x", "max_tokens": 99999})
        assert r.json()["text"] == "**được**" and sent[-1][0]["role"] == "system" and "Trung bình" in sent[-1][0]["content"]
        for bad in ({"lesson": "nope", "question": "x"}, {"lesson": "demo1", "input": [{"role": "system", "content": "x"}]},
                    {"lesson": "demo1", "input": [{"role": "user", "content": 1}]}, {"lesson": "demo1", "question": "x" * 3000}, {"lesson": "demo1"}):
            assert c.post("/api/ask", json=bad).status_code == 400, bad
        assert c.post("/api/ask", json={"lesson": "demo1", "input": "Câu từ trang bài"}).status_code == 200
        assert sent[-1] == [{"role": "user", "content": "Câu từ trang bài"}]
        assert c.post("/api/ask", json={"lesson": "demo1", "input": [{"role": "user", "content": "a"}]}).status_code == 200
        assert c.post("/api/ask", json={"lesson": "demo1", "question": "hết lượt"}).status_code == 429


def test_ask_sends_zdr_and_reports_failure_without_retry(ctx, capsys, monkeypatch):
    main, cli, _ = ctx
    monkeypatch.setenv("AI_API_KEY", "khoa-bi-mat")
    seen = []

    def fake(req, timeout):
        seen.append(json.loads(req.data))
        raise main.urllib.error.HTTPError(req.full_url, 404, "No endpoints", {}, None)

    monkeypatch.setattr(main.urllib.request, "urlopen", fake)
    c = ready_user(main, cli, capsys)
    with c:
        r = c.post("/api/ask", json={"lesson": "demo1", "question": "x"})
        assert r.status_code == 502 and "khoa-bi-mat" not in r.text
    assert len(seen) == 1 and seen[0]["provider"] == {"zdr": True} and seen[0]["max_tokens"] == 1500


def test_cli_reset_and_remove(ctx, capsys):
    main, cli, tmp = ctx
    c = ready_user(main, cli, capsys)
    with c:
        assert cli.main(["reset-password", "an"]) == 0
        new = capsys.readouterr().out.rsplit(": ", 1)[1].strip()
        assert c.get("/api/me").status_code == 401
        assert login(c, "an", new).json()["must_change"] is True
        assert cli.main(["remove-user", "an"]) == 0
        assert c.get("/api/me").status_code == 401


def test_backup_keeps_newest(ctx, capsys, tmp_path):
    main, cli, tmp = ctx
    add_user(cli, capsys, "an")
    dest = tmp / "bk"
    dest.mkdir()
    for i in range(16):
        (dest / f"learn-2020010{i:02d}.db").write_bytes(b"x")
    made = main.db.backup(str(dest))
    files = list(dest.glob("learn-*.db"))
    assert len(files) == 14 and pathlib.Path(made) in files
    assert sqlite3.connect(made).execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_no_html_handlers_in_app_pages():
    """The CSP forbids inline scripts, so an onclick here would silently do nothing."""
    import re
    for name in ("app.html", "login.html", "password.html"):
        html = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert not re.search(r"\son[a-z]+\s*=", html), name
        assert "<script>" not in html and "https://" not in html, name
