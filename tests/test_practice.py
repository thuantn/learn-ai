"""Tests for practice test attempts, grading, clock and answer gating."""
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


def test_open_exam_never_returns_answers_on_any_route(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        r_start = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"})
        assert r_start.status_code == 200 and leaks(r_start) == []
        aid = r_start.json()["id"]

        r_get = c.get(f"/api/attempts/{aid}")
        assert r_get.status_code == 200 and leaks(r_get) == []

        r_save = c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"], "flagged": True})
        assert r_save.status_code == 200 and leaks(r_save) == []

        r_get2 = c.get(f"/api/attempts/{aid}")
        assert r_get2.status_code == 200 and leaks(r_get2) == []

        r_pause = c.post(f"/api/attempts/{aid}/pause")
        assert r_pause.status_code == 200 and leaks(r_pause) == []

        r_resume = c.post(f"/api/attempts/{aid}/resume")
        assert r_resume.status_code == 200 and leaks(r_resume) == []

        r_list = c.get("/api/tests")
        assert r_list.status_code == 200 and leaks(r_list) == []

        r_detail = c.get(f"/api/tests/{key}")
        assert r_detail.status_code == 200 and leaks(r_detail) == []


def test_practice_reveals_only_the_checked_item(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        r = c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]})
        assert r.status_code == 200
        q1_check = r.json()
        assert q1_check["correct"] == ["A"] and q1_check["is_correct"] is True
        assert SENTINELS[0] in q1_check["explanation"]
        assert all(SENTINELS[1] in o["why"] for o in q1_check["options"])

        items = _item_map(c.get(f"/api/attempts/{aid}").json())
        assert items["q1"]["checked"] is True and items["q1"]["correct"] == ["A"]
        assert SENTINELS[0] in items["q1"]["explanation"]
        assert items["q2"]["checked"] is False and leaks(items["q2"]) == []
        assert items["q3"]["checked"] is False and leaks(items["q3"]) == []


def test_saved_but_unchecked_practice_item_stays_hidden(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        assert c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]}).status_code == 200
        r = c.get(f"/api/attempts/{aid}")
        assert r.status_code == 200 and leaks(r) == []
        q1 = _item_map(r.json())["q1"]
        assert q1["chosen"] == ["A"] and q1["checked"] is False


def test_check_grades_the_choice_it_carries(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        assert c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]}).status_code == 200
        r = c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["B"]})
        assert r.status_code == 200
        assert r.json()["chosen"] == ["B"] and r.json()["is_correct"] is False

        late = c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]})
        assert late.status_code == 409 and late.json()["code"] == "checked"

        q1 = _item_map(c.get(f"/api/attempts/{aid}").json())["q1"]
        assert q1["chosen"] == ["B"] and q1["is_correct"] is False


def test_flag_after_check_keeps_the_grade(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        assert c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]}).status_code == 200
        with ctx.db.connect() as conn:
            before = dict(conn.execute("SELECT * FROM test_answer WHERE attempt=? AND item='q1'", (aid,)).fetchone())
        assert c.put(f"/api/attempts/{aid}/items/q1", json={"flagged": True}).status_code == 200
        with ctx.db.connect() as conn:
            after = dict(conn.execute("SELECT * FROM test_answer WHERE attempt=? AND item='q1'", (aid,)).fetchone())
        assert after["flagged"] == 1
        assert after["correct"] == before["correct"] == 1
        assert after["answer_hash"] == before["answer_hash"] and after["answer_hash"]
        assert after["chosen"] == before["chosen"] == '["A"]'
        assert after["graded_at"] == before["graded_at"]


def test_flag_only_save_keeps_the_choice(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        assert c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["C"]}).status_code == 200
        assert c.put(f"/api/attempts/{aid}/items/q1", json={"flagged": True}).status_code == 200
        q1 = _item_map(c.get(f"/api/attempts/{aid}").json())["q1"]
        assert q1["chosen"] == ["C"] and q1["flagged"] is True

        assert c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["B"]}).status_code == 200
        q1 = _item_map(c.get(f"/api/attempts/{aid}").json())["q1"]
        assert q1["chosen"] == ["B"] and q1["flagged"] is True


def test_pass_is_decided_on_exact_counts_not_the_rounded_percent(ctx):
    assert ctx.practice._percent(140, 180) == 78
    assert ctx.practice._passed(140, 180, 78) is False
    assert ctx.practice._passed(141, 180, 78) is True
    assert ctx.practice._passed(0, 0, 70) is False


