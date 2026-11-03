"""Tests for the wrong-answer review pool."""
import json

from practice_fixtures import SENTINELS, make_item, make_test, write_package
from test_catalog import _make_package, _ready_client, ctx  # noqa: F401

SECRET = ("correct", "explanation", "best_practice", "docs", "why", "is_correct")


def leaks(response):
    raw = response.text if hasattr(response, "text") else json.dumps(response, ensure_ascii=False)
    return [k for k in SECRET if f'"{k}"' in raw] + [x for x in SENTINELS if x in raw]


def _install(ctx, tmp_path, tests=None, owner="an", name="p", slug="de"):
    root = write_package(tmp_path / name, tests or {"t1": make_test()}, slug=slug)
    res = ctx.main.catalog.install_version(owner, root)
    return res["id"], f"{res['id']}.t1"


def _item_map(attempt_json):
    return {x["id"]: x for x in attempt_json["items"]}


def _pool(ctx, key, user="an"):
    with ctx.db.connect() as conn:
        return sorted(
            r["item"]
            for r in conn.execute("SELECT item FROM test_pool WHERE user=? AND test_key=?", (user, key))
        )


def _pool_row(ctx, key, item, user="an"):
    with ctx.db.connect() as conn:
        r = conn.execute(
            "SELECT * FROM test_pool WHERE user=? AND test_key=? AND item=?", (user, key, item)
        ).fetchone()
    return dict(r) if r else None


def _start_clock(ctx, monkeypatch, t=1000.0):
    state = {"t": t}
    monkeypatch.setattr(ctx.practice, "clock", lambda: state["t"])
    return state


def _check_wrong(c, key, item_id="q1"):
    """A fresh practice attempt (restart) whose chosen answer is wrong."""
    aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice", "restart": True}).json()["id"]
    r = c.post(f"/api/attempts/{aid}/items/{item_id}/check", json={"chosen": ["B"]})
    assert r.status_code == 200 and r.json()["is_correct"] is False


def _check_correct(c, key, item_id="q1"):
    aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice", "restart": True}).json()["id"]
    r = c.post(f"/api/attempts/{aid}/items/{item_id}/check", json={"chosen": ["A"]})
    assert r.status_code == 200 and r.json()["is_correct"] is True


def _enter_wrong(c, key, item_ids):
    """One open practice attempt that checks every listed item wrongly."""
    aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
    for iid in item_ids:
        r = c.post(f"/api/attempts/{aid}/items/{iid}/check", json={"chosen": ["B"]})
        assert r.status_code == 200 and r.json()["is_correct"] is False
    return aid


def test_wrong_enters_blank_does_not(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        assert c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["B"]}).status_code == 200
        assert _pool(ctx, key) == ["q1"]

        exam = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()
        assert c.put(f"/api/attempts/{exam['id']}/items/q2", json={"chosen": []}).status_code == 200
        res = c.post(f"/api/attempts/{exam['id']}/submit").json()
        assert res["result"]["score"] == 0 and res["result"]["total"] == 3
        assert _pool(ctx, key) == ["q1"]


def test_exam_only_enters_at_submit(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        exam = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()
        assert c.put(f"/api/attempts/{exam['id']}/items/q1", json={"chosen": ["B"]}).status_code == 200
        assert _pool(ctx, key) == []
        res = c.post(f"/api/attempts/{exam['id']}/submit").json()
        assert res["result"]["score"] == 0 and res["result"]["total"] == 3
        assert _pool(ctx, key) == ["q1"]


def test_practice_enters_on_check(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        assert _pool(ctx, key) == []
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        r = c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["B"]})
        assert r.status_code == 200 and r.json()["is_correct"] is False
        assert _pool(ctx, key) == ["q1"]
        row = _pool_row(ctx, key, "q1")
        assert row["streak"] == 0 and row["last_correct_at"] is None and row["answer_hash"]


def test_two_correct_under_12_hours_stays(ctx, capsys, tmp_path, monkeypatch):
    state = _start_clock(ctx, monkeypatch)
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        _check_wrong(c, key, "q1")
        assert _pool_row(ctx, key, "q1")["streak"] == 0

        state["t"] += 11 * 3600
        _check_correct(c, key, "q1")
        row = _pool_row(ctx, key, "q1")
        assert row["streak"] == 1 and row["last_correct_at"] == state["t"]

        last_correct = state["t"]
        state["t"] += 11 * 3600
        _check_correct(c, key, "q1")
        row = _pool_row(ctx, key, "q1")
        assert row["streak"] == 1 and row["last_correct_at"] == last_correct
        assert _pool(ctx, key) == ["q1"]


