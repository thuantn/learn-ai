"""Tests for Task 5: asking about an item, item feedback, author test stats."""
import json
import re
import time
import types

import pytest

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


def _share(ctx, package_id, user):
    with ctx.db.connect() as conn:
        conn.execute(
            "INSERT INTO package_access(package_id, user, via, granted_at) VALUES(?,?,'email',?) "
            "ON CONFLICT(package_id, user) DO UPDATE SET revoked_at=NULL",
            (package_id, user, time.time()),
        )


def _approve(ctx, package_id):
    with ctx.db.connect() as conn:
        conn.execute("UPDATE packages SET ask_status='approved' WHERE id=?", (package_id,))


@pytest.fixture
def fake_ai(ctx, monkeypatch):
    calls = []

    class FakeAI:
        def __init__(self):
            self.calls = calls
            self.reply_text = "Lời giải chi tiết từ trợ giảng AI."
            self.current_setting = {
                "provider": "openrouter",
                "model": "google/gemini-2.0-flash",
                "key": "sk-fake-test-key",
                "base": "https://openrouter.ai/api/v1",
                "source": "admin",
            }

        def call(self, messages):
            self.calls.append(messages)
            return self.reply_text

    fake = FakeAI()
    monkeypatch.setattr(ctx.main.ai, "call", fake.call)
    monkeypatch.setattr(ctx.main.ai, "current", lambda: fake.current_setting)
    return fake


def test_ask_refused_before_reveal(ctx, capsys, tmp_path, fake_ai):
    c = _ready_client(ctx, capsys, "an")
    pid, key = _install(ctx, tmp_path)
    _approve(ctx, pid)
    with c:
        # Unsubmitted exam attempt:
        aid_exam = c.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        r_get = c.get(f"/api/attempts/{aid_exam}/items/q1/ask")
        assert r_get.status_code == 403 and r_get.json()["code"] == "not_revealed"
        r_post = c.post(f"/api/attempts/{aid_exam}/items/q1/ask", json={"question": "giải thích giúp"})
        assert r_post.status_code == 403 and r_post.json()["code"] == "not_revealed"

        # Unchecked practice attempt:
        aid_prac = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        r_get2 = c.get(f"/api/attempts/{aid_prac}/items/q1/ask")
        assert r_get2.status_code == 403 and r_get2.json()["code"] == "not_revealed"
        r_post2 = c.post(f"/api/attempts/{aid_prac}/items/q1/ask", json={"question": "giải thích giúp"})
        assert r_post2.status_code == 403 and r_post2.json()["code"] == "not_revealed"

        # Model was never called
        assert len(fake_ai.calls) == 0

        # After checking the item in practice, asking is allowed:
        r_check = c.post(f"/api/attempts/{aid_prac}/items/q1/check", json={"chosen": ["A"]})
        assert r_check.status_code == 200
        r_get3 = c.get(f"/api/attempts/{aid_prac}/items/q1/ask")
        assert r_get3.status_code == 200 and r_get3.json() == {"messages": []}
        r_post3 = c.post(f"/api/attempts/{aid_prac}/items/q1/ask", json={"question": "giải thích giúp"})
        assert r_post3.status_code == 200 and r_post3.json() == {"text": fake_ai.reply_text}
        assert len(fake_ai.calls) == 1


def test_ask_prompt_holds_one_item_only(ctx, capsys, tmp_path, fake_ai):
    c = _ready_client(ctx, capsys, "an")
    item1 = make_item("q1", question="Câu hỏi RIÊNG_1?", explanation="Lời giải RIÊNG_1")
    item2 = make_item("q2", question="Câu hỏi RIÊNG_2?", explanation="Lời giải RIÊNG_2")
    item3 = make_item("q3", question="Câu hỏi RIÊNG_3?", explanation="Lời giải RIÊNG_3")
    pid, key = _install(ctx, tmp_path, {"t1": make_test(items=[item1, item2, item3])})
    _approve(ctx, pid)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]})
        r = c.post(f"/api/attempts/{aid}/items/q1/ask", json={"question": "Vì sao lại là A?"})
        assert r.status_code == 200

        assert len(fake_ai.calls) == 1
        messages = fake_ai.calls[0]
        sys_msg = next(m["content"] for m in messages if m["role"] == "system")
        assert "RIÊNG_1" in sys_msg
        assert "RIÊNG_2" not in sys_msg
        assert "RIÊNG_3" not in sys_msg
        assert "CAU-" in sys_msg
        boundaries = re.findall(r"CAU-[0-9a-f]{16}", sys_msg)
        assert len(boundaries) >= 2
        assert sys_msg.endswith(ctx.main.ai.DATA_REMINDER)
        assert "Chữ A" in sys_msg