def test_item_outside_the_layout_is_404(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(2)}, name="v1")
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        _install(ctx, tmp_path, {"t1": make_test(3)}, name="v2")
        for item_id in ("q3", "khong-co"):
            r_save = c.put(f"/api/attempts/{aid}/items/{item_id}", json={"chosen": ["A"]})
            assert r_save.status_code == 404 and r_save.json()["code"] == "item"
            r_check = c.post(f"/api/attempts/{aid}/items/{item_id}/check", json={"chosen": ["A"]})
            assert r_check.status_code == 404 and r_check.json()["code"] == "item"


def test_practice_submit_does_not_feed_pool_or_stats_from_unchecked_items(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(2)})
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        assert c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]}).status_code == 200
        assert c.put(f"/api/attempts/{aid}/items/q2", json={"chosen": ["B"]}).status_code == 200
        res = c.post(f"/api/attempts/{aid}/submit").json()
        assert res["result"]["score"] == 1 and res["result"]["total"] == 2
        with ctx.db.connect() as conn:
            first_items = {r["item"] for r in conn.execute("SELECT item FROM test_first_answer").fetchall()}
            pool_count = conn.execute("SELECT count(*) n FROM test_pool").fetchone()["n"]
        assert first_items == {"q1"}
        assert pool_count == 0


def test_changing_pass_percent_keeps_old_results(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(2, pass_percent=50)}, name="v1")
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]})
        c.put(f"/api/attempts/{aid}/items/q2", json={"chosen": ["B"]})
        sub = c.post(f"/api/attempts/{aid}/submit").json()
        assert sub["result"]["percent"] == 50 and sub["result"]["passed"] is True and sub["result"]["pass_percent"] == 50

        _install(ctx, tmp_path, {"t1": make_test(2, pass_percent=80)}, name="v2")
        old = c.get(f"/api/attempts/{aid}").json()
        assert old["result"]["passed"] is True and old["result"]["pass_percent"] == 50
        detail = c.get(f"/api/tests/{key}").json()
        assert detail["pass_percent"] == 80
        assert detail["history"][0]["id"] == aid and detail["history"][0]["passed"] is True


def test_submitted_attempt_shows_everything(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    items = [make_item("q1", docs=["https://a.vn/1"]), make_item("q2"), make_item("q3")]
    _, key = _install(ctx, tmp_path, {"t1": make_test(items=items)})
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]})
        c.put(f"/api/attempts/{aid}/items/q2", json={"chosen": ["B"]})
        sub = c.post(f"/api/attempts/{aid}/submit")
        assert sub.status_code == 200
        for body in (sub.json(), c.get(f"/api/attempts/{aid}").json()):
            assert body["status"] == "submitted"
            assert body["result"]["score"] == 1 and body["result"]["total"] == 3
            by_id = _item_map(body)
            assert by_id["q1"]["is_correct"] is True and by_id["q1"]["docs"] == ["https://a.vn/1"]
            assert by_id["q2"]["is_correct"] is False
            assert by_id["q3"]["is_correct"] is False and by_id["q3"]["chosen"] == []
            for item in body["items"]:
                assert item["correct"] == ["A"]
                assert SENTINELS[0] in item["explanation"]
                assert SENTINELS[2] in item["best_practice"]
                assert all(SENTINELS[1] in o["why"] for o in item["options"])

        for r in (
            c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["B"]}),
            c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]}),
            c.post(f"/api/attempts/{aid}/pause"),
            c.post(f"/api/attempts/{aid}/resume"),
            c.post(f"/api/attempts/{aid}/submit"),
        ):
            assert r.status_code == 409 and r.json()["code"] == "submitted"


def test_other_users_attempt_is_404_for_every_route(ctx, capsys, tmp_path):
    an = _ready_client(ctx, capsys, "an")
    binh = _ready_client(ctx, capsys, "binh")
    pid, key = _install(ctx, tmp_path)
    with an, binh:
        an.post(f"/api/packages/{pid}/share", json={"email": "binh"})
        aid = an.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        for r in (
            binh.get(f"/api/attempts/{aid}"),
            binh.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]}),
            binh.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]}),
            binh.post(f"/api/attempts/{aid}/pause"),
            binh.post(f"/api/attempts/{aid}/resume"),
            binh.post(f"/api/attempts/{aid}/submit"),
            binh.delete(f"/api/attempts/{aid}"),
        ):
            assert r.status_code == 404


