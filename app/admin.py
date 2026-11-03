"""The admin page and its API. Everyone else gets the same 404 as a route that does not exist."""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from . import accounts, ai, auth, catalog, db, uploads
from .web_util import bad, page, read_json

log = logging.getLogger("learn")
LIST_LIMIT = 200
REASON_MAX = 500


def is_admin(user) -> bool:
    with db.connect() as c:
        row = c.execute("SELECT is_admin FROM users WHERE name=?", (user,)).fetchone()
    return bool(row and row["is_admin"])


async def require_admin(request: Request):
    if not is_admin(request.state.user):
        raise HTTPException(404)


router = APIRouter(dependencies=[Depends(require_admin)])


def has_content(c, package_id) -> bool:
    return (
        c.execute(
            "SELECT 1 FROM package_lessons WHERE package_id=? AND json_extract(data, '$.content')<>'' LIMIT 1", (package_id,)
        ).fetchone() is not None
        or c.execute("SELECT 1 FROM package_tests WHERE package_id=? LIMIT 1", (package_id,)).fetchone() is not None
    )


@router.get("/admin")
async def admin_page():
    return page("admin.html")


@router.get("/api/admin/overview")
async def overview():
    with db.connect() as c:
        lesson_counts = {r["package_id"]: r["n"] for r in c.execute("SELECT package_id, count(*) n FROM package_lessons GROUP BY package_id")}
        test_counts = {r["package_id"]: r["n"] for r in c.execute("SELECT package_id, count(*) n FROM package_tests GROUP BY package_id")}
        session_counts = {r["user"]: r["n"] for r in c.execute("SELECT user, count(*) n FROM sessions GROUP BY user")}
        packages = [{
            "id": r["id"], "title": r["title"], "owner": r["owner"], "size_bytes": r["size_bytes"], "version": r["version"],
            "ask_status": r["ask_status"], "updated_at": r["updated_at"], "lessons": lesson_counts.get(r["id"], 0),
            "tests": test_counts.get(r["id"], 0),
        } for r in c.execute(
            "SELECT id, title, owner, size_bytes, version, ask_status, updated_at FROM packages "
            "ORDER BY ask_status IN ('pending', 'approved') DESC, updated_at DESC LIMIT ?", (LIST_LIMIT,))]
        abuse = [dict(r) for r in c.execute(
            """SELECT f.id, f.package_id, p.title, p.owner, f.lesson, f.author, f.body, f.created_at
               FROM feedback f JOIN packages p ON p.id=f.package_id WHERE f.kind='abuse' ORDER BY f.created_at DESC LIMIT ?""", (LIST_LIMIT,))]
        users = [{
            "name": r["name"], "admin": bool(r["is_admin"]), "used": r["used"],
            "quota": r["quota_bytes"] if r["quota_bytes"] is not None else uploads.DEFAULT_QUOTA,
            "must_change": bool(r["must_change"]), "created_at": r["created_at"],
            "sessions": session_counts.get(r["name"], 0),
        } for r in c.execute(
            """SELECT u.name, u.is_admin, u.quota_bytes, u.must_change, u.created_at, coalesce(sum(p.size_bytes),0) used
               FROM users u LEFT JOIN packages p ON p.owner=u.name GROUP BY u.name ORDER BY used DESC LIMIT ?""", (LIST_LIMIT,))]
        entries = [dict(r) for r in c.execute("SELECT actor, action, target, detail, at FROM admin_log ORDER BY id DESC LIMIT ?", (LIST_LIMIT,))]
    return {
        "pending": [p for p in packages if p["ask_status"] == "pending"],
        "packages": packages, "abuse": abuse, "users": users, "log": entries,
        "ai": ai.status(),
        "providers": [{"id": k, "label": v["label"], "zdr": v["zdr"], "default_model": v["default_model"]} for k, v in ai.PROVIDERS.items()],
    }


def _change_and_log(change, name, actor, action):
    with db.connect() as c:
        password = change(c, name)
        db.admin_log(c, actor, action, name)
    return password


async def _hashing(change, name, actor, action):
    # Argon2 is slow and memory hungry: off the event loop, under the same limit as login.
    async with auth.HASHING:
        return await asyncio.to_thread(_change_and_log, change, name, actor, action)


@router.post("/api/admin/users")
async def add_user(request: Request):
    data = await read_json(request) or {}
    raw_name = data.get("name")
    if not isinstance(raw_name, str):
        return bad(400, "name_bad", "Email không hợp lệ.")
    name = raw_name.strip().lower()
    if len(name) > 254 or not accounts.NAME_RE.match(name):
        return bad(400, "name_bad", "Email không hợp lệ.")
    try:
        password = await _hashing(accounts.create, name, request.state.user, "user_add")
    except ValueError:
        return bad(409, "exists", "Tài khoản này đã tồn tại.")
    return JSONResponse({"name": name, "password": password}, headers={"Cache-Control": "no-store"})


@router.post("/api/admin/users/{name}/reset-password")
async def reset_user_password(name: str, request: Request):
    name = name.strip().lower()
    if name == request.state.user:
        return bad(409, "self", "Dùng chức năng Đổi mật khẩu để tự đổi mật khẩu của mình.")
    try:
        password = await _hashing(accounts.reset, name, request.state.user, "user_reset")
    except ValueError:
        return bad(404, "user", "Không có tài khoản này.")
    return JSONResponse({"name": name, "password": password}, headers={"Cache-Control": "no-store"})


@router.post("/api/admin/users/{name}/end-sessions")
async def end_user_sessions(name: str, request: Request):
    name = name.strip().lower()
    with db.connect() as c:
        if not c.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
            return bad(404, "user", "Không có tài khoản này.")
        c.execute("DELETE FROM sessions WHERE user=?", (name,))
        db.admin_log(c, request.state.user, "user_end_sessions", name)
    return {"ok": True}