def test_ask_prompt_names_options_by_text(ctx, capsys, tmp_path, fake_ai):
    c = _ready_client(ctx, capsys, "an")
    item = make_item("q1", options=("A", "B"))
    item["options"] = [
        {"id": "A", "text": "Phương án Alpha", "why": "Vì Alpha đúng"},
        {"id": "B", "text": "Phương án Beta", "why": "Vì Beta sai"},
    ]
    pid, key = _install(ctx, tmp_path, {"t1": make_test(items=[item])})
    _approve(ctx, pid)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]})
        c.post(f"/api/attempts/{aid}/items/q1/ask", json={"question": "Giải thích Alpha"})

        sys_msg = fake_ai.calls[0][0]["content"]
        assert "- Phương án Alpha" in sys_msg
        assert "- Phương án Beta" in sys_msg
        assert "A." not in sys_msg and "B." not in sys_msg
        assert "- A:" not in sys_msg and "- B:" not in sys_msg
        assert "không nhắc lựa chọn bằng chữ cái" in sys_msg


def test_ask_needs_approval_and_uses_zdr_path(ctx, capsys, tmp_path, fake_ai):
    c = _ready_client(ctx, capsys, "an")
    pid, key = _install(ctx, tmp_path)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]})
        # Default ask_status is 'none':
        r_none = c.post(f"/api/attempts/{aid}/items/q1/ask", json={"question": "hỏi"})
        assert r_none.status_code == 503 and r_none.json()["code"] == "disabled"

        # When pending:
        with ctx.db.connect() as conn:
            conn.execute("UPDATE packages SET ask_status='pending' WHERE id=?", (pid,))
        r_pending = c.post(f"/api/attempts/{aid}/items/q1/ask", json={"question": "hỏi"})
        assert r_pending.status_code == 503 and r_pending.json()["code"] == "disabled"

        # When rejected:
        with ctx.db.connect() as conn:
            conn.execute("UPDATE packages SET ask_status='rejected' WHERE id=?", (pid,))
        r_rej = c.post(f"/api/attempts/{aid}/items/q1/ask", json={"question": "hỏi"})
        assert r_rej.status_code == 503 and r_rej.json()["code"] == "disabled"

        assert len(fake_ai.calls) == 0

        # When approved:
        with ctx.db.connect() as conn:
            conn.execute("UPDATE packages SET ask_status='approved' WHERE id=?", (pid,))
        r_app = c.post(f"/api/attempts/{aid}/items/q1/ask", json={"question": "hỏi"})
        assert r_app.status_code == 200
        assert len(fake_ai.calls) == 1


def test_ask_thread_is_per_item_and_survives_reload(ctx, capsys, tmp_path, fake_ai):
    c = _ready_client(ctx, capsys, "an")
    pid, key = _install(ctx, tmp_path)
    _approve(ctx, pid)
    with c:
        aid = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]})
        c.post(f"/api/attempts/{aid}/items/q2/check", json={"chosen": ["A"]})

        # Ask on q1:
        c.post(f"/api/attempts/{aid}/items/q1/ask", json={"question": "Câu 1 turn 1"})
        t1 = c.get(f"/api/attempts/{aid}/items/q1/ask").json()["messages"]
        assert len(t1) == 2 and t1[0]["text"] == "Câu 1 turn 1"

        # q2 thread is empty:
        t2 = c.get(f"/api/attempts/{aid}/items/q2/ask").json()["messages"]
        assert t2 == []

        # Start a new attempt on the same test, check q1, reload thread:
        aid2 = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice", "restart": True}).json()["id"]
        c.post(f"/api/attempts/{aid2}/items/q1/check", json={"chosen": ["A"]})
        t1_reload = c.get(f"/api/attempts/{aid2}/items/q1/ask").json()["messages"]
        assert len(t1_reload) == 2 and t1_reload[0]["text"] == "Câu 1 turn 1"

        # Second turn on q1 sends previous messages to AI:
        c.post(f"/api/attempts/{aid2}/items/q1/ask", json={"question": "Câu 1 turn 2"})
        sent = fake_ai.calls[-1]
        user_msgs = [m["content"] for m in sent if m["role"] == "user"]
        assert user_msgs == ["Câu 1 turn 1", "Câu 1 turn 2"]