def test_two_correct_12_hours_apart_leaves(ctx, capsys, tmp_path, monkeypatch):
    state = _start_clock(ctx, monkeypatch)
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        exam = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()
        assert c.put(f"/api/attempts/{exam['id']}/items/q1", json={"chosen": ["B"]}).status_code == 200
        res = c.post(f"/api/attempts/{exam['id']}/submit").json()
        assert res["result"]["score"] == 0
        assert _pool(ctx, key) == ["q1"] and _pool_row(ctx, key, "q1")["streak"] == 0

        state["t"] += 3600
        exam2 = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()
        assert c.put(f"/api/attempts/{exam2['id']}/items/q1", json={"chosen": ["A"]}).status_code == 200
        c.post(f"/api/attempts/{exam2['id']}/submit")
        row = _pool_row(ctx, key, "q1")
        assert row["streak"] == 1 and row["last_correct_at"] == state["t"]

        state["t"] += 12 * 3600
        exam3 = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()
        assert c.put(f"/api/attempts/{exam3['id']}/items/q1", json={"chosen": ["A"]}).status_code == 200
        c.post(f"/api/attempts/{exam3['id']}/submit")
        assert _pool(ctx, key) == []


def test_wrong_resets_the_count(ctx, capsys, tmp_path, monkeypatch):
    state = _start_clock(ctx, monkeypatch)
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        _check_wrong(c, key, "q1")
        assert _pool_row(ctx, key, "q1")["streak"] == 0

        state["t"] += 3600
        _check_correct(c, key, "q1")
        assert _pool_row(ctx, key, "q1")["streak"] == 1

        state["t"] += 3600
        _check_wrong(c, key, "q1")
        row = _pool_row(ctx, key, "q1")
        assert row["streak"] == 0 and row["last_correct_at"] is None
        assert _pool(ctx, key) == ["q1"]


def test_review_has_only_pool_items_and_no_history(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        assert c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["B"]}).status_code == 200
        assert c.post(f"/api/attempts/{aid}/items/q2/check", json={"chosen": ["A"]}).status_code == 200
        assert c.post(f"/api/attempts/{aid}/items/q3/check", json={"chosen": ["B"]}).status_code == 200
        assert _pool(ctx, key) == ["q1", "q3"]

        rev = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"}).json()
        assert sorted(x["id"] for x in rev["items"]) == ["q1", "q3"]

        sub = c.post(f"/api/attempts/{rev['id']}/submit")
        assert sub.status_code == 200 and sub.json()["result"] is None

        detail = c.get(f"/api/tests/{key}").json()
        assert detail["history"] == [] and detail["open"]["review"] is None


