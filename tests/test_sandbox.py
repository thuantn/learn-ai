"""Tests for the sandboxed lesson route and signed tokens."""
import base64
import importlib
import json
import os
import pathlib
import sys
import time

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ORIGIN = "https://testserver"
GOOD = "ngựa vàng chạy qua cầu mây"


def frame_get(c, url, **kw):
    return c.get(url, headers={"Sec-Fetch-Dest": "iframe"}, **kw)


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


def token_from(url):
    return url.split("/")[2]


def user_id_from_db(main, name):
    with main.db.connect() as c:
        return c.execute("SELECT rowid FROM users WHERE name=?", (name,)).fetchone()["rowid"]


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    (tmp_path / "content").mkdir()
    src = ROOT / "sample"
    audio = tmp_path / "content" / "demo1" / "audio"
    audio.mkdir(parents=True)
    (audio / "short.mp3").write_bytes(b"0123456789")
    (audio / "long.mp3").write_bytes(b"abcdefghij" * 100)
    (tmp_path / "content" / "demo1" / "lesson.html").write_text(
        (src / "demo1" / "lesson.html").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "content" / "manifest.json").write_text(
        (src / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8"
    )

    packages = tmp_path / "packages"
    pkg = packages / "lessons" / "demo1"
    (pkg / "page").mkdir(parents=True)
    (pkg / "audio").mkdir(parents=True)
    (pkg / "page" / "index.html").write_text(
        "<!doctype html><html lang='vi'><body>lesson</body></html>", encoding="utf-8"
    )
    (pkg / "page" / "x.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", encoding="utf-8"
    )
    (pkg / "page" / "font.woff2").write_bytes(b"woff2-data")
    (pkg / "audio" / "tone.mp3").write_bytes(b"fake mp3 data for range request test" * 10)
    (packages / "package.json").write_text(
        json.dumps({"contract_version": "v1", "slug": "demopkg"}), encoding="utf-8"
    )

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CONTENT_DIR", str(tmp_path / "content"))
    monkeypatch.setenv("PACKAGES_DIR", str(packages))
    monkeypatch.setenv("PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("LINK_SECRET", "test-secret-32bytes-long-for-hmac-sha256")
    monkeypatch.setenv("LINK_TTL_SECONDS", "21600")
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    for name in ("app.main", "app.sandbox", "app.cli", "app.auth", "app.db", "app.contract"):
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    cli = importlib.import_module("app.cli")
    sandbox = importlib.import_module("app.sandbox")
    return main, cli, sandbox, tmp_path


def test_html_only_in_iframe(ctx, capsys):
    main, cli, _, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        r = c.post("/api/lessons/demo1/frame")
        assert r.status_code == 200
        url = r.json()["url"]
        assert c.get(url).status_code == 403
        assert c.get(url, headers={"Sec-Fetch-Dest": "document"}).status_code == 403
        assert frame_get(c, url).status_code == 200


def test_html_headers(ctx, capsys):
    main, cli, _, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        url = c.post("/api/lessons/demo1/frame").json()["url"]
        r = frame_get(c, url)
        assert r.status_code == 200
        csp = r.headers["content-security-policy"]
        assert "sandbox allow-scripts" in csp
        assert "default-src 'none'" in csp
        assert f"script-src {ORIGIN}" in csp
        assert f"frame-ancestors {ORIGIN}" in csp
        assert "X-Frame-Options" not in r.headers
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["cross-origin-resource-policy"] == "cross-origin"
        assert r.headers["cache-control"] == "no-store"


def test_other_files_cannot_run(ctx, capsys):
    main, cli, _, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        url = c.post("/api/lessons/demo1/frame").json()["url"]
        svg_url = url.rsplit("/", 1)[0] + "/x.svg"
        r = c.get(svg_url)
        assert r.status_code == 200
        assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"


def test_font_has_cors(ctx, capsys):
    main, cli, _, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        url = c.post("/api/lessons/demo1/frame").json()["url"]
        font_url = url.rsplit("/", 1)[0] + "/font.woff2"
        r = c.get(font_url)
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == "*"


def test_token_tampered_or_expired(ctx, capsys):
    main, cli, sandbox, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        url = c.post("/api/lessons/demo1/frame").json()["url"]
        token = token_from(url)
        tampered_sig = token[:-1] + ("A" if token[-1] != "A" else "B")
        assert tampered_sig != token
        assert sandbox.read_token(tampered_sig, time.time()) is None
        assert frame_get(c, f"/s/{tampered_sig}/page/index.html").status_code == 403
        parts = token.split(".")
        tampered_payload = parts[0][:-1] + ("A" if parts[0][-1] != "A" else "B") + "." + parts[1]
        assert frame_get(c, f"/s/{tampered_payload}/page/index.html").status_code == 403
        uid = user_id_from_db(main, "an")
        expired = sandbox.make_token(uid, "demo1", time.time() - 100000)
        assert frame_get(c, f"/s/{expired}/page/index.html").status_code == 403


def test_token_has_no_email(ctx, capsys):
    main, cli, _, _ = ctx
    name = "hoc.sinh@example.com"
    c = ready_user(main, cli, capsys, name)
    with c:
        url = c.post("/api/lessons/demo1/frame").json()["url"]
        token = token_from(url)
        payload_b64 = token.split(".", 1)[0]
        pad = 4 - len(payload_b64) % 4
        if pad != 4:
            payload_b64 += "=" * pad
        decoded = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
        assert name not in decoded


def test_answers_and_content_not_served(ctx, capsys):
    main, cli, _, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        url = c.post("/api/lessons/demo1/frame").json()["url"]
        token = token_from(url)
        assert frame_get(c, f"/s/{token}/lesson.json").status_code == 404
        assert frame_get(c, f"/s/{token}/content.md").status_code == 404
        assert frame_get(c, f"/s/{token}/page/../lesson.json").status_code == 404


def test_quiz_answer_graded_by_server(ctx, capsys):
    main, cli, _, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        endpoint = "/api/lessons/demo1/quiz-answer"
        assert c.post(endpoint, json={"id": "demo1-q0", "option": 1}).json() == {"correct": True}
        assert c.get("/api/cards/due").json()["cards"] == []
        assert c.post(endpoint, json={"id": "demo1-q0", "option": 0}).json() == {"correct": False}
        cards = c.get("/api/cards/due").json()["cards"]
        assert len(cards) == 1 and cards[0]["id"] == "demo1-q0" and cards[0]["wrong"]
        assert c.post(endpoint, json={"id": "demo1-q0", "option": True}).status_code == 400
        assert c.post(endpoint, json={"id": "unknown-quiz", "option": 0}).status_code == 400


def test_token_for_other_lesson_refused(ctx, capsys):
    main, cli, sandbox, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        uid = user_id_from_db(main, "an")
        token = sandbox.make_token(uid, "other-lesson", time.time())
        assert frame_get(c, f"/s/{token}/page/index.html").status_code == 404


def test_removed_user_loses_access_at_once(ctx, capsys):
    main, cli, _, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        url = c.post("/api/lessons/demo1/frame").json()["url"]
    cli.main(["remove-user", "an"])
    c2 = client(main)
    assert frame_get(c2, url).status_code == 403


def test_traversal_and_symlink(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        url = c.post("/api/lessons/demo1/frame").json()["url"]
        token = token_from(url)
        assert frame_get(c, f"/s/{token}/page/../secret.txt").status_code == 404
        assert frame_get(c, f"/s/{token}/page/..%2fsecret.txt").status_code == 404
        secret = tmp / "outside-secret.txt"
        secret.write_text("leak", encoding="utf-8")
        link = tmp / "packages" / "lessons" / "demo1" / "page" / "escape.html"
        try:
            os.symlink(str(secret), str(link))
        except OSError:  # Windows without symlink permission
            pytest.skip("cannot create symlink on this platform")
        assert frame_get(c, f"/s/{token}/page/escape.html").status_code == 404


def test_no_cookie_needed_and_none_set(ctx, capsys):
    main, cli, _, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        url = c.post("/api/lessons/demo1/frame").json()["url"]
    c2 = client(main)
    r = frame_get(c2, url)
    assert r.status_code == 200
    assert "set-cookie" not in r.headers


def test_audio_range_206_in_sandbox(ctx, capsys):
    main, cli, _, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        url = c.post("/api/lessons/demo1/frame").json()["url"]
        audio_url = url.rsplit("/", 1)[0] + "/../audio/tone.mp3"
        r = c.get(audio_url, headers={"Range": "bytes=0-9"})
        assert r.status_code == 206
        assert r.content == b"fake mp3 d"
        assert "accept-ranges" in r.headers


def test_frame_endpoint_needs_session(ctx):
    main, _, _, _ = ctx
    c = client(main)
    assert c.post("/api/lessons/demo1/frame").status_code == 401


def test_frame_learner_hides_user(ctx, capsys):
    main, cli, _, _ = ctx
    name = "hoc.sinh@example.com"
    c = ready_user(main, cli, capsys, name)
    with c:
        r = c.post("/api/lessons/demo1/frame")
        body = r.json()
        learner = body["learner"]
        uid = str(user_id_from_db(main, name))
        assert name not in learner and uid not in learner
        assert len(learner) == 64
        int(learner, 16)


def test_disabled_without_secret(ctx, capsys, monkeypatch):
    main, cli, _, _ = ctx
    monkeypatch.delenv("LINK_SECRET", raising=False)
    c = client(main)
    assert c.get("/s/dummy/page/index.html").status_code == 404
    c2 = ready_user(main, cli, capsys, "an")
    with c2:
        assert c2.post("/api/lessons/demo1/frame").status_code == 404


def test_app_csp_frames_only_lesson_path(ctx):
    main, _, _, _ = ctx
    with client(main) as c:
        h = c.get("/login").headers["content-security-policy"]
        assert f"frame-src {ORIGIN}/s/" in h


def test_no_access_log_of_token():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--no-access-log" in dockerfile