def test_ask_shares_daily_quota_with_lessons(ctx, capsys, tmp_path, fake_ai, monkeypatch):
    monkeypatch.setenv("AI_DAILY_LIMIT", "2")
    c = _ready_client(ctx, capsys, "an")

    # Install lesson package:
    l_pkg = _make_package(tmp_path / "lp", slug="demo")
    l_res = ctx.main.catalog.install_version("an", l_pkg)
    l_key = f"{l_res['id']}.demo"
    _approve(ctx, l_res["id"])

    # Install test package:
    t_pid, t_key = _install(ctx, tmp_path, name="tp", slug="testpkg")
    _approve(ctx, t_pid)

    with c:
        aid = c.post(f"/api/tests/{t_key}/attempts", json={"mode": "practice"}).json()["id"]
        c.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]})

        # Ask 1: on lesson (takes quota 1/2)
        r1 = c.post("/api/ask", json={"lesson": l_key, "question": "Hỏi bài học"})
        assert r1.status_code == 200

        # Ask 2: on test item (takes quota 2/2)
        r2 = c.post(f"/api/attempts/{aid}/items/q1/ask", json={"question": "Hỏi đề thi"})
        assert r2.status_code == 200

        # Ask 3: exceeded quota on test item -> 429
        r3 = c.post(f"/api/attempts/{aid}/items/q1/ask", json={"question": "Hỏi tiếp"})
        assert r3.status_code == 429 and r3.json()["code"] == "rate_limited"

        # Ask 3: exceeded quota on lesson -> 429
        r4 = c.post("/api/ask", json={"lesson": l_key, "question": "Hỏi bài học tiếp"})
        assert r4.status_code == 429 and r4.json()["code"] == "rate_limited"


def test_leave_removes_item_threads_and_delete_clears_one(ctx, capsys, tmp_path, fake_ai):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    pid, key = _install(ctx, tmp_path)
    _approve(ctx, pid)
    _share(ctx, pid, "binh")

    with b:
        aid = b.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        b.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]})
        b.post(f"/api/attempts/{aid}/items/q1/ask", json={"question": "binh hỏi"})
        assert len(b.get(f"/api/attempts/{aid}/items/q1/ask").json()["messages"]) == 2

        # DELETE clears thread for q1:
        r_del = b.delete(f"/api/attempts/{aid}/items/q1/ask")
        assert r_del.status_code == 200 and r_del.json() == {"ok": True}
        assert b.get(f"/api/attempts/{aid}/items/q1/ask").json()["messages"] == []

        # Ask again on q1:
        b.post(f"/api/attempts/{aid}/items/q1/ask", json={"question": "binh hỏi lại"})
        assert len(b.get(f"/api/attempts/{aid}/items/q1/ask").json()["messages"]) == 2

        # Leave package removes all threads for that package:
        r_leave = b.post(f"/api/packages/{pid}/leave")
        assert r_leave.status_code == 200
        with ctx.db.connect() as conn:
            assert conn.execute("SELECT count(*) n FROM ask_message WHERE user='binh'").fetchone()["n"] == 0


def test_lesson_ask_still_works(ctx, capsys, tmp_path, fake_ai):
    c = _ready_client(ctx, capsys, "an")
    pkg = _make_package(tmp_path / "lp", slug="demo")
    res = ctx.main.catalog.install_version("an", pkg)
    lkey = f"{res['id']}.demo"
    _approve(ctx, res["id"])

    with c:
        r = c.post("/api/ask", json={"lesson": lkey, "question": "Hỏi bài học"})
        assert r.status_code == 200 and r.json() == {"text": fake_ai.reply_text}
        msgs = c.get(f"/api/lessons/{lkey}/ask").json()["messages"]
        assert len(msgs) == 2
        r_del = c.delete(f"/api/lessons/{lkey}/ask")
        assert r_del.status_code == 200
        assert c.get(f"/api/lessons/{lkey}/ask").json()["messages"] == []