def test_review_progress_counts_without_finishing(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        _enter_wrong(c, key, ["q1", "q2"])
        rev = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"}).json()
        r = c.post(f"/api/attempts/{rev['id']}/items/q1/check", json={"chosen": ["A"]})
        assert r.status_code == 200 and r.json()["checked"] is True and r.json()["is_correct"] is True

        got = c.get(f"/api/attempts/{rev['id']}").json()
        assert got["status"] == "open" and got["result"] is None
        items = _item_map(got)
        assert items["q1"]["checked"] is True
        assert items["q2"]["checked"] is False and items["q2"]["chosen"] == []
        assert _pool(ctx, key) == ["q1", "q2"]


def test_empty_pool_cannot_start_review(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        r = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"})
        assert r.status_code == 400
        assert r.json()["code"] == "empty"
        assert r.json()["error"] == "Chưa có câu nào cần ôn."
        assert c.get(f"/api/tests/{key}").json()["open"]["review"] is None
        with ctx.db.connect() as conn:
            assert conn.execute("SELECT count(*) n FROM test_attempt WHERE mode='review'").fetchone()["n"] == 0


def test_finished_but_unsubmitted_review_does_not_block_the_next(ctx, capsys, tmp_path, monkeypatch):
    state = _start_clock(ctx, monkeypatch)
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        _check_wrong(c, key, "q1")
        rev1 = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"}).json()["id"]
        r = c.post(f"/api/attempts/{rev1}/items/q1/check", json={"chosen": ["A"]})
        assert r.status_code == 200 and r.json()["is_correct"] is True
        assert _pool(ctx, key) == ["q1"]

        state["t"] += 12 * 3600
        got = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"})
        assert got.status_code == 200
        rev2 = got.json()
        assert rev2["id"] != rev1 and sorted(x["id"] for x in rev2["items"]) == ["q1"]

        r2 = c.post(f"/api/attempts/{rev2['id']}/items/q1/check", json={"chosen": ["A"]})
        assert r2.status_code == 200 and r2.json()["is_correct"] is True
        assert _pool(ctx, key) == []


def test_open_review_with_unchecked_items_resumes(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        _enter_wrong(c, key, ["q1", "q2"])
        rev1 = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"}).json()
        r = c.post(f"/api/attempts/{rev1['id']}/items/q1/check", json={"chosen": ["A"]})
        assert r.status_code == 200

        again = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"}).json()
        assert again["id"] == rev1["id"]
        items = _item_map(again)
        assert items["q1"]["checked"] is True
        assert items["q2"]["checked"] is False


def test_review_result_is_null(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        _check_wrong(c, key, "q1")
        rev = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"}).json()["id"]
        sub = c.post(f"/api/attempts/{rev}/submit")
        assert sub.status_code == 200 and sub.json()["result"] is None
        got = c.get(f"/api/attempts/{rev}").json()
        assert got["status"] == "submitted" and got["result"] is None
        with ctx.db.connect() as conn:
            row = conn.execute("SELECT score, total FROM test_attempt WHERE id=?", (rev,)).fetchone()
        assert row["score"] is None and row["total"] is None


def test_submitting_a_review_does_not_reveal_unchecked_items(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        _enter_wrong(c, key, ["q1", "q2"])
        rev = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"}).json()["id"]
        sub = c.post(f"/api/attempts/{rev}/submit")
        assert sub.status_code == 200 and leaks(sub) == []
        got = c.get(f"/api/attempts/{rev}")
        assert got.status_code == 200 and leaks(got) == []
        for item in got.json()["items"]:
            assert leaks(item) == [] and item["checked"] is False


def test_open_review_on_an_old_revision_is_replaced(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(
        ctx,
        tmp_path,
        {"t1": make_test(items=[make_item("q1", question="Cũ." ), make_item("q2")])},
        name="v1",
    )
    with c:
        _enter_wrong(c, key, ["q1", "q2"])
        rev1 = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"}).json()
        assert c.post(f"/api/attempts/{rev1['id']}/items/q1/check", json={"chosen": ["A"]}).status_code == 200

        _install(
            ctx,
            tmp_path,
            {"t1": make_test(title="Đề hai", items=[make_item("q1", question="Mới."), make_item("q2")])},
            name="v2",
        )
        rev2 = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"}).json()
        assert rev2["id"] != rev1["id"]
        m = _item_map(rev2)
        assert set(m) == {"q1", "q2"} and m["q1"]["question"] == "Mới."
        with ctx.db.connect() as conn:
            rows = conn.execute("SELECT id FROM test_attempt WHERE mode='review'").fetchall()
        assert [r["id"] for r in rows] == [rev2["id"]]


def test_new_answer_resets_streak(ctx, capsys, tmp_path, monkeypatch):
    state = _start_clock(ctx, monkeypatch)
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(2)}, name="v1")
    with c:
        _check_wrong(c, key, "q1")
        state["t"] += 3600
        _check_correct(c, key, "q1")
        assert _pool_row(ctx, key, "q1")["streak"] == 1

        _install(
            ctx,
            tmp_path,
            {"t1": make_test(items=[make_item("q1", correct=("B",)), make_item("q2")])},
            name="v2",
        )
        row = _pool_row(ctx, key, "q1")
        assert row["streak"] == 0 and row["last_correct_at"] is None
        assert row["answer_hash"] == ctx.main.catalog.answer_hash(make_item("q1", correct=("B",)))

        state["t"] += 12 * 3600
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice", "restart": True}).json()["id"]
        r = c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["B"]})
        assert r.status_code == 200 and r.json()["is_correct"] is True
        row = _pool_row(ctx, key, "q1")
        assert row["streak"] == 1 and _pool(ctx, key) == ["q1"]


def test_removed_item_leaves_the_pool(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(3)}, name="v1")
    with c:
        _enter_wrong(c, key, ["q1", "q2", "q3"])
        assert _pool(ctx, key) == ["q1", "q2", "q3"]

        _install(ctx, tmp_path, {"t1": make_test(items=[make_item("q1"), make_item("q3")])}, name="v2")
        assert _pool(ctx, key) == ["q1", "q3"]

        rev = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"}).json()
        assert sorted(x["id"] for x in rev["items"]) == ["q1", "q3"]


def test_old_revision_attempt_cannot_touch_pool(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(3)}, name="v1")
    with c:
        exam = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        for iid in ("q1", "q2", "q3"):
            assert c.put(f"/api/attempts/{exam}/items/{iid}", json={"chosen": ["B"]}).status_code == 200
        assert _pool(ctx, key) == []

        _install(
            ctx,
            tmp_path,
            {"t1": make_test(items=[make_item("q1", correct=("B",)), make_item("q3")])},
            name="v2",
        )
        old = c.post(f"/api/attempts/{exam}/submit")
        assert old.status_code == 200
        res = old.json()["result"]
        assert res["score"] == 0 and res["total"] == 3
        assert _pool(ctx, key) == ["q3"]

        got = c.get(f"/api/attempts/{exam}").json()
        assert got["status"] == "submitted"
        m = _item_map(got)
        assert set(m) == {"q1", "q2", "q3"}
        assert all(m[i]["correct"] == ["A"] for i in m)
        assert m["q1"]["is_correct"] is False and m["q2"]["is_correct"] is False


def test_review_results_are_gated_like_practice(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        _check_wrong(c, key, "q1")
        rev = c.post(f"/api/tests/{key}/attempts", json={"mode": "review"}).json()["id"]
        r0 = c.get(f"/api/attempts/{rev}")
        assert r0.status_code == 200 and leaks(r0) == []

        assert c.put(f"/api/attempts/{rev}/items/q1", json={"chosen": ["A"]}).status_code == 200
        r1 = c.get(f"/api/attempts/{rev}")
        assert leaks(r1) == []
        for item in r1.json()["items"]:
            assert item["checked"] is False and leaks(item) == []