@router.put("/api/admin/users/{name}")
async def update_user(name: str, request: Request):
    name = name.strip().lower()
    data = await read_json(request) or {}
    has_admin = "admin" in data
    has_quota = "quota_gb" in data
    if not has_admin and not has_quota:
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    admin_val = data.get("admin")
    if has_admin and not isinstance(admin_val, bool):
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    quota_val = data.get("quota_gb")
    if has_quota and (isinstance(quota_val, bool) or not isinstance(quota_val, int) or not (1 <= quota_val <= 100)):
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    if has_admin and name == request.state.user and not admin_val:
        return bad(409, "self", "Không thể tự gỡ quyền admin của chính mình.")
    with db.connect() as c:
        if not c.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
            return bad(404, "user", "Không có tài khoản này.")
        if has_admin:
            c.execute("UPDATE users SET is_admin=? WHERE name=?", (int(admin_val), name))
            db.admin_log(c, request.state.user, "set_admin", name, "on" if admin_val else "off")
        if has_quota:
            c.execute("UPDATE users SET quota_bytes=? WHERE name=?", (quota_val * 1024 ** 3, name))
            db.admin_log(c, request.state.user, "set_quota", name, f"{quota_val} GB")
    return {"ok": True}


@router.delete("/api/admin/users/{name}")
async def remove_user(name: str, request: Request):
    name = name.strip().lower()
    data = await read_json(request) or {}
    confirm = data.get("confirm")
    if confirm != name:
        return bad(400, "confirm", "Xác nhận tên tài khoản không đúng.")
    if name == request.state.user:
        return bad(409, "self", "Không thể tự xóa tài khoản của chính mình.")
    with db.connect() as c:
        if not c.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
            return bad(404, "user", "Không có tài khoản này.")
        db.admin_log(c, request.state.user, "user_remove", name)
    await asyncio.to_thread(accounts.remove, name)
    return {"ok": True}


@router.get("/api/admin/packages/{package_id}/review")
async def review(package_id: str):
    with db.connect() as c:
        # The hash is read first: if a new version lands in between, the approval below fails instead of approving unseen text.
        row = c.execute("SELECT title, owner, ask_status, ask_hash FROM packages WHERE id=?", (package_id,)).fetchone()
        if not row:
            return bad(404, "package", "Không có package này.")
        lessons = [json.loads(r["data"]) for r in c.execute("SELECT data FROM package_lessons WHERE package_id=? ORDER BY ord", (package_id,))]
        tests = [
            json.loads(r["data"])
            for r in c.execute(
                """SELECT tr.data FROM package_tests pt
                   JOIN test_revision tr ON tr.id = pt.revision_id
                   WHERE pt.package_id=? ORDER BY pt.ord""",
                (package_id,),
            )
        ]
    return {
        "title": row["title"], "author": row["owner"], "ask_status": row["ask_status"], "ask_hash": row["ask_hash"],
        "zdr": ai.status()["zdr"],
        "lessons": [{k: x.get(k) for k in ("title", "summary", "cards", "quiz", "content")} for x in lessons],
        "tests": tests,
    }


@router.post("/api/admin/packages/{package_id}/ask")
async def decide_ask(package_id: str, request: Request):
    data = await read_json(request) or {}
    decision = data.get("decision")
    with db.connect() as c:
        if not c.execute("SELECT 1 FROM packages WHERE id=?", (package_id,)).fetchone():
            return bad(404, "package", "Không có package này.")
        if decision == "approve":
            if not has_content(c, package_id):
                return bad(400, "no_content", "Package không có nội dung cho AI đọc.")
            done = c.execute(
                "UPDATE packages SET ask_status='approved' WHERE id=? AND ask_status='pending' AND ask_hash=?",
                (package_id, str(data.get("ask_hash", ""))),
            ).rowcount
            if not done:
                return bad(409, "changed", "Nội dung đã thay đổi hoặc không còn chờ duyệt. Tải lại rồi đọc lại.")
        elif decision in ("reject", "off"):
            c.execute("UPDATE packages SET ask_status='rejected' WHERE id=?", (package_id,))
        else:
            return bad(400, "input", "Dữ liệu không hợp lệ.")
        db.admin_log(c, request.state.user, "ask_" + decision, package_id)
    return {"ok": True}


@router.delete("/api/admin/packages/{package_id}")
async def remove_package(package_id: str, request: Request):
    data = await read_json(request) or {}
    reason = data.get("reason")
    if not isinstance(reason, str) or not 0 < len(reason.strip()) <= REASON_MAX:
        return bad(400, "input", "Cần ghi lý do gỡ.")
    with db.connect() as c:
        row = c.execute("SELECT title, owner FROM packages WHERE id=?", (package_id,)).fetchone()
        if not row:
            return bad(404, "package", "Không có package này.")
        db.admin_log(c, request.state.user, "package_remove", package_id, f"{row['title']} | {row['owner']} | {reason.strip()}")
    await asyncio.to_thread(catalog.delete_package, package_id)
    return {"ok": True}


@router.put("/api/admin/ai")
async def save_ai(request: Request):
    data = await read_json(request) or {}
    provider, model, key = data.get("provider"), data.get("model", ""), data.get("key")
    if not isinstance(provider, str) or not isinstance(model, str) or not (key is None or isinstance(key, str)):
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    try:
        ai.save(provider, model, key, request.state.user)
    except ValueError as e:
        return bad(400, str(e), "Không lưu được.")
    return ai.status()


@router.post("/api/admin/ai/test")
async def test_ai():
    return await asyncio.to_thread(ai.test)