def test_revoked_user_gets_404_but_keeps_rows(ctx, capsys, tmp_path):
    an = _ready_client(ctx, capsys, "an")
    binh = _ready_client(ctx, capsys, "binh")
    pid, key = _install(ctx, tmp_path)
    with an, binh:
        an.post(f"/api/packages/{pid}/share", json={"email": "binh"})
        done_id = binh.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        binh.put(f"/api/attempts/{done_id}/items/q1", json={"chosen": ["A"]})
        binh.post(f"/api/attempts/{done_id}/submit")
        open_id = binh.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]

        assert an.post(f"/api/packages/{pid}/unshare", json={"email": "binh"}).status_code == 200
        assert binh.get("/api/tests").json()["tests"] == []
        assert binh.get(f"/api/tests/{key}").status_code == 404
        assert binh.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).status_code == 404
        assert binh.get(f"/api/attempts/{done_id}").status_code == 404
        assert binh.get(f"/api/attempts/{open_id}").status_code == 404
        assert binh.put(f"/api/attempts/{open_id}/items/q1", json={"chosen": ["A"]}).status_code == 404

        with ctx.db.connect() as conn:
            assert conn.execute("SELECT count(*) n FROM test_attempt WHERE user='binh'").fetchone()["n"] == 2
            assert conn.execute("SELECT count(*) n FROM test_first_answer WHERE user='binh'").fetchone()["n"] == 1

        assert an.post(f"/api/packages/{pid}/share", json={"email": "binh"}).status_code == 200
        assert binh.get(f"/api/attempts/{done_id}").status_code == 200
        assert binh.get(f"/api/attempts/{open_id}").status_code == 200
        detail = binh.get(f"/api/tests/{key}").json()
        assert detail["open"]["practice"] == open_id and len(detail["history"]) == 1


def test_exam_refuses_check(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        r = c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]})
        assert r.status_code == 400 and r.json()["code"] == "mode"


def test_check_needs_the_required_count(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    items = [make_item("q1", type="multi", correct=("A", "C")), make_item("q2", type="single", correct=("A",))]
    _, key = _install(ctx, tmp_path, {"t1": make_test(items=items)})
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        for item_id, bad_choice in (("q1", []), ("q1", ["A"]), ("q1", ["A", "B", "C"]), ("q2", [])):
            r = c.post(f"/api/attempts/{aid}/items/{item_id}/check", json={"chosen": bad_choice})
            assert r.status_code == 400 and r.json()["code"] == "count"
        ok = c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A", "C"]})
        assert ok.status_code == 200 and ok.json()["is_correct"] is True


def test_checked_item_cannot_change_but_can_be_flagged(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        assert c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]}).status_code == 200
        r_recheck = c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["B"]})
        assert r_recheck.status_code == 409 and r_recheck.json()["code"] == "checked"
        r_save = c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["B"]})
        assert r_save.status_code == 409 and r_save.json()["code"] == "checked"

        assert c.put(f"/api/attempts/{aid}/items/q1", json={"flagged": True}).status_code == 200
        q1 = _item_map(c.get(f"/api/attempts/{aid}").json())["q1"]
        assert q1["flagged"] is True and q1["chosen"] == ["A"]


def test_chosen_outside_the_item_is_refused(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    items = [make_item("q1", type="single", correct=("A",)), make_item("q2", type="multi", correct=("A", "B"))]
    _, key = _install(ctx, tmp_path, {"t1": make_test(items=items)})
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        for item_id, bad_choice in (
            ("q1", ["Z"]),
            ("q1", ["A", "A"]),
            ("q1", ["A", "B"]),
            ("q1", "A"),
            ("q1", [1]),
            ("q2", ["A", "Z"]),
            ("q2", ["A", "A"]),
            ("q2", ["A", "B", "C"]),
        ):
            r = c.put(f"/api/attempts/{aid}/items/{item_id}", json={"chosen": bad_choice})
            assert r.status_code == 400 and r.json()["code"] == "input"
        r_check = c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["Z"]})
        assert r_check.status_code == 400 and r_check.json()["code"] == "input"


