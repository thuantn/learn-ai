"""Tests for the two-step package upload."""
import asyncio
import io
import json
import os
import pathlib
import shutil
import time
import zipfile

import pytest
from test_catalog import _first_key, _make_package, _ready_client, ctx  # noqa: F401

ZIP = {"Content-Type": "application/zip"}
CARDS = [{"id": f"c{i}", "q": f"q{i}", "a": f"a{i}"} for i in range(5)]


def zip_of(root):
    root = pathlib.Path(root)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(root).as_posix())
    return out.getvalue()


def package_zip(ctx, name="p", **kw):
    return zip_of(_make_package(ctx.tmp / name, **kw))


def zip_from(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, body in entries:
            z.writestr(name, body)
    return out.getvalue()


def staging(ctx):
    path = pathlib.Path(os.environ["PACKAGES_DIR"]) / ".staging"
    return sorted(p.name for p in path.iterdir()) if path.exists() else []


def send(c, body):
    return c.post("/api/uploads", content=body, headers=ZIP)


def commit(c, upload_id, **kw):
    return c.post(f"/api/uploads/{upload_id}/commit", json={"attest": True, **kw})


def upload_and_commit(c, body, **kw):
    r = send(c, body)
    assert r.status_code == 200, r.text
    r2 = commit(c, r.json()["upload_id"], **kw)
    assert r2.status_code == 200, r2.text
    return r2.json()


def test_upload_then_commit_installs(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        r = send(c, package_zip(ctx, cards=CARDS))
        assert r.status_code == 200
        info = r.json()
        assert info["title"] == "Demo" and info["slug"] == "demo" and info["lessons"] == ["Demo"]
        assert info["is_update"] is False and info["removed"] == []
        assert c.get("/api/lessons").json()["lessons"] == []  # nothing changes before the commit
        assert commit(c, info["upload_id"]).json()["version"] == 1
        assert c.get("/api/lessons").json()["lessons"][0]["title"] == "Demo"
        assert staging(ctx) == []


def test_too_large_refused_before_reading(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        r = c.post("/api/uploads", content=b"x", headers={**ZIP, "Content-Length": str(ctx.main.bundle.MAX_ZIP + 1)})
        assert r.status_code == 413
        assert staging(ctx) == []


def test_lying_length_is_counted_while_streaming(ctx, capsys, monkeypatch):
    monkeypatch.setattr(ctx.main.bundle, "MAX_ZIP", 100)
    c = _ready_client(ctx, capsys)

    def body():
        for _ in range(5):
            yield b"x" * 64

    with c:
        assert c.post("/api/uploads", content=body(), headers=ZIP).status_code == 413
        assert staging(ctx) == []


def test_interrupted_upload_leaves_nothing(ctx, capsys, monkeypatch):
    c = _ready_client(ctx, capsys)

    async def broken(stream, path):
        pathlib.Path(path).write_bytes(b"partial")
        raise ctx.main.ClientDisconnect()

    monkeypatch.setattr(ctx.main.uploads, "receive", broken)
    with c:
        assert send(c, b"x").status_code == 400
        assert staging(ctx) == []
        assert ctx.main.uploads.active == {}


def test_stalled_upload_times_out(ctx):
    async def stalled():
        yield b"x"
        await asyncio.sleep(10)
        yield b"y"

    target = ctx.tmp / "s.zip"
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(ctx.main.uploads.receive(stalled(), target, chunk_timeout=0.05))


def test_stalled_upload_frees_its_slot(ctx, capsys, monkeypatch):
    c = _ready_client(ctx, capsys)

    async def stalled(stream, path):
        raise asyncio.TimeoutError

    with c:
        with monkeypatch.context() as m:
            m.setattr(ctx.main.uploads, "receive", stalled)
            assert send(c, b"x").status_code == 400
        assert staging(ctx) == []
        assert send(c, package_zip(ctx, cards=CARDS)).status_code == 200


@pytest.mark.parametrize("entries", [
    [("../evil.txt", "x")],
    [("/abs.txt", "x")],
    [("a\\b.txt", "x")],
    [("c:/evil.txt", "x")],
    [(".", "x")],
    [("a", "x"), ("a/b", "y")],
    [("package.json", "{bad")],
    [("lessons/x/lesson.json", "{}")],
    [("package.json", json.dumps({"contract_version": "v9"}))],
])
def test_bad_zips_report_problems_and_keep_running_version(ctx, capsys, entries):
    c = _ready_client(ctx, capsys)
    with c:
        upload_and_commit(c, package_zip(ctx, cards=CARDS))
        before = c.get("/api/lessons").json()
        r = send(c, zip_from(entries))
        assert r.status_code == 400
        assert r.json()["code"] == "invalid" and r.json()["problems"]
        assert os.environ["PACKAGES_DIR"] not in r.text and str(ctx.tmp) not in r.text
        assert c.get("/api/lessons").json() == before
        assert staging(ctx) == []


def test_not_a_zip(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        r = send(c, b"not a zip at all")
        assert r.status_code == 400 and r.json()["code"] == "invalid"
        assert c.post("/api/uploads", content=b"x", headers={"Content-Type": "text/plain"}).status_code == 400


def test_duplicate_names_and_symlink_refused(ctx, capsys):
    c = _ready_client(ctx, capsys)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        link = zipfile.ZipInfo("link")
        link.external_attr = 0o120777 << 16
        z.writestr(link, "/etc/passwd")
    dup = io.BytesIO()
    with pytest.warns(UserWarning), zipfile.ZipFile(dup, "w") as z:
        z.writestr("a.txt", "1")
        z.writestr("a.txt", "2")
    with c:
        assert send(c, out.getvalue()).json()["code"] == "invalid"
        assert send(c, dup.getvalue()).json()["code"] == "invalid"


def test_bomb_and_oversize_json_refused(ctx, capsys):
    c = _ready_client(ctx, capsys)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bomb.json", b"0" * (5 * 1024 * 1024))
    root = _make_package(ctx.tmp / "big", cards=CARDS)
    (root / "lessons" / "demo" / "lesson.json").write_text(" " * (2 * 1024 * 1024), encoding="utf-8")
    with c:
        assert send(c, out.getvalue()).json()["code"] == "invalid"
        assert send(c, zip_of(root)).json()["code"] == "invalid"


@pytest.mark.parametrize("change", ["topic", "label", "mp3", "lessons", "option"])
def test_bad_contract_values_never_reach_commit(ctx, capsys, change):
    c = _ready_client(ctx, capsys)
    tracks = {"short": {"file": "s.mp3", "label": "Ngắn"}}
    root = _make_package(ctx.tmp / "b", cards=CARDS, tracks=tracks, quiz=[{"id": "q1", "q": "q", "options": ["a", "b"], "answer": 0}])
    pkg_file, lesson_file = root / "package.json", root / "lessons" / "demo" / "lesson.json"
    pkg, lesson = json.loads(pkg_file.read_text("utf-8")), json.loads(lesson_file.read_text("utf-8"))
    if change == "topic":
        pkg["topic"] = 5
    elif change == "label":
        del lesson["tracks"]["short"]["label"]
    elif change == "mp3":
        (root / "lessons" / "demo" / "audio" / "s.mp3").write_bytes(b"not audio")
    elif change == "lessons":
        pkg["lessons"] = []
    else:
        lesson["quiz"][0]["options"] = [1, 2]
    pkg_file.write_text(json.dumps(pkg), "utf-8")
    lesson_file.write_text(json.dumps(lesson), "utf-8")
    with c:
        r = send(c, zip_of(root))
        assert r.status_code == 400 and r.json()["code"] == "invalid"


def test_shared_learner_list_survives_any_accepted_package(ctx, capsys):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    tracks = {"short": {"file": "s.mp3", "label": "Ngắn"}}
    with a, b:
        pid = upload_and_commit(a, package_zip(ctx, cards=CARDS, tracks=tracks))["package_id"]
        with ctx.db.connect() as x:
            x.execute("INSERT INTO package_access VALUES(?,?,'email',?,NULL)", (pid, "binh", time.time()))
        r = b.get("/api/lessons")
        assert r.status_code == 200 and r.json()["lessons"][0]["tracks"]["short"]["url"].startswith("/audio/")


def test_commit_needs_attest(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        upload_id = send(c, package_zip(ctx, cards=CARDS)).json()["upload_id"]
        url = f"/api/uploads/{upload_id}/commit"
        assert c.post(url, json={}).status_code == 400
        assert c.post(url, json={"attest": "yes"}).status_code == 400
        assert commit(c, upload_id).status_code == 200  # the refusal kept the stage


def test_commit_only_by_uploader(ctx, capsys):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    with a, b:
        upload_id = send(a, package_zip(ctx, cards=CARDS)).json()["upload_id"]
        assert commit(b, upload_id).status_code == 404
        b.delete(f"/api/uploads/{upload_id}")
        assert commit(a, upload_id).status_code == 200


def test_double_commit_installs_once(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        upload_id = send(c, package_zip(ctx, cards=CARDS)).json()["upload_id"]
        assert commit(c, upload_id).json()["version"] == 1
        assert commit(c, upload_id).status_code == 404


def test_removed_ids_need_confirm(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        upload_and_commit(c, package_zip(ctx, cards=CARDS))
        r = send(c, package_zip(ctx, "p2", cards=CARDS[:4] + [{"id": "c9", "q": "q", "a": "a"}]))
        assert r.json()["removed"] == ["c4"] and r.json()["is_update"] is True
        upload_id = r.json()["upload_id"]
        refused = commit(c, upload_id)
        assert refused.status_code == 409 and refused.json()["removed"] == ["c4"]
        assert commit(c, upload_id, confirm_removed=["c4"]).json()["version"] == 2


def test_kept_ids_keep_progress_removed_stop_due_new_appear(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        upload_and_commit(c, package_zip(ctx, cards=CARDS))
        key = _first_key(ctx.catalog, "an")
        c.post(f"/api/lessons/{key}/start")
        cards = c.get("/api/cards/due").json()["cards"]
        kept = next(x for x in cards if x["target_id"] == "c0")
        due_after = c.post(f"/api/cards/{kept['id']}/review", json={"rating": 3}).json()["due"]
        new = CARDS[:4] + [{"id": "c9", "q": "mới", "a": "a"}]
        upload_and_commit(c, package_zip(ctx, "p2", cards=new), confirm_removed=["c4"])
        ids = {x["target_id"] for x in c.get("/api/cards/due").json()["cards"]}
        assert ids == {"c1", "c2", "c3", "c9"}
        with ctx.db.connect() as x:
            assert x.execute("SELECT due FROM card_state WHERE card_id=?", (kept["id"],)).fetchone()["due"] == due_after


def test_quota_counts_unpacked_size(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        body = package_zip(ctx, cards=CARDS)
        size = send(c, body).json()["size"]
        upload_and_commit(c, body)
        with ctx.db.connect() as x:
            x.execute("UPDATE users SET quota_bytes=? WHERE name='an'", (size + 50,))
        other = send(c, package_zip(ctx, "p2", slug="other", cards=CARDS))
        assert other.status_code == 413 and other.json()["code"] == "quota"
        # An update counts only the difference: the old version is replaced.
        assert send(c, package_zip(ctx, "p3", cards=CARDS)).status_code == 200
        assert len(c.get("/api/lessons").json()["lessons"]) == 1


def test_svg_with_script_cannot_run(ctx, capsys):
    c = _ready_client(ctx, capsys)
    root = _make_package(ctx.tmp / "s", cards=CARDS)
    (root / "lessons" / "demo" / "page" / "x.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "utf-8")
    with c:
        upload_and_commit(c, zip_of(root))
        key = _first_key(ctx.catalog, "an")
        base = c.post(f"/api/lessons/{key}/frame", json={}).json()["url"].rsplit("/", 1)[0]
        r = c.get(base + "/x.svg")
        assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"
        assert r.headers["x-content-type-options"] == "nosniff"


def test_html_outside_iframe_refused(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        upload_and_commit(c, package_zip(ctx, cards=CARDS))
        key = _first_key(ctx.catalog, "an")
        url = c.post(f"/api/lessons/{key}/frame", json={}).json()["url"]
        assert c.get(url).status_code == 403
        assert c.get(url, headers={"Sec-Fetch-Dest": "iframe"}).status_code == 200


def test_upload_slots_limited(ctx, capsys):
    c = _ready_client(ctx, capsys)
    u = ctx.main.uploads
    with c:
        u.active["an"] = 1
        assert send(c, b"x").status_code == 429
        u.active.clear()
        u.active.update({f"u{i}": 1 for i in range(u.MAX_ACTIVE_TOTAL)})
        assert send(c, b"x").status_code == 429
        u.active.clear()


def test_new_upload_replaces_users_previous_staged(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        first = send(c, package_zip(ctx, cards=CARDS)).json()["upload_id"]
        second = send(c, package_zip(ctx, "p2", cards=CARDS)).json()["upload_id"]
        assert len(staging(ctx)) == 1
        assert commit(c, first).status_code == 404
        assert commit(c, second).status_code == 200


def test_expired_stage_cleaned(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        upload_id = send(c, package_zip(ctx, cards=CARDS)).json()["upload_id"]
        ctx.main.uploads.stages[upload_id]["created"] -= ctx.main.uploads.STAGE_TTL + 1
        assert commit(c, upload_id).status_code == 404
        assert staging(ctx) == []


def test_low_disk_refused(ctx, capsys, monkeypatch):
    c = _ready_client(ctx, capsys)
    monkeypatch.setattr(ctx.main.uploads, "MIN_FREE_BYTES", 10 ** 18)
    with c:
        assert send(c, b"x").status_code == 507


def test_startup_clears_staging(ctx, capsys):
    leftover = pathlib.Path(os.environ["PACKAGES_DIR"]) / ".staging" / "old"
    leftover.mkdir(parents=True)
    c = _ready_client(ctx, capsys)
    with c:
        assert not leftover.exists()


def test_failed_install_loses_nothing_running(ctx, capsys, monkeypatch):
    c = _ready_client(ctx, capsys)
    with c:
        upload_and_commit(c, package_zip(ctx, cards=CARDS))
        before = c.get("/api/lessons").json()
        upload_id = send(c, package_zip(ctx, "p2", cards=CARDS, title="Mới")).json()["upload_id"]
        original = ctx.catalog._add_new_cards

        def boom(*a, **k):
            raise RuntimeError("x")

        monkeypatch.setattr(ctx.catalog, "_add_new_cards", boom)
        with pytest.raises(RuntimeError):
            commit(c, upload_id)
        monkeypatch.setattr(ctx.catalog, "_add_new_cards", original)
        assert c.get("/api/lessons").json() == before
        assert commit(c, upload_id).status_code == 200  # the stage survives, so the author can retry


def test_cli_import_zip(ctx, capsys, tmp_path):
    ctx.cli.main(["add-user", "an"])
    capsys.readouterr()
    z = tmp_path / "x.zip"
    z.write_bytes(package_zip(ctx, cards=CARDS))
    assert ctx.cli.main(["import-package", str(z), "an"]) == 0
    assert capsys.readouterr().out.strip().startswith("p")
    assert z.exists()
    (tmp_path / "bad.zip").write_bytes(b"x")
    assert ctx.cli.main(["import-package", str(tmp_path / "bad.zip"), "an"]) == 1
