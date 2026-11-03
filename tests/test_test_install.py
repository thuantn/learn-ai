"""Tests for installing practice tests and uploading single .json files."""
import secrets
import json

import app.catalog as catalog
from practice_fixtures import SENTINELS, make_item, make_test, one_file, write_package
from test_catalog import _make_package, _ready_client, ctx  # noqa: F401
from test_uploads import commit, send, upload_and_commit, zip_of

JSON_HEADERS = {"Content-Type": "application/json"}
NEW_TABLES = ("test_revision", "package_tests", "test_attempt", "test_answer", "test_first_answer", "test_pool")


def test_install_stores_tests_without_answers_in_summary(ctx, capsys, tmp_path):
    ctx.cli.main(["add-user", "an"])
    ctx.cli.main(["add-user", "binh"])
    items = [make_item("q1", domain="  Mạng  "), make_item("q2", domain=""), make_item("q3", shuffle=False)]
    root = write_package(tmp_path / "p", {"t1": make_test(items=items, title="Đề 1")})
    res = ctx.catalog.install_version("an", root)
    pid = res["id"]
    key = f"{pid}.t1"
    with ctx.db.connect() as c:
        pt = c.execute("SELECT * FROM package_tests WHERE key=?", (key,)).fetchone()
        assert pt["title"] == "Đề 1" and pt["item_count"] == 3
        assert pt["pass_percent"] == 70 and pt["time_limit_minutes"] == 0
        assert "correct" not in pt.keys()
        assert all("correct" not in str(v) and SENTINELS[0] not in str(v) for v in pt)

        row = ctx.catalog.test_row(c, "an", key)
        assert row is not None
        assert row["package_id"] == pid and row["owner"] == "an"
        assert row["ask_status"] == "none" and row["revision_id"] == pt["revision_id"]
        assert ctx.catalog.test_row(c, "binh", key) is None

        data = ctx.catalog.revision_data(c, row["revision_id"])
        assert data["title"] == "Đề 1" and data["lang"] == "vi"
        assert data["pass_percent"] == 70 and data["time_limit_minutes"] == 0
        assert [x["domain"] for x in data["items"]] == ["Mạng", "Khác", "Chung"]
        assert [x["shuffle"] for x in data["items"]] == [True, True, False]
        assert data["items"][0]["correct"] == ["A"]
        assert SENTINELS[0] in data["items"][0]["explanation"]


def test_same_content_keeps_the_revision_and_changed_content_adds_one(ctx, capsys, tmp_path):
    ctx.cli.main(["add-user", "an"])
    pid = ctx.catalog.install_version("an", write_package(tmp_path / "v1", {"t1": make_test(title="Đề A")}))["id"]
    key = f"{pid}.t1"
    ctx.catalog.install_version("an", write_package(tmp_path / "v2", {"t1": make_test(title="Đề A")}))
    with ctx.db.connect() as c:
        revs = c.execute("SELECT id FROM test_revision WHERE test_key=?", (key,)).fetchall()
        assert len(revs) == 1
        rev1 = revs[0]["id"]

    # Đổi chữ khi chưa có lượt làm nào dùng bản cũ: bản cũ được dọn, chỉ còn 1 dòng.
    ctx.catalog.install_version("an", write_package(tmp_path / "v3", {"t1": make_test(title="Đề B")}))
    with ctx.db.connect() as c:
        revs = c.execute("SELECT id FROM test_revision WHERE test_key=?", (key,)).fetchall()
        assert len(revs) == 1 and revs[0]["id"] != rev1
        rev2 = revs[0]["id"]
        c.execute(
            "INSERT INTO test_attempt(id, user, test_key, revision_id, mode, layout, started_at) VALUES('a1','an',?,?,'exam','[]',0)",
            (key, rev2),
        )

    # Đổi chữ khi có lượt dùng bản cũ: giữ bản cũ và thêm bản mới (2 dòng).
    ctx.catalog.install_version("an", write_package(tmp_path / "v4", {"t1": make_test(title="Đề C")}))
    with ctx.db.connect() as c:
        revs = c.execute("SELECT id FROM test_revision WHERE test_key=? ORDER BY id", (key,)).fetchall()
        assert len(revs) == 2 and revs[0]["id"] == rev2