def test_partial_multi_saves(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    items = [make_item("q1", type="multi", correct=("A", "C"))]
    _, key = _install(ctx, tmp_path, {"t1": make_test(items=items)})
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        assert c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]}).status_code == 200
        q1 = _item_map(c.get(f"/api/attempts/{aid}").json())["q1"]
        assert q1["chosen"] == ["A"] and q1["required"] == 2
        assert c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": []}).status_code == 200
        assert _item_map(c.get(f"/api/attempts/{aid}").json())["q1"]["chosen"] == []


def test_last_write_wins_per_item(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        assert c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]}).status_code == 200
        assert c.put(f"/api/attempts/{aid}/items/q2", json={"chosen": ["B"]}).status_code == 200
        assert c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["D"]}).status_code == 200
        items = _item_map(c.get(f"/api/attempts/{aid}").json())
        assert items["q1"]["chosen"] == ["D"] and items["q2"]["chosen"] == ["B"]


def test_multi_is_all_or_nothing(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    items = [make_item(f"q{i}", type="multi", correct=("A", "C")) for i in (1, 2, 3)]
    _, key = _install(ctx, tmp_path, {"t1": make_test(items=items)})
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]})
        c.put(f"/api/attempts/{aid}/items/q2", json={"chosen": ["A", "B"]})
        c.put(f"/api/attempts/{aid}/items/q3", json={"chosen": ["C", "A"]})
        sub = c.post(f"/api/attempts/{aid}/submit").json()
        assert sub["result"]["score"] == 1 and sub["result"]["total"] == 3
        by_id = _item_map(sub)
        assert by_id["q1"]["is_correct"] is False
        assert by_id["q2"]["is_correct"] is False
        assert by_id["q3"]["is_correct"] is True


def test_blank_counts_as_wrong(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(3)})
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]})
        c.put(f"/api/attempts/{aid}/items/q2", json={"flagged": True})
        sub = c.post(f"/api/attempts/{aid}/submit").json()
        assert sub["result"]["score"] == 1 and sub["result"]["total"] == 3
        by_id = _item_map(sub)
        assert by_id["q1"]["is_correct"] is True
        assert by_id["q2"]["is_correct"] is False and by_id["q2"]["chosen"] == []
        assert by_id["q3"]["is_correct"] is False and by_id["q3"]["chosen"] == []
        with ctx.db.connect() as conn:
            ans_rows = {r["item"]: r for r in conn.execute("SELECT * FROM test_answer WHERE attempt=?", (aid,))}
            first_rows = {r["item"] for r in conn.execute("SELECT item FROM test_first_answer")}
        assert set(ans_rows) == {"q1", "q2"}
        assert ans_rows["q1"]["correct"] == 1 and ans_rows["q2"]["correct"] == 0
        assert first_rows == {"q1"}


def test_score_and_domain_breakdown(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    items = [
        make_item("q1", domain="Mạng"),
        make_item("q2", domain="Mạng"),
        make_item("q3", domain="khác"),
        make_item("q4", domain="Khác"),
        make_item("q5", domain=""),
    ]
    _, key = _install(ctx, tmp_path, {"t1": make_test(items=items)})
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]})
        c.put(f"/api/attempts/{aid}/items/q2", json={"chosen": ["A"]})
        c.put(f"/api/attempts/{aid}/items/q3", json={"chosen": ["B"]})
        c.put(f"/api/attempts/{aid}/items/q4", json={"chosen": ["A"]})
        c.put(f"/api/attempts/{aid}/items/q5", json={"chosen": ["B"]})
        res = c.post(f"/api/attempts/{aid}/submit").json()["result"]
        assert res["score"] == 3 and res["total"] == 5 and res["percent"] == 60
        assert res["by_domain"] == [
            {"domain": "Khác", "correct": 1, "total": 3, "percent": 33},
            {"domain": "Mạng", "correct": 2, "total": 2, "percent": 100},
        ]


def test_pass_uses_pass_percent(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(100, pass_percent=78)})
    with c:
        aid1 = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        for i in range(1, 78):
            c.put(f"/api/attempts/{aid1}/items/q{i}", json={"chosen": ["A"]})
        res1 = c.post(f"/api/attempts/{aid1}/submit").json()["result"]
        assert res1["score"] == 77 and res1["percent"] == 77 and res1["passed"] is False

        aid2 = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        for i in range(1, 79):
            c.put(f"/api/attempts/{aid2}/items/q{i}", json={"chosen": ["A"]})
        res2 = c.post(f"/api/attempts/{aid2}/submit").json()["result"]
        assert res2["score"] == 78 and res2["percent"] == 78 and res2["passed"] is True
        assert c.get(f"/api/tests/{key}").json()["best_percent"] == 78