def test_feedback_on_item_reaches_author_with_question(ctx, capsys, tmp_path):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    pid, key = _install(ctx, tmp_path)
    _share(ctx, pid, "binh")

    with b:
        # Can report while taking exam (unsubmitted):
        aid = b.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        r = b.post(f"/api/attempts/{aid}/items/q1/feedback", json={"kind": "wrong", "text": "Câu này đáp án sai"})
        assert r.status_code == 200 and r.json() == {"ok": True}

    with a:
        fb = a.get(f"/api/packages/{pid}/feedback").json()["feedback"]
        assert len(fb) == 1
        entry = fb[0]
        assert entry["lesson_title"] == "Đề"
        assert entry["target_type"] == "test_item"
        assert entry["target_id"] == "q1"
        assert entry["target_text"] == "Câu hỏi q1?"
        assert entry["kind"] == "wrong"
        assert entry["author"] == "binh"
        assert entry["body"] == "Câu này đáp án sai"

        # Update package removing q1:
        _install(ctx, tmp_path, {"t1": make_test(items=[make_item("q2"), make_item("q3")])}, name="v2")
        fb2 = a.get(f"/api/packages/{pid}/feedback").json()["feedback"]
        assert fb2[0]["target_text"] is None
        assert fb2[0]["lesson_title"] == "Đề"


def test_feedback_unknown_item_is_refused(ctx, capsys, tmp_path):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    pid, key = _install(ctx, tmp_path)
    _share(ctx, pid, "binh")

    with b:
        aid = b.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        # Unknown item id:
        r_unk = b.post(f"/api/attempts/{aid}/items/khong-co/feedback", json={"kind": "wrong", "text": "Sai"})
        assert r_unk.status_code == 404 and r_unk.json()["code"] == "item"

        # Bad kind:
        r_kind = b.post(f"/api/attempts/{aid}/items/q1/feedback", json={"kind": "khong-dung", "text": "Sai"})
        assert r_kind.status_code == 400 and r_kind.json()["code"] == "input"

        # Empty text:
        r_empty = b.post(f"/api/attempts/{aid}/items/q1/feedback", json={"kind": "wrong", "text": "   "})
        assert r_empty.status_code == 400 and r_empty.json()["code"] == "input"

    with a:
        # Attempt belonging to someone else:
        r_other = a.post(f"/api/attempts/{aid}/items/q1/feedback", json={"kind": "wrong", "text": "Sai"})
        assert r_other.status_code == 404 and r_other.json()["code"] == "attempt"


def test_stats_hidden_under_three_people(ctx, capsys, tmp_path):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    c = _ready_client(ctx, capsys, "cuong")
    pid, key = _install(ctx, tmp_path)
    _share(ctx, pid, "binh")
    _share(ctx, pid, "cuong")

    # 2 learners answer in practice:
    for user_client in (b, c):
        with user_client:
            aid = user_client.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
            user_client.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]})
            user_client.post(f"/api/attempts/{aid}/items/q2/check", json={"chosen": ["B"]})
            user_client.post(f"/api/attempts/{aid}/items/q3/check", json={"chosen": ["A"]})

    with a:
        st = a.get(f"/api/packages/{pid}/test-stats").json()["tests"][0]
        assert st["items"] == []
        assert st["hidden"] == 3


def test_stats_excludes_author_and_review_and_blanks(ctx, capsys, tmp_path):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    c = _ready_client(ctx, capsys, "cuong")
    d = _ready_client(ctx, capsys, "dung")
    pid, key = _install(ctx, tmp_path)
    _share(ctx, pid, "binh")
    _share(ctx, pid, "cuong")
    _share(ctx, pid, "dung")

    # Author answers (must NOT count towards stats):
    with a:
        aid_a = a.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        a.post(f"/api/attempts/{aid_a}/items/q1/check", json={"chosen": ["B"]})

    # Learner b submits blank exam (must NOT enter first answer):
    with b:
        aid_b = b.post(f"/api/tests/{key}/attempts", json={"mode": "exam"}).json()["id"]
        b.post(f"/api/attempts/{aid_b}/submit")

    # Now 3 learners (b, c, d) answer in practice:
    with b:
        aid_b2 = b.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        b.post(f"/api/attempts/{aid_b2}/items/q1/check", json={"chosen": ["A"]})  # correct
    with c:
        aid_c = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        c.post(f"/api/attempts/{aid_c}/items/q1/check", json={"chosen": ["B"]})  # wrong
    with d:
        aid_d = d.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        d.post(f"/api/attempts/{aid_d}/items/q1/check", json={"chosen": ["B"]})  # wrong
        # d takes review mode on q1 and gets it right; review mode must not record first answer:
        aid_d_rev = d.post(f"/api/tests/{key}/attempts", json={"mode": "review"}).json()["id"]
        d.post(f"/api/attempts/{aid_d_rev}/items/q1/check", json={"chosen": ["A"]})

    # Check stats:
    with a:
        st = a.get(f"/api/packages/{pid}/test-stats").json()["tests"][0]
        q1_stat = next(x for x in st["items"] if x["id"] == "q1")
        assert q1_stat["people"] == 3
        assert q1_stat["wrong_percent"] == 67  # 2 out of 3 wrong
        assert q1_stat["top_wrong"] == {"id": "B", "text": "Chữ B"}


