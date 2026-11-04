"""Tests for the sandboxed lesson route and signed tokens."""
import base64
import importlib
import json
import os
import pathlib
import shutil
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


def install_sample(main, owner, tmp_path, name="pkg"):
    src = ROOT / "sample" / "package"
    copy = tmp_path / name
    shutil.copytree(src, copy)
    page_dir = copy / "lessons" / "sample" / "page"
    audio_dir = copy / "lessons" / "sample" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    tone = ROOT / "tests" / "fixtures" / "tone.mp3"
    shutil.copy(tone, audio_dir / "short.mp3")
    shutil.copy(tone, audio_dir / "long.mp3")
    (audio_dir / "tone.mp3").write_bytes(b"fake mp3 data for range request test" * 10)
    (page_dir / "x.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", encoding="utf-8"
    )
    (page_dir / "font.woff2").write_bytes(b"woff2-data")
    lesson_path = copy / "lessons" / "sample" / "lesson.json"
    lesson = json.loads(lesson_path.read_text(encoding="utf-8"))
    lesson["tracks"] = {
        "short": {"file": "short.mp3", "label": "Ngắn"},
        "long": {"file": "long.mp3", "label": "Dài"},
    }
    lesson["cards"] = []
    lesson["quiz"] = [{"id": "sample-q0", "q": "?", "options": ["0", "20", "x"], "answer": 1, "why": "vì 20"}]
    lesson_path.write_text(json.dumps(lesson), encoding="utf-8")
    res = main.catalog.install_version(owner, copy)
    return f"{res['id']}.sample"


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    (tmp_path / "packages").mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PACKAGES_DIR", str(tmp_path / "packages"))
    monkeypatch.setenv("PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("LINK_SECRET", "test-secret-32bytes-long-for-hmac-sha256")
    monkeypatch.setenv("LINK_TTL_SECONDS", "21600")
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    for name in (
        "app.main",
        "app.sandbox",
        "app.cli",
        "app.auth",
        "app.db",
        "app.catalog",
        "app.contract",
        "app.bundle", "app.uploads", "app.ai", "app.admin", "app.web_util",
    ):
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    cli = importlib.import_module("app.cli")
    sandbox = importlib.import_module("app.sandbox")
    return main, cli, sandbox, tmp_path


def test_html_only_in_iframe(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with c:
        r = c.post(f"/api/lessons/{key}/frame")
        assert r.status_code == 200
        url = r.json()["url"]
        assert c.get(url).status_code == 403
        assert c.get(url, headers={"Sec-Fetch-Dest": "document"}).status_code == 403
        assert frame_get(c, url).status_code == 200


def test_html_headers(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with c:
        url = c.post(f"/api/lessons/{key}/frame").json()["url"]
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
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with c:
        url = c.post(f"/api/lessons/{key}/frame").json()["url"]
        svg_url = url.rsplit("/", 1)[0] + "/x.svg"
        r = c.get(svg_url)
        assert r.status_code == 200
        assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"


def test_font_has_cors(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with c:
        url = c.post(f"/api/lessons/{key}/frame").json()["url"]
        font_url = url.rsplit("/", 1)[0] + "/font.woff2"
        r = c.get(font_url)
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == "*"


def test_token_tampered_or_expired(ctx, capsys):
    main, cli, sandbox, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with c:
        url = c.post(f"/api/lessons/{key}/frame").json()["url"]
        token = token_from(url)
        parts = token.split(".")
        tampered_sig = parts[0] + "." + "A" * len(parts[1])
        assert tampered_sig != token
        assert sandbox.read_token(tampered_sig, time.time()) is None
        assert frame_get(c, f"/s/{tampered_sig}/page/index.html").status_code == 403
        parts = token.split(".")
        # The first character: the last one may carry only padding bits and decode to the same bytes.
        tampered_payload = ("A" if parts[0][0] != "A" else "B") + parts[0][1:] + "." + parts[1]
        assert frame_get(c, f"/s/{tampered_payload}/page/index.html").status_code == 403
        uid = user_id_from_db(main, "an")
        expired = sandbox.make_token(uid, key, time.time() - 100000)
        assert frame_get(c, f"/s/{expired}/page/index.html").status_code == 403


def test_token_has_no_email(ctx, capsys):
    main, cli, _, tmp = ctx
    name = "hoc.sinh@example.com"
    c = ready_user(main, cli, capsys, name)
    key = install_sample(main, name, tmp)
    with c:
        url = c.post(f"/api/lessons/{key}/frame").json()["url"]
        token = token_from(url)
        payload_b64 = token.split(".", 1)[0]
        pad = 4 - len(payload_b64) % 4
        if pad != 4:
            payload_b64 += "=" * pad
        decoded = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
        assert name not in decoded


def test_answers_and_content_not_served(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with c:
        url = c.post(f"/api/lessons/{key}/frame").json()["url"]
        token = token_from(url)
        assert frame_get(c, f"/s/{token}/lesson.json").status_code == 404
        assert frame_get(c, f"/s/{token}/content.md").status_code == 404
        assert frame_get(c, f"/s/{token}/page/../lesson.json").status_code == 404


def test_quiz_answer_graded_by_server(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with c:
        endpoint = f"/api/lessons/{key}/quiz-answer"
        assert c.post(endpoint, json={"id": "sample-q0", "option": 1}).json() == {"correct": True}
        assert c.get("/api/cards/due").json()["cards"] == []
        assert c.post(endpoint, json={"id": "sample-q0", "option": 0}).json() == {"correct": False}
        cards = c.get("/api/cards/due").json()["cards"]
        assert len(cards) == 1 and cards[0]["target_id"] == "sample-q0" and cards[0]["wrong"]
        assert c.post(endpoint, json={"id": "sample-q0", "option": True}).status_code == 400
        assert c.post(endpoint, json={"id": "unknown-quiz", "option": 0}).status_code == 400


def test_token_for_other_lesson_refused(ctx, capsys):
    main, cli, sandbox, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        uid = user_id_from_db(main, "an")
        token = sandbox.make_token(uid, "other-lesson", time.time())
        assert frame_get(c, f"/s/{token}/page/index.html").status_code == 403


def test_removed_user_loses_access_at_once(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with c:
        url = c.post(f"/api/lessons/{key}/frame").json()["url"]
    cli.main(["remove-user", "an"])
    c2 = client(main)
    assert frame_get(c2, url).status_code == 403


def test_traversal_and_symlink(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with c:
        url = c.post(f"/api/lessons/{key}/frame").json()["url"]
        token = token_from(url)
        assert frame_get(c, f"/s/{token}/page/../secret.txt").status_code == 404
        assert frame_get(c, f"/s/{token}/page/..%2fsecret.txt").status_code == 404
        secret = tmp / "outside-secret.txt"
        secret.write_text("leak", encoding="utf-8")
        page_dir = main.catalog.lesson_dir(main.db.connect(), key) / "page"
        link = page_dir / "escape.html"
        try:
            os.symlink(str(secret), str(link))
        except OSError:  # Windows without symlink permission
            pytest.skip("cannot create symlink on this platform")
        assert frame_get(c, f"/s/{token}/page/escape.html").status_code == 404


def test_no_cookie_needed_and_none_set(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with c:
        url = c.post(f"/api/lessons/{key}/frame").json()["url"]
    c2 = client(main)
    r = frame_get(c2, url)
    assert r.status_code == 200
    assert "set-cookie" not in r.headers


def test_audio_range_206_in_sandbox(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with c:
        url = c.post(f"/api/lessons/{key}/frame").json()["url"]
        audio_url = url.rsplit("/", 1)[0] + "/../audio/tone.mp3"
        r = c.get(audio_url, headers={"Range": "bytes=0-9"})
        assert r.status_code == 206
        assert r.content == b"fake mp3 d"
        assert "accept-ranges" in r.headers


def test_frame_endpoint_needs_session(ctx, capsys):
    main, cli, _, tmp = ctx
    add_user(cli, capsys, "an")
    c = client(main)
    key = install_sample(main, "an", tmp)
    assert c.post(f"/api/lessons/{key}/frame").status_code == 401


def test_frame_learner_hides_user(ctx, capsys):
    main, cli, _, tmp = ctx
    name = "hoc.sinh@example.com"
    c = ready_user(main, cli, capsys, name)
    key = install_sample(main, name, tmp)
    with c:
        r = c.post(f"/api/lessons/{key}/frame")
        body = r.json()
        learner = body["learner"]
        assert name not in learner
        assert len(learner) == 64
        int(learner, 16)


def test_disabled_without_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PACKAGES_DIR", str(tmp_path / "packages"))
    monkeypatch.setenv("PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.delenv("LINK_SECRET", raising=False)
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    for name in (
        "app.main",
        "app.sandbox",
        "app.cli",
        "app.auth",
        "app.db",
        "app.catalog",
        "app.contract",
        "app.bundle", "app.uploads", "app.ai", "app.admin", "app.web_util",
    ):
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    with pytest.raises(RuntimeError):
        with TestClient(main.app, base_url=ORIGIN, headers={"Origin": ORIGIN}, follow_redirects=False):
            pass


def test_app_csp_frames_only_lesson_path(ctx):
    main, _, _, _ = ctx
    with client(main) as c:
        h = c.get("/login").headers["content-security-policy"]
        assert f"frame-src {ORIGIN}/s/" in h


def test_lesson_page_needs_session(ctx, capsys):
    main, cli, _, tmp = ctx
    add_user(cli, capsys, "an")
    with client(main) as c:
        key = install_sample(main, "an", tmp)
        assert c.get(f"/lesson/{key}").status_code == 303
        assert c.get(f"/lesson/{key}").headers["location"] == "/login"


def test_lesson_page_unknown_404(ctx, capsys):
    main, cli, _, _ = ctx
    c = ready_user(main, cli, capsys, "an")
    with c:
        assert c.get("/lesson/khong-co").status_code == 404


def test_lesson_host_sandbox_flags(ctx):
    text = (ROOT / "web" / "static" / "lesson-host.js").read_text(encoding="utf-8")
    assert 'sandbox="allow-scripts"' in text
    assert "allow-same-origin" not in text
    assert "allow-popups" not in text
    assert "allow-top-navigation" not in text
    assert "allow-forms" not in text


def test_no_access_log_of_token():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--no-access-log" in dockerfile


def _page_with_theme_rules(main, tmp, key):
    """Adds a stylesheet with dark and light rules to the installed sample lesson."""
    with main.db.connect() as conn:
        base = main.catalog.lesson_dir(conn, key)
    css = "@media (prefers-color-scheme: dark){a{color:red}}\n@media (prefers-color-scheme:light) and (max-width:600px){a{color:blue}}\nb{color:green}"
    (base / "page" / "theme.css").write_bytes(css.encode("utf-8"))
    (base / "page" / "theme.js").write_text("matchMedia('(prefers-color-scheme: dark)')", encoding="utf-8")
    (base / "page" / "binary.png").write_bytes(b"(prefers-color-scheme: dark)")
    return css


def test_frame_url_carries_only_a_known_theme(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    with c:
        assert "/theme-light/page/index.html" in c.post(f"/api/lessons/{key}/frame", json={"theme": "light"}).json()["url"]
        assert "/theme-dark/page/index.html" in c.post(f"/api/lessons/{key}/frame", json={"theme": "dark"}).json()["url"]
        for other in ("blue", "../x", 3, None):
            assert "/theme-" not in c.post(f"/api/lessons/{key}/frame", json={"theme": other}).json()["url"]
        assert "/theme-" not in c.post(f"/api/lessons/{key}/frame").json()["url"]


def test_theme_path_leaves_very_large_files_alone(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    _page_with_theme_rules(main, tmp, key)
    with main.db.connect() as conn:
        big = main.catalog.lesson_dir(conn, key) / "page" / "big.js"
    body = b"matchMedia('(prefers-color-scheme: dark)');" + b" " * main.REWRITE_LIMIT
    big.write_bytes(body)
    with c:
        token = token_from(c.post(f"/api/lessons/{key}/frame").json()["url"])
        assert c.get(f"/s/{token}/theme-light/page/big.js").content == body


def test_theme_path_rewrites_colour_queries(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    css = _page_with_theme_rules(main, tmp, key)
    with c:
        token = token_from(c.post(f"/api/lessons/{key}/frame").json()["url"])
        assert c.get(f"/s/{token}/page/theme.css").text == css
        light = c.get(f"/s/{token}/theme-light/page/theme.css")
        assert light.status_code == 200 and "text/css" in light.headers["content-type"]
        assert "prefers-color-scheme" not in light.text and "b{color:green}" in light.text
        assert "@media (max-width:-1px){a{color:red}}" in light.text
        assert "@media (min-width:0) and (max-width:600px){a{color:blue}}" in light.text
        dark = c.get(f"/s/{token}/theme-dark/page/theme.css").text
        assert "@media (min-width:0){a{color:red}}" in dark and "@media (max-width:-1px) and (max-width:600px){a{color:blue}}" in dark
        assert "matchMedia('(max-width:-1px)')" in c.get(f"/s/{token}/theme-light/page/theme.js").text
        assert c.get(f"/s/{token}/theme-light/page/binary.png").content == b"(prefers-color-scheme: dark)"
        page = frame_get(c, f"/s/{token}/theme-light/page/index.html")
        assert page.status_code == 200 and page.headers.get("content-security-policy") == frame_get(c, f"/s/{token}/page/index.html").headers.get("content-security-policy")


def test_theme_path_keeps_every_guard(ctx, capsys):
    main, cli, _, tmp = ctx
    c = ready_user(main, cli, capsys, "an")
    key = install_sample(main, "an", tmp)
    _page_with_theme_rules(main, tmp, key)
    with c:
        token = token_from(c.post(f"/api/lessons/{key}/frame").json()["url"])
        assert c.get(f"/s/{token}/theme-light/page/index.html").status_code == 403  # html only inside a frame
        assert c.get(f"/s/{token}/theme-blue/page/theme.css").status_code == 404
        assert c.get(f"/s/{token}/theme-light/lesson.json").status_code == 404
        assert c.get(f"/s/{token}/theme-light/theme-dark/page/theme.css").status_code == 404
        assert c.get(f"/s/{token}/theme-light/page/../lesson.json").status_code == 404
        assert c.get(f"/s/{token}x/theme-light/page/theme.css").status_code == 403