def test_order_differs_between_attempts_and_stays_on_reload(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(10)})
    with c:
        first = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()
        reloaded = c.get(f"/api/attempts/{first['id']}").json()
        sig = lambda d: [(x["id"], [o["id"] for o in x["options"]]) for x in d["items"]]
        assert sig(first) == sig(reloaded)

        seen = {json.dumps(sig(first))}
        for _ in range(5):
            nxt = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam", "restart": True}).json()
            seen.add(json.dumps(sig(nxt)))
        assert len(seen) > 1


def test_shuffle_false_keeps_option_order(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    opts = ("A", "B", "C", "D", "E", "F", "G", "H")
    items = [make_item("q1", options=opts, shuffle=False), make_item("q2", options=opts, shuffle=True)]
    _, key = _install(ctx, tmp_path, {"t1": make_test(items=items)})
    with c:
        for _ in range(10):
            att = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam", "restart": True}).json()
            q1 = _item_map(att)["q1"]
            assert [o["id"] for o in q1["options"]] == list(opts)


def test_one_open_attempt_per_mode_and_restart(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        a1 = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()
        c.put(f"/api/attempts/{a1['id']}/items/q1", json={"chosen": ["A"]})
        again = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()
        assert again["id"] == a1["id"]
        assert _item_map(again)["q1"]["chosen"] == ["A"]

        restarted = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam", "restart": True}).json()
        assert restarted["id"] != a1["id"]
        assert _item_map(restarted)["q1"]["chosen"] == []
        assert c.get(f"/api/attempts/{a1['id']}").status_code == 404


def test_exam_and_practice_can_be_open_together(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        exam = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()
        prac = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()
        assert exam["id"] != prac["id"]
        detail = c.get(f"/api/tests/{key}").json()
        assert detail["open"] == {"exam": exam["id"], "practice": prac["id"], "review": None}


def test_expired_exam_grades_saved_answers_on_read(ctx, capsys, tmp_path, monkeypatch):
    t = 1000.0
    monkeypatch.setattr(ctx.practice, "clock", lambda: t)
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(3, time_limit_minutes=10)})
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]})
        c.put(f"/api/attempts/{aid}/items/q2", json={"chosen": ["B"]})

        t = 1000.0 + 600 + 6
        got = c.get(f"/api/attempts/{aid}").json()
        assert got["status"] == "submitted"
        assert got["result"]["score"] == 1 and got["result"]["total"] == 3
        assert got["result"]["duration_seconds"] == got["time_limit_seconds"] == 600

        fresh = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()
        assert fresh["id"] != aid and fresh["status"] == "open"


def test_save_within_grace_passes_and_after_grace_is_refused(ctx, capsys, tmp_path, monkeypatch):
    t = 1000.0
    monkeypatch.setattr(ctx.practice, "clock", lambda: t)
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(3, time_limit_minutes=10)})
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        t = 1000.0 + 600 + 4
        assert c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]}).status_code == 200

        t = 1000.0 + 600 + 6
        late = c.put(f"/api/attempts/{aid}/items/q2", json={"chosen": ["A"]})
        assert late.status_code == 409 and late.json()["code"] == "submitted"

        got = c.get(f"/api/attempts/{aid}").json()
        assert got["status"] == "submitted" and got["result"]["score"] == 1


def test_pause_stops_the_clock_and_hides_items(ctx, capsys, tmp_path, monkeypatch):
    t = 1000.0
    monkeypatch.setattr(ctx.practice, "clock", lambda: t)
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(3, time_limit_minutes=10)})
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]})
        t = 1100.0
        paused = c.post(f"/api/attempts/{aid}/pause").json()
        assert paused["status"] == "paused" and paused["items"] == [] and paused["remaining"] == 500

        t = 2100.0
        still_paused = c.get(f"/api/attempts/{aid}").json()
        assert still_paused["status"] == "paused" and still_paused["items"] == []
        assert still_paused["remaining"] == 500 and still_paused["elapsed"] == 100

        for r in (
            c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["B"]}),
            c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["B"]}),
            c.post(f"/api/attempts/{aid}/submit"),
        ):
            assert r.status_code == 409 and r.json()["code"] == "paused"

        resumed = c.post(f"/api/attempts/{aid}/resume").json()
        assert resumed["status"] == "open" and len(resumed["items"]) == 3
        assert resumed["pause_count"] == 1 and resumed["paused_seconds"] == 1000
        assert resumed["remaining"] == 500 and resumed["elapsed"] == 100