def test_stats_count_first_answer_only(ctx, capsys, tmp_path):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    c = _ready_client(ctx, capsys, "cuong")
    d = _ready_client(ctx, capsys, "dung")
    pid, key = _install(ctx, tmp_path)
    _share(ctx, pid, "binh")
    _share(ctx, pid, "cuong")
    _share(ctx, pid, "dung")

    # binh answers WRONG first:
    with b:
        aid_b = b.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        b.post(f"/api/attempts/{aid_b}/items/q1/check", json={"chosen": ["B"]})
        # binh restarts and answers CORRECT:
        aid_b2 = b.post(f"/api/tests/{key}/attempts", json={"mode": "practice", "restart": True}).json()["id"]
        b.post(f"/api/attempts/{aid_b2}/items/q1/check", json={"chosen": ["A"]})

    # cuong and dung answer CORRECT first:
    with c:
        aid_c = c.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        c.post(f"/api/attempts/{aid_c}/items/q1/check", json={"chosen": ["A"]})
    with d:
        aid_d = d.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
        d.post(f"/api/attempts/{aid_d}/items/q1/check", json={"chosen": ["A"]})

    # Stats must count binh's first (wrong) answer:
    with a:
        st = a.get(f"/api/packages/{pid}/test-stats").json()["tests"][0]
        q1 = next(x for x in st["items"] if x["id"] == "q1")
        assert q1["people"] == 3
        assert q1["wrong_percent"] == 33  # 1 out of 3
        assert q1["top_wrong"] == {"id": "B", "text": "Chữ B"}


def test_stats_restart_after_answer_change(ctx, capsys, tmp_path):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    c = _ready_client(ctx, capsys, "cuong")
    d = _ready_client(ctx, capsys, "dung")
    pid, key = _install(ctx, tmp_path)
    _share(ctx, pid, "binh")
    _share(ctx, pid, "cuong")
    _share(ctx, pid, "dung")

    # 3 learners answer on revision 1:
    for user_client in (b, c, d):
        with user_client:
            aid = user_client.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
            user_client.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]})

    with a:
        st1 = a.get(f"/api/packages/{pid}/test-stats").json()["tests"][0]
        assert len(st1["items"]) == 1 and st1["items"][0]["id"] == "q1"

        # Author updates package: changes correct answer for q1 from ["A"] to ["B"]:
        new_items = [make_item("q1", correct=("B",)), make_item("q2"), make_item("q3")]
        _install(ctx, tmp_path, {"t1": make_test(items=new_items)}, name="v2")

        # Stats for q1 restart because answer_hash changed:
        st2 = a.get(f"/api/packages/{pid}/test-stats").json()["tests"][0]
        assert st2["items"] == []
        assert st2["hidden"] == 3


def test_stats_owner_only_and_no_names(ctx, capsys, tmp_path):
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    c = _ready_client(ctx, capsys, "cuong")
    d = _ready_client(ctx, capsys, "dung")
    pid, key = _install(ctx, tmp_path)
    _share(ctx, pid, "binh")
    _share(ctx, pid, "cuong")
    _share(ctx, pid, "dung")

    for user_client in (b, c, d):
        with user_client:
            aid = user_client.post(f"/api/tests/{key}/attempts", json={"mode": "practice"}).json()["id"]
            user_client.post(f"/api/attempts/{aid}/items/q1/check", json={"chosen": ["A"]})

    with b:
        # Shared learner gets 404:
        r_b = b.get(f"/api/packages/{pid}/test-stats")
        assert r_b.status_code == 404 and r_b.json()["code"] == "package"

    z = _ready_client(ctx, capsys, "stranger")
    with z:
        # Stranger gets 404:
        r_z = z.get(f"/api/packages/{pid}/test-stats")
        assert r_z.status_code == 404 and r_z.json()["code"] == "package"

    with a:
        # Owner gets 200:
        r_a = a.get(f"/api/packages/{pid}/test-stats")
        assert r_a.status_code == 200
        raw = r_a.text
        # No learner usernames appear in stats:
        assert '"binh"' not in raw
        assert '"cuong"' not in raw
        assert '"dung"' not in raw
        # Ensure item structure contains only expected statistical fields:
        st = r_a.json()["tests"][0]
        assert len(st["items"]) == 1
        assert set(st["items"][0].keys()) == {"id", "question", "people", "wrong_percent", "top_wrong"}