def test_a_two_megabyte_test_uploads_and_commits(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    items = [
        make_item(
            f"q{i}",
            question=secrets.token_hex(1950),
            explanation=secrets.token_hex(1950),
            best_practice=secrets.token_hex(500),
            docs=["https://a.vn/" + secrets.token_hex(150) for _ in range(5)],
        )
        for i in range(200)
    ]
    root1 = write_package(tmp_path / "v1", {"t1": make_test(items=items, title="Đề lớn 1")})
    assert (root1 / "tests/t1.json").stat().st_size > 2 * 1024 * 1024
    root2 = write_package(tmp_path / "v2", {"t1": make_test(items=items, title="Đề lớn 2")})
    with c:
        r1 = upload_and_commit(c, zip_of(root1))
        assert r1["version"] == 1
        r2 = upload_and_commit(c, zip_of(root2))
        assert r2["version"] == 2 and r2["package_id"] == r1["package_id"]


def test_zip_without_a_lessons_key_uploads(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    for name, title in (("v1", "Đề 1"), ("v2", "Đề 2")):
        root = write_package(tmp_path / name, {"t1": make_test(title=title)})
        pkg_path = root / "package.json"
        pkg = json.loads(pkg_path.read_text("utf-8"))
        del pkg["lessons"]
        pkg_path.write_text(json.dumps(pkg), encoding="utf-8")
    with c:
        assert upload_and_commit(c, zip_of(tmp_path / "v1"))["version"] == 1
        assert upload_and_commit(c, zip_of(tmp_path / "v2"))["version"] == 2


def test_answer_hash_ignores_wording():
    a = make_item()
    b = {**a, "question": "khác", "explanation": "khác"}
    assert catalog.answer_hash(a) == catalog.answer_hash(b)
    assert catalog.answer_hash(a) != catalog.answer_hash({**a, "correct": ["B"]})


def test_existing_lesson_package_keeps_its_ask_hash(ctx, capsys, tmp_path):
    ctx.cli.main(["add-user", "an"])
    pkg1 = _make_package(tmp_path / "v1", slug="demo", content="# Bài học\n")
    lesson = json.loads((pkg1 / "lessons/demo/lesson.json").read_text("utf-8"))
    expected = ctx.catalog._hash_ask([lesson["title"], "# Bài học\n", lesson["summary"], lesson["cards"], lesson["quiz"]])
    pid = ctx.catalog.install_version("an", pkg1)["id"]
    with ctx.db.connect() as c:
        assert c.execute("SELECT ask_hash FROM packages WHERE id=?", (pid,)).fetchone()["ask_hash"] == expected
        c.execute("UPDATE packages SET ask_status='approved' WHERE id=?", (pid,))
    pkg2 = _make_package(tmp_path / "v2", slug="demo", content="# Bài học\n")
    ctx.catalog.install_version("an", pkg2)
    with ctx.db.connect() as c:
        assert c.execute("SELECT ask_status FROM packages WHERE id=?", (pid,)).fetchone()["ask_status"] == "approved"


def test_changing_a_test_requeues_ask_approval(ctx, capsys, tmp_path):
    ctx.cli.main(["add-user", "an"])
    pid = ctx.catalog.install_version("an", write_package(tmp_path / "v1", {"t1": make_test()}))["id"]
    with ctx.db.connect() as c:
        c.execute("UPDATE packages SET ask_status='approved' WHERE id=?", (pid,))
    items = [make_item("q1", explanation="Lời giải mới"), make_item("q2"), make_item("q3")]
    ctx.catalog.install_version("an", write_package(tmp_path / "v2", {"t1": make_test(items=items)}))
    with ctx.db.connect() as c:
        assert c.execute("SELECT ask_status FROM packages WHERE id=?", (pid,)).fetchone()["ask_status"] == "pending"


def test_removed_ids_lists_tests_and_items(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    v1 = write_package(tmp_path / "v1", {"t1": make_test(3), "t2": make_test(2)})
    v2 = write_package(tmp_path / "v2", {"t1": make_test(items=[make_item("q1"), make_item("q3")])})
    with c:
        upload_and_commit(c, zip_of(v1))
        r = send(c, zip_of(v2))
        assert r.status_code == 200
        assert set(r.json()["removed"]) == {"test:t2", "t1/q2"}
        uid = r.json()["upload_id"]
        assert commit(c, uid).status_code == 409
        assert commit(c, uid, confirm_removed=["test:t2", "t1/q2"]).status_code == 200


def test_delete_package_and_owner_leave_no_test_rows(ctx, capsys, tmp_path):
    for name in ("an", "binh"):
        ctx.cli.main(["add-user", name])
    p1 = ctx.catalog.install_version("an", write_package(tmp_path / "p1", {"t1": make_test(2)}, slug="de1"))["id"]
    p2 = ctx.catalog.install_version("an", write_package(tmp_path / "p2", {"t1": make_test(2)}, slug="de2"))["id"]
    with ctx.db.connect() as c:
        for idx, pid in enumerate((p1, p2), 1):
            key = f"{pid}.t1"
            rev = c.execute("SELECT revision_id FROM package_tests WHERE key=?", (key,)).fetchone()["revision_id"]
            aid = f"att{idx}"
            c.execute(
                "INSERT INTO test_attempt(id, user, test_key, revision_id, mode, layout, started_at) VALUES(?,?,?,?,'exam','[]',0)",
                (aid, "binh", key, rev),
            )
            c.execute("INSERT INTO test_answer(attempt, item, chosen) VALUES(?,'q1','[\"A\"]')", (aid,))
            c.execute(
                "INSERT INTO test_first_answer(user, package_id, test_key, item, answer_hash, chosen, correct, at) VALUES('binh',?,?,'q1','h','[\"B\"]',0,0)",
                (pid, key),
            )
            c.execute(
                "INSERT INTO test_pool(user, package_id, test_key, item, answer_hash, added_at) VALUES('binh',?,?,'q1','h',0)",
                (pid, key),
            )

    ctx.catalog.delete_package(p1)
    with ctx.db.connect() as c:
        for table in NEW_TABLES:
            assert c.execute(f"SELECT count(*) n FROM {table}").fetchone()["n"] == 1, table

    assert ctx.cli.main(["remove-user", "an"]) == 0
    with ctx.db.connect() as c:
        for table in NEW_TABLES:
            assert c.execute(f"SELECT count(*) n FROM {table}").fetchone()["n"] == 0, table


def test_upload_json_goes_through_the_same_path(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    body = json.dumps(one_file({"t1": make_test(3, title="Đề")})).encode("utf-8")
    with c:
        r = c.post("/api/uploads", content=body, headers=JSON_HEADERS)
        assert r.status_code == 200
        info = r.json()
        assert info["upload_id"] and info["tests"] == ["Đề"] and info["lessons"] == []
        assert commit(c, info["upload_id"]).status_code == 200
        mine = c.get("/api/packages").json()["mine"]
        assert len(mine) == 1 and mine[0]["first_lesson"] is None and mine[0]["lessons"] == []
        assert mine[0]["tests"] == [{"key": f"{mine[0]['id']}.t1", "title": "Đề", "items": 3, "minutes": 0}]


def test_upload_json_too_large_and_bad_problems(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    limit = ctx.catalog.contract.MAX_TESTS_TOTAL
    with c:
        r_len = c.post("/api/uploads", content=b"{}", headers={**JSON_HEADERS, "Content-Length": str(limit + 1)})
        assert r_len.status_code == 413
        r_stream = c.post("/api/uploads", content=b" " * (limit + 10), headers=JSON_HEADERS)
        assert r_stream.status_code == 413

        dup = make_test(items=[make_item("q1"), make_item("q1")])
        r_bad = c.post("/api/uploads", content=json.dumps(one_file({"t1": dup})).encode("utf-8"), headers=JSON_HEADERS)
        assert r_bad.status_code == 400
        assert any(p["path"] == "tests/t1.json" for p in r_bad.json()["problems"])


def test_upload_zip_with_tests_only_and_with_lessons(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    only_tests = write_package(tmp_path / "p1", {"t1": make_test(2, title="Đề riêng", time_limit_minutes=20)}, slug="only-tests")
    both = _make_package(tmp_path / "p2", slug="both", title="Bài kèm đề")
    (both / "tests").mkdir()
    (both / "tests/t1.json").write_text(json.dumps(make_test(4, title="Đề chung", time_limit_minutes=45)), encoding="utf-8")
    pkg = json.loads((both / "package.json").read_text("utf-8"))
    pkg["tests"] = ["t1"]
    (both / "package.json").write_text(json.dumps(pkg), encoding="utf-8")

    with c:
        id1 = upload_and_commit(c, zip_of(only_tests))["package_id"]
        id2 = upload_and_commit(c, zip_of(both))["package_id"]
        by_id = {p["id"]: p for p in c.get("/api/packages").json()["mine"]}
        assert by_id[id1]["lessons"] == [] and by_id[id1]["first_lesson"] is None
        assert by_id[id1]["tests"] == [{"key": f"{id1}.t1", "title": "Đề riêng", "items": 2, "minutes": 20}]
        assert by_id[id2]["lessons"] == ["Bài kèm đề"] and by_id[id2]["first_lesson"] == f"{id2}.demo"
        assert by_id[id2]["tests"] == [{"key": f"{id2}.t1", "title": "Đề chung", "items": 4, "minutes": 45}]


def test_join_a_test_only_package(ctx, capsys, tmp_path):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    root = write_package(tmp_path / "p", {"t1": make_test(3, title="Đề share", time_limit_minutes=30)})
    with a, b:
        pid = upload_and_commit(a, zip_of(root))["package_id"]
        token = a.post(f"/api/packages/{pid}/link").json()["url"].split("#join=")[1]
        joined = b.post("/api/join", json={"token": token})
        assert joined.status_code == 200
        assert joined.json() == {"package_id": pid, "first_lesson": None}
        shared = b.get("/api/packages").json()["shared"]
        assert len(shared) == 1 and shared[0]["id"] == pid and shared[0]["first_lesson"] is None
        assert shared[0]["tests"] == [{"key": f"{pid}.t1", "title": "Đề share", "items": 3, "minutes": 30}]


def test_ask_request_accepts_a_test_only_package(ctx, capsys, tmp_path):
    an = _ready_client(ctx, capsys, "an")
    boss = _ready_client(ctx, capsys, "boss")
    assert ctx.cli.main(["set-admin", "boss", "on"]) == 0
    root = write_package(tmp_path / "p", {"t1": make_test(2, title="Đề duyệt")})
    with an, boss:
        pid = upload_and_commit(an, zip_of(root))["package_id"]
        assert an.get("/api/packages").json()["mine"][0]["has_content"] is True
        assert an.post(f"/api/packages/{pid}/ask-request").status_code == 200
        with ctx.db.connect() as c:
            assert c.execute("SELECT ask_status FROM packages WHERE id=?", (pid,)).fetchone()["ask_status"] == "pending"
        overview = boss.get("/api/admin/overview").json()
        assert overview["pending"][0]["id"] == pid and overview["pending"][0]["tests"] == 1
        rev = boss.get(f"/api/admin/packages/{pid}/review").json()
        assert rev["ask_status"] == "pending" and len(rev["tests"]) == 1
        assert rev["tests"][0]["items"][0]["correct"] == ["A"]
        assert SENTINELS[0] in rev["tests"][0]["items"][0]["explanation"]
