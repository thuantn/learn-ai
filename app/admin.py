"""The admin page and its API. Everyone else gets the same 404 as a route that does not exist."""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from . import ai, catalog, db, uploads
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
    return c.execute(
        "SELECT 1 FROM package_lessons WHERE package_id=? AND json_extract(data, '$.content')<>'' LIMIT 1", (package_id,)
    ).fetchone() is not None


@router.get("/admin")
async def admin_page():
    return page("admin.html")


@router.get("/api/admin/overview")
async def overview():
    with db.connect() as c:
        lesson_counts = {r["package_id"]: r["n"] for r in c.execute("SELECT package_id, count(*) n FROM package_lessons GROUP BY package_id")}
        packages = [{
            "id": r["id"], "title": r["title"], "owner": r["owner"], "size_bytes": r["size_bytes"], "version": r["version"],
            "ask_status": r["ask_status"], "updated_at": r["updated_at"], "lessons": lesson_counts.get(r["id"], 0),
        } for r in c.execute(
            "SELECT id, title, owner, size_bytes, version, ask_status, updated_at FROM packages "
            "ORDER BY ask_status IN ('pending', 'approved') DESC, updated_at DESC LIMIT ?", (LIST_LIMIT,))]
        abuse = [dict(r) for r in c.execute(
            """SELECT f.id, f.package_id, p.title, p.owner, f.lesson, f.author, f.body, f.created_at
               FROM feedback f JOIN packages p ON p.id=f.package_id WHERE f.kind='abuse' ORDER BY f.created_at DESC LIMIT ?""", (LIST_LIMIT,))]
        users = [{
            "name": r["name"], "admin": bool(r["is_admin"]), "used": r["used"],
            "quota": r["quota_bytes"] if r["quota_bytes"] is not None else uploads.DEFAULT_QUOTA,
        } for r in c.execute(
            """SELECT u.name, u.is_admin, u.quota_bytes, coalesce(sum(p.size_bytes),0) used
               FROM users u LEFT JOIN packages p ON p.owner=u.name GROUP BY u.name ORDER BY used DESC LIMIT ?""", (LIST_LIMIT,))]
        entries = [dict(r) for r in c.execute("SELECT actor, action, target, detail, at FROM admin_log ORDER BY id DESC LIMIT ?", (LIST_LIMIT,))]
    return {
        "pending": [p for p in packages if p["ask_status"] == "pending"],
        "packages": packages, "abuse": abuse, "users": users, "log": entries,
        "ai": ai.status(),
        "providers": [{"id": k, "label": v["label"], "zdr": v["zdr"], "default_model": v["default_model"]} for k, v in ai.PROVIDERS.items()],
    }


@router.get("/api/admin/packages/{package_id}/review")
async def review(package_id: str):
    with db.connect() as c:
        # The hash is read first: if a new version lands in between, the approval below fails instead of approving unseen text.
        row = c.execute("SELECT title, owner, ask_status, ask_hash FROM packages WHERE id=?", (package_id,)).fetchone()
        if not row:
            return bad(404, "package", "Không có package này.")
        lessons = [json.loads(r["data"]) for r in c.execute("SELECT data FROM package_lessons WHERE package_id=? ORDER BY ord", (package_id,))]
    return {
        "title": row["title"], "author": row["owner"], "ask_status": row["ask_status"], "ask_hash": row["ask_hash"],
        "zdr": ai.status()["zdr"],
        "lessons": [{k: x.get(k) for k in ("title", "summary", "cards", "quiz", "content")} for x in lessons],
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