def test_practice_has_no_time_limit(ctx, capsys, tmp_path, monkeypatch):
    t = 1000.0
    monkeypatch.setattr(ctx.practice, "clock", lambda: t)
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(3, time_limit_minutes=10)})
    with c:
        att = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()
        assert att["remaining"] is None
        t = 10000.0
        got = c.get(f"/api/attempts/{att['id']}").json()
        assert got["status"] == "open" and got["remaining"] is None and got["elapsed"] == 9000


def test_every_read_route_finalizes_an_expired_exam(ctx, capsys, tmp_path, monkeypatch):
    t = 1000.0
    monkeypatch.setattr(ctx.practice, "clock", lambda: t)
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(3, time_limit_minutes=10)})
    with c:
        aid1 = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        c.put(f"/api/attempts/{aid1}/items/q1", json={"chosen": ["A"]})
        t += 610
        listed = c.get("/api/tests").json()["tests"][0]
        assert listed["open"]["exam"] is None and listed["best_percent"] == 33

        aid2 = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        c.put(f"/api/attempts/{aid2}/items/q1", json={"chosen": ["A"]})
        c.put(f"/api/attempts/{aid2}/items/q2", json={"chosen": ["A"]})
        t += 610
        detail = c.get(f"/api/tests/{key}").json()
        assert detail["open"]["exam"] is None and detail["best_percent"] == 67
        assert [h["id"] for h in detail["history"]] == [aid2, aid1]


def test_late_finalize_uses_the_deadline_as_the_grade_time(ctx, capsys, tmp_path, monkeypatch):
    t = 1000.0
    monkeypatch.setattr(ctx.practice, "clock", lambda: t)
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path, {"t1": make_test(3, time_limit_minutes=10)})
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["B"]})
        deadline = 1000.0 + 600
        t = 1000.0 + 3 * 86400
        got = c.get(f"/api/attempts/{aid}").json()
        assert got["status"] == "submitted"
        with ctx.db.connect() as conn:
            att = conn.execute("SELECT submitted_at FROM test_attempt WHERE id=?", (aid,)).fetchone()
            ans = conn.execute("SELECT graded_at FROM test_answer WHERE attempt=? AND item='q1'", (aid,)).fetchone()
            first = conn.execute("SELECT at FROM test_first_answer WHERE test_key=? AND item='q1'", (key,)).fetchone()
        assert att["submitted_at"] == deadline
        assert ans["graded_at"] == deadline
        assert first["at"] == deadline


def test_discard_only_while_open(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    _, key = _install(ctx, tmp_path)
    with c:
        aid1 = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        assert c.delete(f"/api/attempts/{aid1}").status_code == 200
        assert c.get(f"/api/attempts/{aid1}").status_code == 404

        aid2 = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        c.post(f"/api/attempts/{aid2}/pause")
        assert c.delete(f"/api/attempts/{aid2}").status_code == 200
        assert c.get(f"/api/attempts/{aid2}").status_code == 404

        aid3 = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        c.post(f"/api/attempts/{aid3}/submit")
        r = c.delete(f"/api/attempts/{aid3}")
        assert r.status_code == 409 and r.json()["code"] == "submitted"
        assert c.get(f"/api/attempts/{aid3}").status_code == 200


def test_removed_test_still_shows_old_results(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    pid, key1 = _install(ctx, tmp_path, {"t1": make_test(title="Đề cũ"), "t2": make_test(title="Đề còn")}, name="v1")
    with c:
        aid = c.post(f"/api/tests/{key1}/attempts", json={"mode": "exam"}).json()["id"]
        c.put(f"/api/attempts/{aid}/items/q1", json={"chosen": ["A"]})
        c.post(f"/api/attempts/{aid}/submit")

        _install(ctx, tmp_path, {"t2": make_test(title="Đề còn")}, name="v2")
        old = c.get(f"/api/attempts/{aid}")
        assert old.status_code == 200
        assert old.json()["title"] == "Đề cũ" and old.json()["result"]["score"] == 1
        assert c.post(f"/api/tests/{key1}/attempts", json={"mode": "exam"}).status_code == 404
        assert c.get(f"/api/tests/{key1}").status_code == 404
