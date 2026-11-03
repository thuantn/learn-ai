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
