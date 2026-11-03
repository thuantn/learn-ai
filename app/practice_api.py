"""HTTP routes for practice test listings and attempts."""
from fastapi import APIRouter, Request

from . import db, practice
from .web_util import bad, read_json

router = APIRouter()


def _with_db(fn, *args):
    try:
        with db.connect() as c:
            return fn(c, *args)
    except practice.Refused as e:
        return bad(e.status, e.code, e.message)


def _with_attempt(user: str, attempt_id: str, fn, *args):
    def work(c):
        row = practice.load(c, user, attempt_id)
        if not row:
            raise practice.Refused("attempt", 404, "Không có lượt làm này.")
        return fn(c, row, *args)

    return _with_db(work)


@router.get("/api/tests")
async def get_tests(request: Request):
    return _with_db(lambda c: {"tests": practice.list_tests(c, request.state.user)})


@router.get("/api/tests/{key}")
async def get_test(key: str, request: Request):
    res = _with_db(practice.test_detail, request.state.user, key)
    return res if res is not None else bad(404, "test", "Không có bộ đề này.")


@router.post("/api/tests/{key}/attempts")
async def start_attempt(key: str, request: Request):
    data = await read_json(request)
    if not data or not isinstance(data.get("mode"), str) or not isinstance(data.get("restart", False), bool):
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    res = _with_db(practice.start, request.state.user, key, data["mode"], bool(data.get("restart", False)))
    return res if res is not None else bad(404, "test", "Không có bộ đề này.")


@router.get("/api/attempts/{attempt_id}")
async def get_attempt(attempt_id: str, request: Request):
    return _with_attempt(request.state.user, attempt_id, lambda c, row: practice.view(c, request.state.user, row))


@router.put("/api/attempts/{attempt_id}/items/{item_id}")
async def save_item(attempt_id: str, item_id: str, request: Request):
    data = await read_json(request)
    if not data:
        return bad(400, "input", "Dữ liệu không hợp lệ.")

    def work(c, row):
        practice.save(c, row, item_id, data.get("chosen"), data.get("flagged"))
        return {"ok": True}

    return _with_attempt(request.state.user, attempt_id, work)


@router.post("/api/attempts/{attempt_id}/items/{item_id}/check")
async def check_item(attempt_id: str, item_id: str, request: Request):
    data = await read_json(request)
    if not data or "chosen" not in data:
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    return _with_attempt(request.state.user, attempt_id, practice.check, item_id, data.get("chosen"))


@router.post("/api/attempts/{attempt_id}/pause")
async def pause_attempt(attempt_id: str, request: Request):
    return _with_attempt(request.state.user, attempt_id, practice.pause)


@router.post("/api/attempts/{attempt_id}/resume")
async def resume_attempt(attempt_id: str, request: Request):
    return _with_attempt(request.state.user, attempt_id, practice.resume)


@router.post("/api/attempts/{attempt_id}/submit")
async def submit_attempt(attempt_id: str, request: Request):
    return _with_attempt(request.state.user, attempt_id, practice.submit)


@router.delete("/api/attempts/{attempt_id}")
async def discard_attempt(attempt_id: str, request: Request):
    def work(c, row):
        practice.discard(c, row)
        return {"ok": True}

    return _with_attempt(request.state.user, attempt_id, work)


@router.get("/api/attempts/{attempt_id}/items/{item_id}/ask")
async def get_item_ask(attempt_id: str, item_id: str, request: Request):
    user = request.state.user
    with db.connect() as c:
        try:
            target = practice.ask_target(c, user, attempt_id, item_id)
        except practice.Refused as e:
            return bad(e.status, e.code, e.message)
        if not target:
            if not practice.load(c, user, attempt_id):
                return bad(404, "attempt", "Không có lượt làm này.")
            return bad(404, "item", "Không có câu hỏi này.")
        thread_key, _, _, _ = target
        from . import main
        rows = c.execute(
            "SELECT role, body FROM ask_message WHERE user=? AND lesson=? ORDER BY id DESC LIMIT ?",
            (user, thread_key, main.ASK_SHOW),
        ).fetchall()
    return {"messages": [{"role": r["role"], "text": r["body"]} for r in reversed(rows)]}


@router.post("/api/attempts/{attempt_id}/items/{item_id}/ask")
async def post_item_ask(attempt_id: str, item_id: str, request: Request):
    user = request.state.user
    with db.connect() as c:
        try:
            target = practice.ask_target(c, user, attempt_id, item_id)
        except practice.Refused as e:
            return bad(e.status, e.code, e.message)
        if not target:
            if not practice.load(c, user, attempt_id):
                return bad(404, "attempt", "Không có lượt làm này.")
            return bad(404, "item", "Không có câu hỏi này.")
        thread_key, item, test_title, ask_status = target
        if ask_status != "approved":
            return bad(503, "disabled", "Ô Hỏi chưa được bật.")
    from . import main
    if main.ai.current() is None:
        return bad(503, "disabled", "Ô Hỏi chưa được bật.")
    data = await read_json(request, main.ASK_INPUT_MAX * 4)
    question = (data or {}).get("question")
    if not isinstance(question, str):
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    question = question.strip()
    if not 0 < len(question) <= main.QUESTION_MAX:
        return bad(400, "input", "Câu hỏi quá dài hoặc đang trống.")
    system = practice.item_context(test_title, item)
    return await main.run_ask(
        user, thread_key, system, question,
        lambda conn: practice.item_still_allowed(conn, user, attempt_id, item_id),
    )


@router.delete("/api/attempts/{attempt_id}/items/{item_id}/ask")
async def delete_item_ask(attempt_id: str, item_id: str, request: Request):
    user = request.state.user
    with db.connect() as c:
        try:
            target = practice.ask_target(c, user, attempt_id, item_id)
        except practice.Refused as e:
            return bad(e.status, e.code, e.message)
        if not target:
            if not practice.load(c, user, attempt_id):
                return bad(404, "attempt", "Không có lượt làm này.")
            return bad(404, "item", "Không có câu hỏi này.")
        thread_key, _, _, _ = target
        c.execute("DELETE FROM ask_message WHERE user=? AND lesson=?", (user, thread_key))
    return {"ok": True}


@router.post("/api/attempts/{attempt_id}/items/{item_id}/feedback")
async def post_item_feedback(attempt_id: str, item_id: str, request: Request):
    user = request.state.user
    data = await read_json(request) or {}
    with db.connect() as c:
        row = practice.load(c, user, attempt_id)
        if not row:
            return bad(404, "attempt", "Không có lượt làm này.")
        item = practice.item_in(c, row, item_id)
        if not item:
            return bad(404, "item", "Không có câu hỏi này.")
        rev = c.execute("SELECT package_id FROM test_revision WHERE id=?", (row["revision_id"],)).fetchone()
        if not rev:
            return bad(404, "package", "Không có package này.")
        from . import main
        refused = main.save_feedback(
            c, user, rev["package_id"], row["test_key"], "test_item", item_id,
            data.get("kind"), data.get("text"),
        )
        if refused:
            return refused
    return {"ok": True}


@router.get("/api/packages/{package_id}/test-stats")
async def get_test_stats(package_id: str, request: Request):
    user = request.state.user
    with db.connect() as c:
        row = c.execute("SELECT * FROM packages WHERE id=?", (package_id,)).fetchone()
        if not row or row["owner"] != user:
            return bad(404, "package", "Không có package này.")
        return {"tests": practice.stats(c, package_id, user)}
