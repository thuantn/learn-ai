"""Tests for package catalog and database migrations."""
import importlib
import json
import os
import pathlib
import re
import shutil
import sqlite3
import sys
import time
import types

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOOD = "ngựa vàng chạy qua cầu mây"
ORIGIN = "https://testserver"
TONE = ROOT / "tests" / "fixtures" / "tone.mp3"


def _fresh_db_module(tmp_path, monkeypatch, **extra_env):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PACKAGES_DIR", str(tmp_path / "packages"))
    monkeypatch.setenv("PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("LINK_SECRET", "test-secret-32bytes-long-for-hmac-sha256")
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    for name in (
        "app.main",
        "app.cli",
        "app.auth",
        "app.db",
        "app.catalog",
        "app.sandbox",
        "app.contract",
        "app.bundle",
        "app.uploads",
        "app.ai",
        "app.admin",
        "app.practice",
        "app.practice_api",
        "app.web_util",
    ):
        sys.modules.pop(name, None)
        # `from . import x` reads the package attribute first, so it must go too.
        if "app" in sys.modules and name in ("app.practice", "app.practice_api"):
            sys.modules["app"].__dict__.pop(name.split(".")[1], None)
    for k, v in extra_env.items():
        monkeypatch.setenv(k, v)
    db = importlib.import_module("app.db")
    db.init()
    catalog = importlib.import_module("app.catalog")
    practice = importlib.import_module("app.practice")
    cli = importlib.import_module("app.cli")
    main = importlib.import_module("app.main")
    return types.SimpleNamespace(main=main, cli=cli, catalog=catalog, practice=practice, db=db, tmp=tmp_path)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    return _fresh_db_module(tmp_path, monkeypatch)


def _client(ctx):
    return TestClient(ctx.main.app, base_url=ORIGIN, headers={"Origin": ORIGIN}, follow_redirects=False)


def _add_user(cli, capsys, name):
    cli.main(["add-user", name])
    return capsys.readouterr().out.rsplit(": ", 1)[1].strip()


def _login(c, name, password):
    return c.post("/login", json={"username": name, "password": password})


def _ready_client(ctx, capsys, name="an"):
    temp = _add_user(ctx.cli, capsys, name)
    c = _client(ctx)
    assert _login(c, name, temp).status_code == 200
    assert c.post("/api/change-password", json={"password": GOOD}).status_code == 200
    return c


def _make_package(
    root,
    slug="demo",
    title="Demo",
    topic="test",
    description="x",
    lesson_id="demo",
    cards=None,
    quiz=None,
    tracks=None,
    content="# x\n",
    summary=None,
):
    root = pathlib.Path(root)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    package = {
        "contract_version": "v1",
        "slug": slug,
        "title": title,
        "topic": topic,
        "description": description,
        "lessons": [lesson_id],
    }
    (root / "package.json").write_text(json.dumps(package), encoding="utf-8")

    lesson_dir = root / "lessons" / lesson_id
    lesson_dir.mkdir(parents=True)
    lesson = {
        "title": title,
        "summary": summary or ["a", "b", "c"],
        "cards": cards if cards is not None else [
            {"id": f"{lesson_id}-c{i}", "q": f"q{i}", "a": f"a{i}"}
            for i in range(5)
        ],
        "quiz": quiz if quiz is not None else [],
        "tracks": tracks if tracks is not None else {},
    }
    (lesson_dir / "lesson.json").write_text(json.dumps(lesson), encoding="utf-8")

    page_dir = lesson_dir / "page"
    page_dir.mkdir()
    (page_dir / "index.html").write_text(
        "<!doctype html><html lang='vi'><body>x</body></html>", encoding="utf-8"
    )
    if content is not None:
        (lesson_dir / "content.md").write_text(content, encoding="utf-8")

    if tracks:
        audio_dir = lesson_dir / "audio"
        audio_dir.mkdir()
        for key, track in tracks.items():
            shutil.copy(TONE, audio_dir / track["file"])
    return root


def _first_key(catalog, user):
    with catalog.db.connect() as c:
        rows = catalog.lessons_for(c, user)
    assert rows
    return rows[0]["id"]


# ---------- Migrations ----------

def test_migration_keeps_rows_from_old_database(tmp_path, monkeypatch):
    db_mod = _fresh_db_module(tmp_path, monkeypatch).db
    # Simulate an old database with user_version 0.
    db_path = tmp_path / "data" / "learn.db"
    for ext in ("", "-wal", "-shm"):
        p = pathlib.Path(str(db_path) + ext)
        if p.exists():
            p.unlink()
    conn = sqlite3.connect(db_path)
    conn.executescript(db_mod.MIGRATIONS[0])
    conn.execute("INSERT INTO users VALUES('an','hash',1,?)", (time.time(),))
    conn.execute("INSERT INTO card_state VALUES('an','c1','l1',0,'{}')")
    conn.commit()
    conn.close()

    db_mod.init()
    with db_mod.connect() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == len(db_mod.MIGRATIONS)
        assert c.execute("SELECT name FROM users WHERE name='an'").fetchone()["name"] == "an"
        assert c.execute("SELECT card_id FROM card_state WHERE user='an'").fetchone()["card_id"] == "c1"
    db_mod.init()  # idempotent


def test_failed_migration_leaves_version_and_schema_unchanged(tmp_path, monkeypatch):
    db_mod = _fresh_db_module(tmp_path, monkeypatch).db
    db_path = tmp_path / "data" / "learn.db"
    for ext in ("", "-wal", "-shm"):
        p = pathlib.Path(str(db_path) + ext)
        if p.exists():
            p.unlink()
    conn = sqlite3.connect(db_path)
    conn.executescript(db_mod.MIGRATIONS[0])
    conn.execute("INSERT INTO users VALUES('an','hash',1,?)", (time.time(),))
    conn.commit()
    conn.close()

    original = list(db_mod.MIGRATIONS)
    db_mod.MIGRATIONS = [
        original[0],
        "ALTER TABLE users ADD COLUMN zzz TEXT; CREATE TABLE BROKEN (",
    ]
    with pytest.raises(Exception):
        db_mod.init()
    with sqlite3.connect(tmp_path / "data" / "learn.db") as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1
        assert c.execute("SELECT name FROM pragma_table_info('users') WHERE name='zzz'").fetchone() is None

    db_mod.MIGRATIONS = original
    db_mod.init()
    with sqlite3.connect(tmp_path / "data" / "learn.db") as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == len(original)


def test_backup_failure_stops_migration(tmp_path, monkeypatch):
    db_mod = _fresh_db_module(tmp_path, monkeypatch, BACKUP_DIR=str(tmp_path / "bk")).db
    db_path = tmp_path / "data" / "learn.db"
    for ext in ("", "-wal", "-shm"):
        p = pathlib.Path(str(db_path) + ext)
        if p.exists():
            p.unlink()
    conn = sqlite3.connect(db_path)
    conn.executescript(db_mod.MIGRATIONS[0])
    conn.execute("PRAGMA user_version=1")
    conn.execute("INSERT INTO users VALUES('an','hash',1,?)", (time.time(),))
    conn.commit()
    conn.close()

    def fail(_dest, _version):
        raise RuntimeError("disk full")

    monkeypatch.setattr(db_mod, "_backup_premigrate", fail)
    with pytest.raises(RuntimeError):
        db_mod.init()
    with sqlite3.connect(tmp_path / "data" / "learn.db") as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "packages" not in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_premigration_backup_survives_first_backup_loop(tmp_path, monkeypatch):
    db_mod = _fresh_db_module(tmp_path, monkeypatch, BACKUP_DIR=str(tmp_path / "bk")).db
    db_path = tmp_path / "data" / "learn.db"
    for ext in ("", "-wal", "-shm"):
        p = pathlib.Path(str(db_path) + ext)
        if p.exists():
            p.unlink()
    conn = sqlite3.connect(db_path)
    conn.executescript(db_mod.MIGRATIONS[0])
    conn.execute("PRAGMA user_version=1")
    conn.execute("INSERT INTO users VALUES('an','hash',1,?)", (time.time(),))
    conn.commit()
    conn.close()

    db_mod.init()
    prem = list((tmp_path / "bk").glob("premigrate-*"))
    assert len(prem) == 1
    db_mod.backup(str(tmp_path / "bk"))
    assert prem[0].exists()
    old = sqlite3.connect(prem[0])
    assert old.execute("SELECT name FROM sqlite_master WHERE name='packages'").fetchone() is None
    old.close()


# ---------- Catalog install and access ----------

def test_install_gives_server_ids(ctx, tmp_path):
    ctx.cli.main(["add-user", "an"])
    copy = tmp_path / "sample-copy"
    shutil.copytree(ROOT / "sample" / "package", copy)
    res = ctx.catalog.install_version("an", copy)
    assert re.fullmatch(r"p[0-9a-f]{12}", res["id"])
    assert res["version"] == 1 and res["created"] is True
    with ctx.db.connect() as c:
        lessons = ctx.catalog.lessons_for(c, "an")
        assert len(lessons) == 1
        key = lessons[0]["id"]
        assert re.fullmatch(r"p[0-9a-f]{12}\.sample", key)
        assert {card["id"] for card in lessons[0]["cards"]} == {"sample-c1", "sample-c2", "sample-c3", "sample-c4", "sample-c5"}


def test_same_slug_other_owner_is_separate_package(ctx, tmp_path):
    for name in ("an", "binh"):
        ctx.cli.main(["add-user", name])
    pkg = tmp_path / "sample-copy"
    shutil.copytree(ROOT / "sample" / "package", pkg)
    a = ctx.catalog.install_version("an", pkg)
    b = ctx.catalog.install_version("binh", pkg)
    assert a["id"] != b["id"]
    with ctx.db.connect() as c:
        an_key = ctx.catalog.lessons_for(c, "an")[0]["id"]
        assert ctx.catalog.lesson_for(c, "binh", an_key) is None


def test_only_owner_and_shared_can_read(ctx, tmp_path):
    for name in ("an", "binh"):
        ctx.cli.main(["add-user", name])
    pkg = tmp_path / "sample-copy"
    shutil.copytree(ROOT / "sample" / "package", pkg)
    pid = ctx.catalog.install_version("an", pkg)["id"]
    with ctx.db.connect() as c:
        key = ctx.catalog.lessons_for(c, "an")[0]["id"]
        assert ctx.catalog.lesson_for(c, "binh", key) is None
        c.execute(
            "INSERT INTO package_access(package_id, user, via, granted_at) VALUES(?,?,?,?)",
            (pid, "binh", "share", time.time()),
        )
        assert ctx.catalog.lesson_for(c, "binh", key) is not None
        c.execute("UPDATE package_access SET revoked_at=? WHERE package_id=? AND user=?", (time.time(), pid, "binh"))
        assert ctx.catalog.lesson_for(c, "binh", key) is None


def test_update_swaps_pointer_and_removes_old_files(ctx):
    ctx.cli.main(["add-user", "an"])
    pkg1 = _make_package(ctx.tmp / "v1", slug="demo", title="V1")
    res1 = ctx.catalog.install_version("an", pkg1)
    key = _first_key(ctx.catalog, "an")
    old_dir = ctx.catalog.lesson_dir(ctx.db.connect(), key)

    pkg2 = _make_package(ctx.tmp / "v2", slug="demo", title="V2")
    res2 = ctx.catalog.install_version("an", pkg2)
    new_dir = ctx.catalog.lesson_dir(ctx.db.connect(), key)

    assert res2["id"] == res1["id"]
    assert res2["version"] > res1["version"]
    assert not old_dir.exists()
    assert new_dir.exists()
    with ctx.db.connect() as c:
        assert ctx.catalog.lesson_for(c, "an", key)["title"] == "V2"


def test_sweep_removes_only_older_versions(ctx):
    ctx.cli.main(["add-user", "an"])
    pkg = _make_package(ctx.tmp / "p", slug="demo")
    res = ctx.catalog.install_version("an", pkg)
    pkg_dir = pathlib.Path(os.environ["PACKAGES_DIR"])

    orphan = pkg_dir / ("p" + "a" * 12) / "1"
    orphan.mkdir(parents=True)
    (orphan / "x.txt").write_text("x", encoding="utf-8")

    other = pkg_dir / "not-a-package" / "x.txt"
    other.parent.mkdir(parents=True)
    other.write_text("x", encoding="utf-8")

    leftover = pkg_dir / res["id"] / "99"
    leftover.mkdir(parents=True)
    (leftover / "x.txt").write_text("x", encoding="utf-8")

    older = pkg_dir / res["id"] / "0"
    older.mkdir(parents=True)

    ctx.catalog.sweep()
    assert orphan.exists(), "may be the only copy after a database restore"
    assert other.exists()
    assert leftover.exists(), "may be the only copy after a database restore"
    assert not older.exists()
    assert (pkg_dir / res["id"] / str(res["version"])).exists()


def test_lesson_lists_leave_out_full_text_but_ask_still_gets_it(ctx):
    ctx.cli.main(["add-user", "an"])
    pkg = _make_package(ctx.tmp / "p", slug="demo")
    lesson_dir = next((pkg / "lessons").iterdir())
    (lesson_dir / "content.md").write_text("toàn văn", encoding="utf-8")
    res = ctx.catalog.install_version("an", pkg)
    with ctx.db.connect() as c:
        listed = ctx.catalog.lessons_for(c, "an")[0]
        assert listed["content"] == ""
        assert ctx.catalog.lesson_for(c, "an", listed["id"])["content"] == "toàn văn"


def test_retry_after_crash_with_leftover_version_dir(ctx):
    ctx.cli.main(["add-user", "an"])
    pkg = _make_package(ctx.tmp / "p", slug="demo")
    res = ctx.catalog.install_version("an", pkg)
    pkg_dir = pathlib.Path(os.environ["PACKAGES_DIR"])
    leftover = pkg_dir / res["id"] / "99"
    leftover.mkdir(parents=True)
    (leftover / "x.txt").write_text("x", encoding="utf-8")

    pkg2 = _make_package(ctx.tmp / "p2", slug="demo", title="V2")
    res2 = ctx.catalog.install_version("an", pkg2)
    assert res2["version"] == 100
    new_dir = pkg_dir / res["id"] / str(res2["version"])
    assert new_dir.exists()
    assert not (new_dir / "99").exists()  # not nested inside leftover dir


def test_two_packages_same_bare_ids_do_not_collide(ctx, capsys):
    ca = _ready_client(ctx, capsys, "an")
    cb = _ready_client(ctx, capsys, "binh")
    cards = [{"id": f"c{i}", "q": f"q{i}", "a": f"a{i}"} for i in range(1, 6)]
    quiz = [{"id": "q1", "q": "Câu của an?", "options": ["a", "b"], "answer": 0}]
    pkg_a = _make_package(ctx.tmp / "a", slug="pkg-a", lesson_id="demo", cards=cards, quiz=quiz)
    pkg_b = _make_package(
        ctx.tmp / "b", slug="pkg-b", lesson_id="demo",
        cards=[{**c, "q": c["q"] + "-b", "a": c["a"] + "-b"} for c in cards],
        quiz=[{**quiz[0], "q": "Câu của binh?"}],
    )
    ctx.catalog.install_version("an", pkg_a)
    pid_b = ctx.catalog.install_version("binh", pkg_b)["id"]
    key_a = _first_key(ctx.catalog, "an")
    key_b = _first_key(ctx.catalog, "binh")
    with ctx.db.connect() as c:
        c.execute("INSERT INTO package_access VALUES(?,?,'email',?,NULL)", (pid_b, "an", time.time()))
    with ca, cb:
        ca.post(f"/api/lessons/{key_a}/start")
        cb.post(f"/api/lessons/{key_b}/start")
        a_cards = ca.get("/api/cards/due").json()["cards"]
        b_cards = cb.get("/api/cards/due").json()["cards"]
        assert {c["target_id"] for c in a_cards} == {"c1", "c2", "c3", "c4", "c5"}
        assert {c["target_id"] for c in b_cards} == {"c1", "c2", "c3", "c4", "c5"}
        assert all("-b" not in c["q"] for c in a_cards)
        assert all("-b" in c["q"] for c in b_cards)
        # The same learner answers bare id q1 wrong in both packages: two separate cards, each with its own text.
        assert ca.post(f"/api/lessons/{key_a}/quiz-answer", json={"id": "q1", "option": 1}).json() == {"correct": False}
        assert ca.post(f"/api/lessons/{key_b}/quiz-answer", json={"id": "q1", "option": 1}).json() == {"correct": False}
        wrong = {c["lesson"]: c["q"] for c in ca.get("/api/cards/due").json()["cards"] if c["target_id"] == "q1"}
        assert wrong == {key_a: "Câu của an?", key_b: "Câu của binh?"}


def test_corrected_quiz_shows_new_text_on_wrong_card(ctx, capsys):
    c = _ready_client(ctx, capsys, "an")
    quiz = [{"id": "q1", "q": "Câu cũ?", "options": ["a", "b"], "answer": 0, "why": "vì cũ"}]
    pkg = _make_package(ctx.tmp / "v1", slug="demo", quiz=quiz)
    ctx.catalog.install_version("an", pkg)
    key = _first_key(ctx.catalog, "an")
    with c:
        c.post(f"/api/lessons/{key}/start")
        c.post(f"/api/lessons/{key}/quiz-answer", json={"id": "q1", "option": 1})
        cards = c.get("/api/cards/due").json()["cards"]
        assert any(c["target_id"] == "q1" and "Câu cũ?" in c["q"] for c in cards)

        quiz2 = [{"id": "q1", "q": "Câu mới?", "options": ["a", "b"], "answer": 0, "why": "vì mới"}]
        pkg2 = _make_package(ctx.tmp / "v2", slug="demo", quiz=quiz2)
        ctx.catalog.install_version("an", pkg2)
        cards = c.get("/api/cards/due").json()["cards"]
        assert any(c["target_id"] == "q1" and "Câu mới?" in c["q"] for c in cards)

        pkg3 = _make_package(ctx.tmp / "v3", slug="demo", quiz=[])
        ctx.catalog.install_version("an", pkg3)
        cards = c.get("/api/cards/due").json()["cards"]
        assert not any(c["target_id"] == "q1" for c in cards)


def test_due_cards_not_starved_by_inaccessible_rows(ctx, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "0")
    for name in ("an", "binh"):
        ctx.cli.main(["add-user", name])
    with ctx.db.connect() as c:
        for name in ("an", "binh"):
            c.execute("UPDATE users SET pw_hash=?, must_change=0 WHERE name=?", (ctx.main.auth.hash_password(GOOD), name))
    cards_a = [{"id": f"c{i}", "q": "q", "a": "a"} for i in range(5)]
    pkg_a = _make_package(ctx.tmp / "a", slug="a", lesson_id="la", cards=cards_a)
    pkg_b = _make_package(ctx.tmp / "b", slug="b", lesson_id="lb", cards=[{"id": "c1", "q": "q", "a": "a"}])
    id_a = ctx.catalog.install_version("an", pkg_a)["id"]
    id_b = ctx.catalog.install_version("binh", pkg_b)["id"]
    key_b = _first_key(ctx.catalog, "binh")
    now = time.time()
    with ctx.db.connect() as c:
        for i in range(250):
            c.execute(
                "INSERT INTO card_state VALUES(?,?,?,?,?)",
                ("an", f"{id_b}.x{i}", key_b, now, ctx.main.Card().to_json()),
            )
    key_a = _first_key(ctx.catalog, "an")
    c = _client(ctx)
    assert _login(c, "an", GOOD).status_code == 200
    with c:
        c.post(f"/api/lessons/{key_a}/start")
        cards = c.get("/api/cards/due").json()["cards"]
        assert len(cards) == 5
        assert all(c["lesson"] == key_a for c in cards)


def test_update_resets_ask_when_ai_content_changes(ctx):
    ctx.cli.main(["add-user", "an"])
    cards = [{"id": f"c{i}", "q": "q", "a": "a"} for i in range(5)]
    quiz = [{"id": "q1", "q": "q", "options": ["a", "b"], "answer": 0}]
    summary = ["a", "b", "c"]
    count = 0

    def install(content="# x\n", summary=summary, cards=cards, quiz=quiz, page=None):
        nonlocal count
        count += 1
        pkg = _make_package(ctx.tmp / f"v{count}", slug="demo", content=content, summary=summary, cards=cards, quiz=quiz)
        if page:
            (pkg / "lessons" / "demo" / "page" / "index.html").write_text(page, encoding="utf-8")
        return ctx.catalog.install_version("an", pkg)["id"]

    def approve(pid):
        with ctx.db.connect() as c:
            c.execute("UPDATE packages SET ask_status='approved' WHERE id=?", (pid,))

    def status(pid):
        with ctx.db.connect() as c:
            return c.execute("SELECT ask_status FROM packages WHERE id=?", (pid,)).fetchone()["ask_status"]

    pid = install()
    approve(pid)
    install(page="<html><body>changed</body></html>")
    assert status(pid) == "approved"
    for changed in (
        {"content": "# y\n"},
        {"summary": ["a", "b", "c", "d"]},
        {"cards": [{**cards[0], "q": "changed"}] + cards[1:]},
        {"quiz": [{**quiz[0], "q": "changed"}]},
    ):
        approve(pid)
        install(**changed)
        assert status(pid) == "pending", changed
        install()  # back to the baseline content for the next case


def _ask_ctx(ctx):
    ctx.cli.main(["add-user", "an"])

    def install(n, **kw):
        return ctx.catalog.install_version("an", _make_package(ctx.tmp / f"v{n}", slug="demo", **kw))["id"]

    def set_status(pid, value):
        with ctx.db.connect() as c:
            c.execute("UPDATE packages SET ask_status=? WHERE id=?", (value, pid))

    def status(pid):
        with ctx.db.connect() as c:
            return c.execute("SELECT ask_status FROM packages WHERE id=?", (pid,)).fetchone()["ask_status"]

    return install, set_status, status


def test_update_ask_status_transitions(ctx):
    install, set_status, status = _ask_ctx(ctx)
    pid = install(0, content="# 0\n")
    for n, (before, after) in enumerate((("approved", "pending"), ("rejected", "none"), ("pending", "pending"), ("none", "none")), 1):
        set_status(pid, before)
        install(n, content=f"# {n}\n")
        assert status(pid) == after, before


def test_ask_hash_includes_lesson_title(ctx):
    install, set_status, status = _ask_ctx(ctx)
    pid = install(0, content="# x\n")
    set_status(pid, "approved")
    pkg = _make_package(ctx.tmp / "renamed", slug="demo", content="# x\n")
    path = pkg / "lessons" / "demo" / "lesson.json"
    lesson = json.loads(path.read_text(encoding="utf-8"))
    lesson["title"] = "Tên khác"
    path.write_text(json.dumps(lesson), encoding="utf-8")
    ctx.catalog.install_version("an", pkg)
    assert status(pid) == "pending"


def test_install_does_not_overwrite_admin_decision(ctx, monkeypatch):
    install, set_status, status = _ask_ctx(ctx)
    pid = install(0, content="# x\n")
    set_status(pid, "approved")
    real = ctx.catalog.shutil.copytree

    def admin_turns_it_off_meanwhile(*a, **kw):
        set_status(pid, "rejected")
        return real(*a, **kw)

    monkeypatch.setattr(ctx.catalog.shutil, "copytree", admin_turns_it_off_meanwhile)
    install(1, content="# x\n")  # same AI content, only a new version of the page
    assert status(pid) == "rejected"
