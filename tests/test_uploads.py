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


def test_package_count_cap(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        first = upload_and_commit(c, zip_of(_make_package(ctx.tmp / "p0", slug="first")))
        staged = send(c, zip_of(_make_package(ctx.tmp / "p1", slug="staged")))
        assert staged.status_code == 200
        with ctx.db.connect() as conn:
            for n in range(ctx.main.uploads.MAX_PACKAGES - 1):
                conn.execute(
                    "INSERT INTO packages(id, owner, slug, title, topic, description, version, size_bytes, ask_hash, created_at, updated_at) VALUES(?,?,?,?,'','',1,0,'',0,0)",
                    (f"p{n:012x}", "an", f"s{n}", "x"),
                )
        assert commit(c, staged.json()["upload_id"]).status_code == 413
        c.delete(f"/api/uploads/{staged.json()['upload_id']}")
        assert send(c, zip_of(_make_package(ctx.tmp / "p2", slug="other"))).status_code == 413
        update = send(c, zip_of(_make_package(ctx.tmp / "p3", slug="first", title="Mới")))
        assert update.status_code == 200, update.text
        assert commit(c, update.json()["upload_id"]).status_code == 200
        assert first["package_id"]


def multipart_package(ctx, name="mp"):
    root = _make_package(ctx.tmp / name, cards=CARDS)
    # ~4.5 MB dummy data produces 3 parts when PART_SIZE is 2 MB
    # an mp3 outside the lesson tracks is neither size-capped nor parsed, so random bytes pass validation
    (root / "lessons" / "demo" / "page" / "filler.mp3").write_bytes(os.urandom(4_500_000))
    return zip_of(root)


def start_parts(c, size):
    return c.post("/api/uploads/parts", json={"size": size})


def put_part(c, session, index, chunk, headers=None):
    hdrs = {"Content-Type": "application/octet-stream"}
    if headers:
        hdrs.update(headers)
    return c.put(f"/api/uploads/parts/{session}/{index}", content=chunk, headers=hdrs)


def finish_parts(c, session):
    return c.post(f"/api/uploads/parts/{session}/finish")


def test_parts_in_order_and_out_of_order_installs(ctx, capsys):
    c = _ready_client(ctx, capsys)
    part_size = ctx.main.uploads.PART_SIZE
    with c:
        # 1. In order
        body = multipart_package(ctx, "p_in_order")
        parts = [body[i:i + part_size] for i in range(0, len(body), part_size)]
        assert len(parts) == 3

        r = start_parts(c, len(body))
        assert r.status_code == 200
        s = r.json()["session"]
        assert r.json()["parts"] == 3
        assert r.json()["part_size"] == part_size

        for i, chunk in enumerate(parts):
            res = put_part(c, s, i, chunk)
            assert res.status_code == 200 and res.json() == {"ok": True}

        fin = finish_parts(c, s)
        assert fin.status_code == 200
        info = fin.json()
        assert info["title"] == "Demo"
        res_commit = commit(c, info["upload_id"])
        assert res_commit.status_code == 200 and res_commit.json()["version"] == 1
        assert len(c.get("/api/lessons").json()["lessons"]) == 1

        # 2. Out of order (update version)
        body2 = multipart_package(ctx, "p_out_order")
        parts2 = [body2[i:i + part_size] for i in range(0, len(body2), part_size)]
        r2 = start_parts(c, len(body2))
        s2 = r2.json()["session"]

        # Send in order: 2, 0, 1
        for i in (2, 0, 1):
            res = put_part(c, s2, i, parts2[i])
            assert res.status_code == 200 and res.json() == {"ok": True}

        fin2 = finish_parts(c, s2)
        assert fin2.status_code == 200
        assert fin2.json()["is_update"] is True
        res_commit2 = commit(c, fin2.json()["upload_id"])
        assert res_commit2.status_code == 200 and res_commit2.json()["version"] == 2


def test_part_sent_twice(ctx, capsys):
    c = _ready_client(ctx, capsys)
    part_size = ctx.main.uploads.PART_SIZE
    with c:
        body = multipart_package(ctx, "p_dup")
        parts = [body[i:i + part_size] for i in range(0, len(body), part_size)]
        r = start_parts(c, len(body))
        s = r.json()["session"]

        # Part 0 sent twice
        assert put_part(c, s, 0, parts[0]).status_code == 200
        assert put_part(c, s, 0, parts[0]).status_code == 200

        # Remaining parts
        assert put_part(c, s, 1, parts[1]).status_code == 200
        assert put_part(c, s, 2, parts[2]).status_code == 200

        fin = finish_parts(c, s)
        assert fin.status_code == 200


def test_wrong_size_part_and_index_out_of_range(ctx, capsys):
    c = _ready_client(ctx, capsys)
    part_size = ctx.main.uploads.PART_SIZE
    with c:
        body = multipart_package(ctx, "p_err")
        parts = [body[i:i + part_size] for i in range(0, len(body), part_size)]
        r = start_parts(c, len(body))
        s = r.json()["session"]

        # Wrong size part: too short or too long
        assert put_part(c, s, 0, parts[0][:100]).status_code == 400
        assert put_part(c, s, 0, parts[0] + b"x").status_code == 400
        assert put_part(c, s, 2, parts[2][:10]).status_code == 400
        assert put_part(c, s, 2, parts[2] + b"x").status_code == 400

        # Index out of range
        assert put_part(c, s, -1, parts[0]).status_code == 400
        assert put_part(c, s, 3, parts[0]).status_code == 400
        assert put_part(c, s, 999, parts[0]).status_code == 400


def test_finish_missing_part_409(ctx, capsys):
    c = _ready_client(ctx, capsys)
    part_size = ctx.main.uploads.PART_SIZE
    with c:
        body = multipart_package(ctx, "p_miss")
        parts = [body[i:i + part_size] for i in range(0, len(body), part_size)]
        r = start_parts(c, len(body))
        s = r.json()["session"]

        # Send part 0 and 2, miss part 1
        put_part(c, s, 0, parts[0])
        put_part(c, s, 2, parts[2])

        fin = finish_parts(c, s)
        assert fin.status_code == 409
        d = fin.json()
        assert d["code"] == "missing"
        assert d["missing"] == [1]

        # Then sending part 1 allows finish to succeed
        put_part(c, s, 1, parts[1])
        assert finish_parts(c, s).status_code == 200


def test_another_user_session_404(ctx, capsys):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    part_size = ctx.main.uploads.PART_SIZE
    with a, b:
        body = multipart_package(ctx, "p_other")
        parts = [body[i:i + part_size] for i in range(0, len(body), part_size)]
        r = start_parts(a, len(body))
        s = r.json()["session"]

        # B tries to PUT, finish, and DELETE A's session
        assert put_part(b, s, 0, parts[0]).status_code == 404
        assert finish_parts(b, s).status_code == 404
        assert b.delete(f"/api/uploads/parts/{s}").status_code == 404

        # A's session is unaffected: A can complete it
        for i, chunk in enumerate(parts):
            assert put_part(a, s, i, chunk).status_code == 200
        assert finish_parts(a, s).status_code == 200


def test_new_start_replaces_old_session(ctx, capsys):
    c = _ready_client(ctx, capsys)
    part_size = ctx.main.uploads.PART_SIZE
    with c:
        body = multipart_package(ctx, "p_replace")
        parts = [body[i:i + part_size] for i in range(0, len(body), part_size)]
        r1 = start_parts(c, len(body))
        s1 = r1.json()["session"]

        # User starts a new session
        r2 = start_parts(c, len(body))
        s2 = r2.json()["session"]
        assert s1 != s2

        # s1 is now replaced / gone
        assert put_part(c, s1, 0, parts[0]).status_code == 404
        # s2 is valid
        assert put_part(c, s2, 0, parts[0]).status_code == 200


def test_parts_size_over_max_zip_413(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        max_zip = ctx.main.bundle.MAX_ZIP
        assert start_parts(c, max_zip + 1).status_code == 413
        assert start_parts(c, 0).status_code == 413
        assert start_parts(c, -1).status_code == 413
        assert start_parts(c, "not_int").status_code == 413


def test_body_larger_than_part_size_refused_with_false_content_length(ctx, capsys):
    c = _ready_client(ctx, capsys)
    part_size = ctx.main.uploads.PART_SIZE
    with c:
        body = multipart_package(ctx, "p_false_len")
        parts = [body[i:i + part_size] for i in range(0, len(body), part_size)]
        r = start_parts(c, len(body))
        s = r.json()["session"]

        # Send body larger than part_size with Content-Length claiming part_size
        oversized = parts[0] + b"extra_byte"
        hdrs = {"Content-Length": str(part_size)}
        res = put_part(c, s, 0, oversized, headers=hdrs)
        assert res.status_code == 400


def test_parts_file_gone_after_finish(ctx, capsys):
    c = _ready_client(ctx, capsys)
    part_size = ctx.main.uploads.PART_SIZE
    with c:
        body = multipart_package(ctx, "p_gone")
        parts = [body[i:i + part_size] for i in range(0, len(body), part_size)]
        r = start_parts(c, len(body))
        s = r.json()["session"]

        for i, chunk in enumerate(parts):
            put_part(c, s, i, chunk)

        st_before = staging(ctx)
        # Verify a .zip staging file exists while upload was in progress
        assert any(p.endswith(".zip") for p in st_before)

        fin = finish_parts(c, s)
        assert fin.status_code == 200

        # After finish, the raw zip parts file is gone from staging
        st_after = staging(ctx)
        assert not any(p.endswith(".zip") for p in st_after)


def test_invalid_finish_ends_the_session_and_removes_the_file(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        body = os.urandom(3_000_000)  # not a zip
        s = start_parts(c, len(body)).json()["session"]
        part_size = ctx.main.uploads.PART_SIZE
        for i in range(0, 2):
            assert put_part(c, s, i, body[i * part_size:(i + 1) * part_size]).status_code == 200
        assert finish_parts(c, s).status_code == 400
        assert finish_parts(c, s).status_code == 404
        assert not any(p.endswith(".zip") for p in staging(ctx))


def eocd(body: bytes):
    size = len(body)
    tail_size = min(size, 65536 + 22)
    tail = body[size - tail_size:]
    for i in range(tail_size - 22, -1, -1):
        if tail[i:i + 4] == b"PK\x05\x06":
            cd_size = int.from_bytes(tail[i + 12:i + 16], "little")
            cd_offset = int.from_bytes(tail[i + 16:i + 20], "little")
            if cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF or cd_offset + cd_size > size or cd_size <= 0 or cd_offset < 0:
                return None
            return cd_offset, cd_size
    return None


def test_delta_upload_rebuilds_and_installs(ctx, capsys):
    c = _ready_client(ctx, capsys)
    part_size = ctx.main.uploads.PART_SIZE
    with c:
        root = _make_package(ctx.tmp / "pkg_delta", cards=CARDS)
        filler1 = os.urandom(4_500_000)
        (root / "lessons" / "demo" / "page" / "filler1.mp3").write_bytes(filler1)
        body1 = zip_of(root)
        parts1 = [body1[i:i + part_size] for i in range(0, len(body1), part_size)]
        assert len(parts1) == 3

        r1 = start_parts(c, len(body1))
        assert r1.status_code == 200
        s1 = r1.json()["session"]
        for i, chunk in enumerate(parts1):
            assert put_part(c, s1, i, chunk).status_code == 200
        fin1 = finish_parts(c, s1)
        assert fin1.status_code == 200
        commit_res = commit(c, fin1.json()["upload_id"])
        assert commit_res.status_code == 200
        pkg_id = commit_res.json()["package_id"]
        assert commit_res.json()["version"] == 1

        # Build v2 = same files plus one new filler mp3, re-zipped
        filler2 = os.urandom(2_500_000)
        (root / "lessons" / "demo" / "page" / "filler2.mp3").write_bytes(filler2)
        body2 = zip_of(root)
        parts2 = [body2[i:i + part_size] for i in range(0, len(body2), part_size)]
        assert len(parts2) >= 4

        cd_offset, cd_size = eocd(body2)
        assert cd_offset is not None and cd_size is not None
        r2 = c.post("/api/uploads/parts", json={"size": len(body2), "cd_offset": cd_offset, "cd_size": cd_size})
        assert r2.status_code == 200
        s2 = r2.json()["session"]

        # Send the CD parts
        cd_start = cd_offset // part_size
        cd_parts = list(range(cd_start, len(parts2)))
        for i in cd_parts:
            assert put_part(c, s2, i, parts2[i]).status_code == 200

        # Call plan: reused > 0, needed is a strict subset of all parts and excludes unchanged filler parts
        r_plan = c.post(f"/api/uploads/parts/{s2}/plan")
        assert r_plan.status_code == 200
        plan_data = r_plan.json()
        assert plan_data["reused"] > 0
        needed = set(plan_data["needed"])
        all_parts = set(range(len(parts2)))
        assert needed < all_parts

        with zipfile.ZipFile(io.BytesIO(body2)) as zf:
            info1 = zf.getinfo("lessons/demo/page/filler1.mp3")
            f1_start = info1.header_offset
            sorted_infos = sorted(zf.infolist(), key=lambda x: x.header_offset)
            idx1 = next(idx for idx, x in enumerate(sorted_infos) if x.filename == info1.filename)
            f1_end = sorted_infos[idx1 + 1].header_offset if idx1 + 1 < len(sorted_infos) else cd_offset
            f1_middle_part = (f1_start + f1_end) // (2 * part_size)
            if f1_start <= f1_middle_part * part_size and (f1_middle_part + 1) * part_size <= f1_end:
                assert f1_middle_part not in needed

        # Send only needed parts that have not been sent yet
        for i in needed:
            if i not in cd_parts:
                assert put_part(c, s2, i, parts2[i]).status_code == 200

        fin2 = finish_parts(c, s2)
        assert fin2.status_code == 200
        res_c2 = commit(c, fin2.json()["upload_id"])
        assert res_c2.status_code == 200 and res_c2.json()["version"] == 2

        # Installed files are byte-identical to the v2 zip's content
        inst_dir = ctx.main.catalog._package_dir(pkg_id, 2)
        reused_file = (inst_dir / "lessons" / "demo" / "page" / "filler1.mp3").read_bytes()
        new_file = (inst_dir / "lessons" / "demo" / "page" / "filler2.mp3").read_bytes()
        with zipfile.ZipFile(io.BytesIO(body2)) as zf:
            assert reused_file == zf.read("lessons/demo/page/filler1.mp3")
            assert new_file == zf.read("lessons/demo/page/filler2.mp3")


def test_plan_before_cd_parts_arrive_409(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        body = multipart_package(ctx, "pkg_cd_miss")
        cd_offset, cd_size = eocd(body)
        r = c.post("/api/uploads/parts", json={"size": len(body), "cd_offset": cd_offset, "cd_size": cd_size})
        assert r.status_code == 200
        s = r.json()["session"]

        r_plan = c.post(f"/api/uploads/parts/{s}/plan")
        assert r_plan.status_code == 409
        d = r_plan.json()
        assert d["code"] == "missing"
        expected_cd = list(range(cd_offset // ctx.main.uploads.PART_SIZE, r.json()["parts"]))
        assert d["missing"] == expected_cd


def test_plan_on_other_user_session_and_no_cross_user_reuse(ctx, capsys):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    part_size = ctx.main.uploads.PART_SIZE
    with a, b:
        root = _make_package(ctx.tmp / "pkg_user_a", cards=CARDS)
        (root / "lessons" / "demo" / "page" / "filler.mp3").write_bytes(os.urandom(3_000_000))
        body = zip_of(root)
        cd_offset, cd_size = eocd(body)

        r_a = a.post("/api/uploads/parts", json={"size": len(body), "cd_offset": cd_offset, "cd_size": cd_size})
        s_a = r_a.json()["session"]

        assert b.post(f"/api/uploads/parts/{s_a}/plan").status_code == 404

        parts = [body[i:i + part_size] for i in range(0, len(body), part_size)]
        for i, chunk in enumerate(parts):
            assert put_part(a, s_a, i, chunk).status_code == 200
        fin_a = finish_parts(a, s_a)
        assert fin_a.status_code == 200
        assert commit(a, fin_a.json()["upload_id"]).status_code == 200

        r_b = b.post("/api/uploads/parts", json={"size": len(body), "cd_offset": cd_offset, "cd_size": cd_size})
        s_b = r_b.json()["session"]
        cd_parts = list(range(cd_offset // part_size, len(parts)))
        for i in cd_parts:
            assert put_part(b, s_b, i, parts[i]).status_code == 200

        plan_b = b.post(f"/api/uploads/parts/{s_b}/plan").json()
        assert plan_b["reused"] == 0
        assert plan_b["needed"] == list(range(len(parts)))


def test_file_changed_on_disk_between_plan_and_finish_400(ctx, capsys):
    c = _ready_client(ctx, capsys)
    part_size = ctx.main.uploads.PART_SIZE
    with c:
        root = _make_package(ctx.tmp / "pkg_tamper", cards=CARDS)
        filler1 = os.urandom(3_000_000)
        (root / "lessons" / "demo" / "page" / "filler1.mp3").write_bytes(filler1)
        body1 = zip_of(root)
        parts1 = [body1[i:i + part_size] for i in range(0, len(body1), part_size)]

        r1 = start_parts(c, len(body1))
        s1 = r1.json()["session"]
        for i, chunk in enumerate(parts1):
            put_part(c, s1, i, chunk)
        fin1 = finish_parts(c, s1)
        commit_res = commit(c, fin1.json()["upload_id"]).json()
        pkg_id = commit_res["package_id"]

        (root / "lessons" / "demo" / "page" / "filler2.mp3").write_bytes(os.urandom(1_000_000))
        body2 = zip_of(root)
        parts2 = [body2[i:i + part_size] for i in range(0, len(body2), part_size)]
        cd_offset, cd_size = eocd(body2)

        r2 = c.post("/api/uploads/parts", json={"size": len(body2), "cd_offset": cd_offset, "cd_size": cd_size})
        s2 = r2.json()["session"]
        cd_parts = list(range(cd_offset // part_size, len(parts2)))
        for i in cd_parts:
            put_part(c, s2, i, parts2[i])

        plan_res = c.post(f"/api/uploads/parts/{s2}/plan")
        assert plan_res.status_code == 200
        assert plan_res.json()["reused"] > 0
        needed = set(plan_res.json()["needed"])
        for i in needed:
            if i not in cd_parts:
                put_part(c, s2, i, parts2[i])

        # Modify existing file on disk in v1
        installed_f1 = ctx.main.catalog._package_dir(pkg_id, 1) / "lessons" / "demo" / "page" / "filler1.mp3"
        installed_f1.write_bytes(os.urandom(3_000_000))

        fin2 = finish_parts(c, s2)
        assert fin2.status_code == 400
        d = fin2.json()
        assert d["code"] == "invalid"
        assert d["problems"][0]["path"] == "upload.zip"
        assert "File cũ đã đổi trong lúc tải. Tải lại file." in d["problems"][0]["message"]


def test_zip_without_cd_offset_works_with_all_parts(ctx, capsys):
    c = _ready_client(ctx, capsys)
    part_size = ctx.main.uploads.PART_SIZE
    with c:
        body = multipart_package(ctx, "pkg_no_cd")
        parts = [body[i:i + part_size] for i in range(0, len(body), part_size)]
        r = start_parts(c, len(body))
        s = r.json()["session"]

        assert c.post(f"/api/uploads/parts/{s}/plan").status_code == 400

        for i, chunk in enumerate(parts):
            assert put_part(c, s, i, chunk).status_code == 200
        fin = finish_parts(c, s)
        assert fin.status_code == 200


def test_start_bad_cd_values_400(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        assert c.post("/api/uploads/parts", json={"size": 1000, "cd_offset": 600, "cd_size": 500}).status_code == 400
        assert c.post("/api/uploads/parts", json={"size": 1000, "cd_offset": -1, "cd_size": 100}).status_code == 400
        assert c.post("/api/uploads/parts", json={"size": 1000, "cd_offset": 0, "cd_size": 0}).status_code == 400
        assert c.post("/api/uploads/parts", json={"size": 1000, "cd_offset": 100}).status_code == 400
        assert c.post("/api/uploads/parts", json={"size": 1000, "cd_size": 100}).status_code == 400


def test_start_size_300mb(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        limit = 300 * 1024 * 1024
        assert start_parts(c, limit).status_code == 200
        assert start_parts(c, limit + 1).status_code == 413


def test_parts_expiry_uses_touched(ctx, capsys):
    c = _ready_client(ctx, capsys)
    with c:
        r1 = start_parts(c, 1000)
        s1 = r1.json()["session"]
        now = time.time()
        ctx.main.uploads.part_sessions[s1]["touched"] = now - ctx.main.uploads.STAGE_TTL - 10
        ctx.main.uploads.expire(now=now)
        assert s1 not in ctx.main.uploads.part_sessions

        r2 = start_parts(c, 1000)
        s2 = r2.json()["session"]
        ctx.main.uploads.part_sessions[s2]["created"] = now - ctx.main.uploads.STAGE_TTL - 100
        ctx.main.uploads.part_sessions[s2]["touched"] = now
        ctx.main.uploads.expire(now=now)
        assert s2 in ctx.main.uploads.part_sessions


def test_rebuild_rejects_duplicate_names_and_counts_reused_bytes(ctx, tmp_path, monkeypatch):
    import warnings
    old = tmp_path / "old.mp3"
    old.write_bytes(os.urandom(300_000))
    crc_old = ctx.main._file_crc32(old)

    def session_zip(names):
        p = tmp_path / f"s{len(names)}.zip"
        with warnings.catch_warnings(), zipfile.ZipFile(p, "w") as z:
            warnings.simplefilter("ignore")  # duplicate names on purpose
            for n in names:
                z.writestr(n, old.read_bytes())
        return p

    dup = session_zip(["a.mp3", "a.mp3"])
    with pytest.raises(ctx.main.RebuildError):
        ctx.main._rebuild_zip(dup, tmp_path / "out1.zip", {"a.mp3": str(old)})

    many = session_zip([f"{i}.mp3" for i in range(4)])
    assert zipfile.ZipFile(many).infolist()[0].CRC == crc_old
    monkeypatch.setattr(ctx.main.bundle, "MAX_UNPACKED", 1_000_000)  # 4 reused copies of 300 KB exceed it
    with pytest.raises(ctx.main.RebuildError):
        ctx.main._rebuild_zip(many, tmp_path / "out2.zip", {f"{i}.mp3": str(old) for i in range(4)})


def test_parts_are_frozen_after_plan(ctx, capsys):
    c = _ready_client(ctx, capsys)
    part_size = ctx.main.uploads.PART_SIZE
    with c:
        root = _make_package(ctx.tmp / "pkg_freeze", cards=CARDS)
        (root / "lessons" / "demo" / "page" / "filler1.mp3").write_bytes(os.urandom(4_500_000))
        body1 = zip_of(root)
        s1 = start_parts(c, len(body1)).json()["session"]
        for i in range(0, len(body1), part_size):
            assert put_part(c, s1, i // part_size, body1[i:i + part_size]).status_code == 200
        assert commit(c, finish_parts(c, s1).json()["upload_id"]).status_code == 200

        (root / "lessons" / "demo" / "page" / "filler2.mp3").write_bytes(os.urandom(1_000_000))
        body2 = zip_of(root)
        parts2 = [body2[i:i + part_size] for i in range(0, len(body2), part_size)]
        cd_offset, cd_size = eocd(body2)
        s2 = c.post("/api/uploads/parts", json={"size": len(body2), "cd_offset": cd_offset, "cd_size": cd_size}).json()["session"]
        cd_parts = list(range(cd_offset // part_size, len(parts2)))
        for i in cd_parts:
            assert put_part(c, s2, i, parts2[i]).status_code == 200
        needed = set(c.post(f"/api/uploads/parts/{s2}/plan").json()["needed"])
        skipped = sorted(set(range(len(parts2))) - needed)
        assert skipped
        # a part the plan does not need is refused
        assert put_part(c, s2, skipped[0], parts2[skipped[0]]).status_code == 400
        # rewriting a received CD part after plan is a no-op, so the planned layout stands
        last = cd_parts[-1]
        assert put_part(c, s2, last, b"\0" * len(parts2[last])).status_code == 200
        for i in sorted(needed - set(cd_parts)):
            assert put_part(c, s2, i, parts2[i]).status_code == 200
        fin = finish_parts(c, s2)
        assert fin.status_code == 200, fin.text
        assert commit(c, fin.json()["upload_id"]).json()["version"] == 2
        assert not any(p.endswith(".zip") for p in staging(ctx))
