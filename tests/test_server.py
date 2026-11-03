"""Security and behaviour checks. No network: the AI API is replaced by a stub."""
import base64
import importlib
import json
import pathlib
import shutil
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
    (tmp_path / "packages").mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PACKAGES_DIR", str(tmp_path / "packages"))
    monkeypatch.setenv("PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("LINK_SECRET", "test-secret-32bytes-long-for-hmac-sha256")
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setenv("AI_DAILY_LIMIT", "3")
    for name in (
        "app.main",
        "app.cli",
        "app.auth",
        "app.db",
        "app.catalog",
        "app.sandbox",
        "app.contract",
        "app.bundle", "app.uploads", "app.ai", "app.admin", "app.practice", "app.practice_api", "app.web_util",
    ):
        sys.modules.pop(name, None)
        # `from . import x` reads the package attribute first, so it must go too.
        if "app" in sys.modules and name in ("app.practice", "app.practice_api"):
            sys.modules["app"].__dict__.pop(name.split(".")[1], None)
    main = importlib.import_module("app.main")
    cli = importlib.import_module("app.cli")
    return main, cli, tmp_path


def install_sample(main, owner, tmp_path, name="pkg"):
    src = ROOT / "sample" / "package"
    copy = tmp_path / name
    shutil.copytree(src, copy)
    audio_dir = copy / "lessons" / "sample" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    tone = ROOT / "tests" / "fixtures" / "tone.mp3"
    shutil.copy(tone, audio_dir / "short.mp3")
    shutil.copy(tone, audio_dir / "long.mp3")
    (audio_dir / "tone.mp3").write_bytes(b"fake mp3 data for range request test" * 10)
    lesson_path = copy / "lessons" / "sample" / "lesson.json"
    lesson = json.loads(lesson_path.read_text(encoding="utf-8"))
    lesson["title"] = "Trung bình"
    lesson["tracks"] = {
        "short": {"file": "short.mp3", "label": "Ngắn"},
        "long": {"file": "long.mp3", "label": "Dài"},
    }
    lesson["cards"] = lesson["cards"][:2]
    lesson["quiz"] = [{"id": "sample-q0", "q": "?", "options": ["0", "20", "x"], "answer": 1, "why": "vì 20"}]
    lesson_path.write_text(json.dumps(lesson), encoding="utf-8")
    res = main.catalog.install_version(owner, copy)
    return f"{res['id']}.sample"


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


def test_everything_needs_a_session(ctx, capsys):
    main, cli, tmp = ctx
    add_user(cli, capsys, "an")
    with client(main) as c:
        key = install_sample(main, "an", tmp)
        for path in ("/", f"/content/{key}/lesson.html", f"/content/{key}/audio/long.mp3", "/change-password"):
            r = c.get(path)
            assert r.status_code == 303 and r.headers["location"] == "/login", path
        for path in ("/api/me", "/api/lessons", "/api/cards/due", f"/api/doc/{key}"):
            assert c.get(path).status_code == 401, path
        assert c.post("/api/ask", json={"lesson": key, "question": "x"}).status_code == 401
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
    main, cli, tmp = ctx
    temp = add_user(cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with client(main) as c:
        assert login(c, "an", temp).json()["must_change"] is True
        assert c.get("/api/me").status_code == 403
        assert c.get("/api/lessons").status_code == 403
        assert c.get("/").headers["location"] == "/change-password"
        assert c.get(f"/content/{key}/lesson.html").headers["location"] == "/change-password"
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
    main, cli, tmp = ctx
    c = ready_user(main, cli, capsys)
    key = install_sample(main, "an", tmp)
    with c:
        for path in (
            "/docs",
            "/redoc",
            "/openapi.json",
            f"/content/{key}/lesson.html",
            f"/content/{key}/audio/long.mp3",
            "/content/secret.txt",
            "/content/manifest.json",
            f"/content/{key}/",
            "/content/../data/learn.db",
            "/content/%2e%2e/secret.txt",
            "/static/../../app/main.py",
            "/static/%2e%2e/%2e%2e/app/main.py",
            f"/content/{key}/../secret.txt",
            "/data/learn.db",
        ):
            assert c.get(path).status_code == 404, path


def test_security_headers(ctx):
    main, _, _ = ctx
    with client(main) as c:
        h = c.get("/login").headers
        assert "default-src 'self'" in h["content-security-policy"] and "'unsafe-inline'" not in h["content-security-policy"].split("style-src")[0]
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert "script-src https://testserver/static/;" in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff" and "max-age" in h["strict-transport-security"] and h["referrer-policy"] == "same-origin"
        assert c.get("/api/me").headers["cache-control"] == "no-store"


def test_body_limit(ctx, capsys):
    main, cli, tmp = ctx
    c = ready_user(main, cli, capsys)
    key = install_sample(main, "an", tmp)
    with c:
        big = {"episode": f"{key}:long", "seconds": 1, "pad": "x" * 20000}
        assert c.put("/api/listen", json=big).status_code == 404
        assert c.put(f"/api/doc/{key}", json={"pad": "x" * (3 * 1024 * 1024)}).status_code == 400


def test_users_cannot_see_each_other(ctx, capsys):
    main, cli, tmp = ctx
    a = ready_user(main, cli, capsys, "an")
    b = ready_user(main, cli, capsys, "binh")
    key = install_sample(main, "an", tmp)
    with a, b:
        a.post(f"/api/lessons/{key}/start")
        a.put("/api/listen", json={"episode": f"{key}:long", "seconds": 3, "user": "binh"})
        a.put(f"/api/doc/{key}", json={"quiz": {"q0": 0}, "chat": ["bí mật của an"], "user": "binh"})
        assert b.get(f"/api/doc/{key}").status_code == 404
        assert b.get("/api/cards/due").json()["cards"] == []
        assert b.get("/api/lessons").json()["lessons"] == []
        card = a.get("/api/cards/due").json()["cards"][0]["id"]
        assert b.post(f"/api/cards/{card}/review", json={"rating": 3}).status_code == 404
        assert b.get(f"/api/doc/{key}?user=an").status_code == 404


def test_cards_open_on_start_and_fsrs_order(ctx, capsys):
    main, cli, tmp = ctx
    c = ready_user(main, cli, capsys)
    key = install_sample(main, "an", tmp)
    with c:
        assert c.get("/api/lessons").json()["due_total"] == 0
        assert c.post("/api/lessons/nope/start").status_code == 404
        assert c.post(f"/api/lessons/{key}/start").status_code == 200
        assert c.get("/api/lessons").json()["lessons"][0]["status"] == "in_progress"
        cards = c.get("/api/cards/due").json()["cards"]
        assert {x["target_id"] for x in cards} == {"sample-c1", "sample-c2"}
        by_target = {x["target_id"]: x["id"] for x in cards}
        forget = c.post(f"/api/cards/{by_target['sample-c1']}/review", json={"rating": 1}).json()["due"]
        easy = c.post(f"/api/cards/{by_target['sample-c2']}/review", json={"rating": 4}).json()["due"]
        assert forget < easy
        for bad in (0, 5, "3", True, None):
            assert c.post(f"/api/cards/{by_target['sample-c1']}/review", json={"rating": bad}).status_code == 400
        c.post(f"/api/lessons/{key}/finish")
        c.post(f"/api/lessons/{key}/start")
        assert c.get("/api/lessons").json()["lessons"][0]["status"] == "done"


def test_wrong_quiz_answer_makes_one_card_and_right_makes_none(ctx, capsys):
    main, cli, tmp = ctx
    c = ready_user(main, cli, capsys)
    key = install_sample(main, "an", tmp)
    pkg_id = key.split(".")[0]
    full_q0 = f"{pkg_id}.sample-q0"
    with c:
        c.put(f"/api/doc/{key}", json={"quiz": {"q0": 1}})
        assert c.get("/api/cards/due").json()["cards"] == []
        for _ in range(2):
            c.put(f"/api/doc/{key}", json={"quiz": {"q0": 0, "q99": 1, "q0x": "a"}})
        cards = c.get("/api/cards/due").json()["cards"]
        assert len(cards) == 1 and cards[0]["id"] == full_q0 and cards[0]["wrong"] and cards[0]["a"].startswith("2")
        due = c.post(f"/api/cards/{full_q0}/review", json={"rating": 4}).json()["due"]
        c.put(f"/api/doc/{key}", json={"quiz": {"q0": 2}})
        assert c.get("/api/cards/due").json()["cards"] == [] and due > time.time()


def test_listen_position(ctx, capsys):
    main, cli, tmp = ctx
    c = ready_user(main, cli, capsys)
    key = install_sample(main, "an", tmp)
    with c:
        assert c.put("/api/listen", json={"episode": f"{key}:other", "seconds": 1}).status_code == 400
        assert c.put("/api/listen", json={"episode": "x:long", "seconds": 1}).status_code == 404
        for bad in (
            {"episode": f"{key}:long", "seconds": "1"},
            {"episode": f"{key}:long", "seconds": True},
        ):
            assert c.put("/api/listen", json=bad).status_code == 400
        c.put("/api/listen", json={"episode": f"{key}:long", "seconds": 999})
        lesson = c.get("/api/lessons").json()["lessons"][0]
        assert lesson["track"] == "long" and lesson["tracks"]["long"]["position"] == 0  # at the end, so it restarts


def test_audio_range(ctx, capsys):
    main, cli, tmp = ctx
    c = ready_user(main, cli, capsys)
    key = install_sample(main, "an", tmp)
    with c:
        r = c.get(f"/content/{key}/audio/long.mp3", headers={"Range": "bytes=10-19"})
        assert r.status_code == 404


def test_ask_disabled_without_key(ctx, capsys):
    main, cli, tmp = ctx
    c = ready_user(main, cli, capsys)
    key = install_sample(main, "an", tmp)
    with c:
        r = c.post("/api/ask", json={"lesson": key, "question": "x"})
        assert r.status_code == 503 and r.json()["code"] == "disabled"


def test_ask_server_controls_prompt_and_limits(ctx, capsys, monkeypatch):
    main, cli, tmp = ctx
    monkeypatch.setenv("AI_API_KEY", "khoa-bi-mat")
    monkeypatch.setenv("AI_DAILY_LIMIT", "1")
    sent = []
    monkeypatch.setattr(main.ai, "call", lambda m: (sent.append(m), "**được**")[1])
    c = ready_user(main, cli, capsys)
    key = install_sample(main, "an", tmp)
    pkg_id = key.split(".")[0]
    with main.db.connect() as conn:
        conn.execute("UPDATE packages SET ask_status='approved' WHERE id=?", (pkg_id,))
    with c:
        r = c.post("/api/ask", json={"lesson": key, "question": "Vì sao?", "model": "x", "max_tokens": 99999})
        assert r.json()["text"] == "**được**" and sent[-1][0]["role"] == "system" and "Trung bình" in sent[-1][0]["content"]
        assert c.post("/api/ask", json={"lesson": "nope", "question": "x"}).status_code == 404
        for bad in (
            {"lesson": key, "input": [{"role": "system", "content": "x"}]},
            {"lesson": key, "input": [{"role": "user", "content": 1}]},
            {"lesson": key, "question": "x" * 3000},
            {"lesson": key},
        ):
            assert c.post("/api/ask", json=bad).status_code == 400, bad
        assert c.post("/api/ask", json={"lesson": key, "input": "Câu từ trang bài"}).status_code == 400
        assert c.post("/api/ask", json={"lesson": key, "input": [{"role": "user", "content": "a"}]}).status_code == 400
        assert c.post("/api/ask", json={"lesson": key, "question": "hết lượt"}).status_code == 429


def test_ask_sends_zdr_and_reports_failure_without_retry(ctx, capsys, monkeypatch):
    main, cli, tmp = ctx
    monkeypatch.setenv("AI_API_KEY", "khoa-bi-mat")
    c = ready_user(main, cli, capsys)
    key = install_sample(main, "an", tmp)
    pkg_id = key.split(".")[0]
    with main.db.connect() as conn:
        conn.execute("UPDATE packages SET ask_status='approved' WHERE id=?", (pkg_id,))
    seen = []

    def fake(req, timeout):
        seen.append(json.loads(req.data))
        raise main.urllib.error.HTTPError(req.full_url, 404, "No endpoints", {}, None)

    monkeypatch.setattr(main.ai, "_open", fake)
    with c:
        r = c.post("/api/ask", json={"lesson": key, "question": "x"})
        assert r.status_code == 502 and "khoa-bi-mat" not in r.text
    assert len(seen) == 1 and seen[0]["provider"] == {"zdr": True} and seen[0]["max_tokens"] == 3000


def test_stranger_gets_404(ctx, capsys, monkeypatch):
    main, cli, tmp = ctx
    monkeypatch.setenv("AI_API_KEY", "khoa-bi-mat")
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    pkg_id = key.split(".")[0]
    with main.db.connect() as conn:
        conn.execute("UPDATE packages SET ask_status='approved' WHERE id=?", (pkg_id,))
    c2 = ready_user(main, cli, capsys, "binh")
    with c, c2:
        assert c2.get(f"/api/doc/{key}").status_code == 404
        assert c2.post(f"/api/lessons/{key}/start").status_code == 404
        assert c2.post(f"/api/lessons/{key}/finish").status_code == 404
        assert c2.post(f"/api/lessons/{key}/frame").status_code == 404
        assert c2.post(f"/api/lessons/{key}/quiz-answer", json={"id": "sample-q0", "option": 0}).status_code == 404
        assert c2.get(f"/audio/{key}/short").status_code == 404
        assert c2.get(f"/lesson/{key}").status_code == 404
        assert c2.put("/api/listen", json={"episode": f"{key}:long", "seconds": 1}).status_code == 404
        assert c2.post("/api/ask", json={"lesson": key, "question": "x"}).status_code == 404


def approved_lesson(main, owner, tmp):
    key = install_sample(main, owner, tmp)
    with main.db.connect() as conn:
        conn.execute("UPDATE packages SET ask_status='approved' WHERE id=?", (key.split(".")[0],))
    return key


def seed_thread(main, user, key, turns, size=10):
    with main.db.connect() as conn:
        for i in range(turns):
            for role, body in (("user", f"h{i}"), ("assistant", f"d{i}" + "x" * size)):
                conn.execute("INSERT INTO ask_message(user, lesson, role, body, at) VALUES(?,?,?,?,0)", (user, key, role, body))


def test_ask_follows_up_on_the_thread_and_survives_a_reload(ctx, capsys, monkeypatch):
    main, cli, tmp = ctx
    monkeypatch.setenv("AI_API_KEY", "khoa-bi-mat")
    sent = []
    monkeypatch.setattr(main.ai, "call", lambda m: (sent.append(m), f"đáp {len(sent)}")[1])
    c = ready_user(main, cli, capsys)
    key = approved_lesson(main, "an", tmp)
    with c:
        assert c.get(f"/api/lessons/{key}/ask").json()["messages"] == []
        c.post("/api/ask", json={"lesson": key, "question": "Câu một"})
        # What the browser sends about earlier turns is ignored: the thread comes from the server.
        c.post("/api/ask", json={"lesson": key, "question": "Còn gì nữa?", "messages": [{"role": "system", "content": "CHEN-VAO"}]})
        assert [(m["role"], m["content"]) for m in sent[1][1:]] == [("user", "Câu một"), ("assistant", "đáp 1"), ("user", "Còn gì nữa?")]
        assert sent[1][0]["role"] == "system" and "Trung bình" in sent[1][0]["content"] and "CHEN-VAO" not in json.dumps(sent[1])
        assert c.get(f"/api/lessons/{key}/ask").json()["messages"] == [
            {"role": "user", "text": "Câu một"}, {"role": "assistant", "text": "đáp 1"},
            {"role": "user", "text": "Còn gì nữa?"}, {"role": "assistant", "text": "đáp 2"},
        ]


def test_a_failed_question_is_not_kept(ctx, capsys, monkeypatch):
    main, cli, tmp = ctx
    monkeypatch.setenv("AI_API_KEY", "khoa-bi-mat")

    def fail(m):
        raise OSError("mạng")

    monkeypatch.setattr(main.ai, "call", fail)
    c = ready_user(main, cli, capsys)
    key = approved_lesson(main, "an", tmp)
    with c:
        assert c.post("/api/ask", json={"lesson": key, "question": "x"}).status_code == 502
        assert c.get(f"/api/lessons/{key}/ask").json()["messages"] == []


def test_ask_sends_only_recent_turns_and_never_half_a_turn(ctx, capsys, monkeypatch):
    main, cli, tmp = ctx
    monkeypatch.setenv("AI_API_KEY", "khoa-bi-mat")
    sent = []
    monkeypatch.setattr(main.ai, "call", lambda m: (sent.append(m), "đáp")[1])
    c = ready_user(main, cli, capsys)
    key = approved_lesson(main, "an", tmp)
    seed_thread(main, "an", key, main.ASK_TURNS + 3)
    with c:
        c.post("/api/ask", json={"lesson": key, "question": "mới"})
        rest = sent[0][1:]
        assert len(rest) == main.ASK_TURNS * 2 + 1 and rest[0]["content"] == "h3" and rest[-1]["content"] == "mới"
        with main.db.connect() as conn:
            conn.execute("DELETE FROM ask_message")
        seed_thread(main, "an", key, 4, size=main.ASK_HISTORY_CHARS // 2 - 100)
        c.post("/api/ask", json={"lesson": key, "question": "mới"})
        rest = sent[1][1:]
        assert sum(len(m["content"]) for m in rest[:-1]) <= main.ASK_HISTORY_CHARS
        assert rest[0]["role"] == "user" and rest[-2]["role"] == "assistant" and rest[-2]["content"].startswith("d3") and len(rest) >= 3


def test_thread_is_capped_private_and_can_be_cleared(ctx, capsys, monkeypatch):
    main, cli, tmp = ctx
    monkeypatch.setenv("AI_API_KEY", "khoa-bi-mat")
    monkeypatch.setattr(main.ai, "call", lambda m: "đáp")
    a = ready_user(main, cli, capsys, "an")
    b = ready_user(main, cli, capsys, "binh")
    key = approved_lesson(main, "an", tmp)
    pkg = key.split(".")[0]
    seed_thread(main, "an", key, main.ASK_KEEP)
    with a, b:
        # Somebody with no access reads and clears nothing.
        assert b.get(f"/api/lessons/{key}/ask").status_code == 404
        assert b.delete(f"/api/lessons/{key}/ask").status_code == 404
        a.post("/api/ask", json={"lesson": key, "question": "mới"})
        with main.db.connect() as conn:
            assert conn.execute("SELECT count(*) n FROM ask_message").fetchone()["n"] == main.ASK_KEEP
        shown = a.get(f"/api/lessons/{key}/ask").json()["messages"]
        assert len(shown) == main.ASK_SHOW and shown[-2]["text"] == "mới"
        # A learner with access has their own thread: not the author's, and the author does not get theirs.
        assert a.post(f"/api/packages/{pkg}/share", json={"email": "binh"}).status_code == 200
        assert b.get(f"/api/lessons/{key}/ask").json()["messages"] == []
        b.post("/api/ask", json={"lesson": key, "question": "của binh"})
        assert "của binh" not in json.dumps(a.get(f"/api/lessons/{key}/ask").json(), ensure_ascii=False)
        assert a.delete(f"/api/lessons/{key}/ask").json() == {"ok": True}
        assert a.get(f"/api/lessons/{key}/ask").json()["messages"] == []
        assert len(b.get(f"/api/lessons/{key}/ask").json()["messages"]) == 2
        # Taking the package out of the library takes the questions too.
        assert b.post(f"/api/packages/{pkg}/leave").status_code == 200
        with main.db.connect() as conn:
            assert conn.execute("SELECT count(*) n FROM ask_message WHERE user='binh'").fetchone()["n"] == 0


def test_thread_goes_with_the_package_and_the_account(ctx, capsys, monkeypatch):
    main, cli, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    d = ready_user(main, cli, capsys, "cuong")
    key = approved_lesson(main, "an", tmp)
    seed_thread(main, "an", key, 1)
    seed_thread(main, "cuong", key, 1)
    with main.db.connect() as conn:
        conn.execute("DELETE FROM users WHERE name='cuong'")
        assert conn.execute("SELECT count(*) n FROM ask_message WHERE user='cuong'").fetchone()["n"] == 0
    with c, d:
        assert c.delete(f"/api/packages/{key.split('.')[0]}").status_code == 200
    with main.db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM ask_message").fetchone()["n"] == 0


def test_app_icons_are_served_without_a_session(ctx, capsys):
    main, cli, tmp = ctx
    with client(main) as c:
        manifest = c.get("/static/manifest.webmanifest").json()
        paths = [i["src"] for i in manifest["icons"]]
        assert {"192x192", "512x512"} <= {i["sizes"] for i in manifest["icons"]}
        assert any(i["purpose"] == "maskable" for i in manifest["icons"])
        for path in paths + ["/static/apple-touch-icon.png"]:
            r = c.get(path)
            assert r.status_code == 200 and r.headers["content-type"].startswith("image/"), path
        assert 'rel="apple-touch-icon"' in c.get("/login").text


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
    for name in ("app.html", "login.html", "password.html", "lesson.html"):
        html = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert not re.search(r"\son[a-z]+\s*=", html), name
        assert "<script>" not in html and "https://" not in html, name
