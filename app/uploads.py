"""Two-step package upload: stage and check a zip, install it once the author confirms."""
import asyncio
import pathlib
import secrets
import shutil
import time

from . import bundle, catalog, contract, db

STAGE_TTL = 3600
DEFAULT_QUOTA = 1024 ** 3
MAX_PACKAGES = 30
MIN_FREE_BYTES = 2 * 1024 ** 3
MAX_ACTIVE_TOTAL = 4
CHUNK_TIMEOUT = 60
TOTAL_TIMEOUT = 1800
MAX_PROBLEMS = 50
PART_SIZE = 2 * 1024 * 1024
MAX_PART_SESSIONS = 8

# One worker, so plain dicts are enough. Everything here is lost on restart, and startup clears .staging.
stages = {}
active = {}
part_sessions = {}


class TooLarge(Exception):
    pass


def staging_dir() -> pathlib.Path:
    path = catalog.packages_dir() / ".staging"
    path.mkdir(parents=True, exist_ok=True)
    return path


def clear_staging() -> None:
    shutil.rmtree(catalog.packages_dir() / ".staging", ignore_errors=True)
    staging_dir()
    part_sessions.clear()


def begin(user: str) -> bool:
    if active.get(user) or sum(active.values()) >= MAX_ACTIVE_TOTAL:
        return False
    active[user] = 1
    return True


def end(user: str) -> None:
    active.pop(user, None)


def disk_low() -> bool:
    return shutil.disk_usage(staging_dir()).free < MIN_FREE_BYTES


async def receive(stream, path, chunk_timeout=None, total_timeout=None, limit=None, offset=None) -> int:
    """Writes the request body to path, counting bytes because Content-Length can lie."""
    chunk_timeout = CHUNK_TIMEOUT if chunk_timeout is None else chunk_timeout
    deadline = time.monotonic() + (TOTAL_TIMEOUT if total_timeout is None else total_timeout)
    max_bytes = bundle.MAX_ZIP if limit is None else limit
    size = 0
    chunks = stream.__aiter__()
    mode = "r+b" if offset is not None else "wb"
    with open(path, mode) as f:
        if offset is not None:
            f.seek(offset)
        while True:
            wait = min(chunk_timeout, deadline - time.monotonic())
            try:
                chunk = await asyncio.wait_for(chunks.__anext__(), wait)
            except StopAsyncIteration:
                return size
            size += len(chunk)
            if size > max_bytes:
                raise TooLarge
            f.write(chunk)


def _public_problems(problems, roots):
    """The last stop before the browser: no server path may leave in a path or a message."""
    def clean(text):
        for root in roots:
            text = text.replace(str(root) + "\\", "").replace(str(root) + "/", "").replace(str(root), "")
        return text
    return [{"path": clean(p.path), "message": clean(p.message)} for p in problems[:MAX_PROBLEMS]]


def _tree_size(root) -> int:
    return sum(p.stat().st_size for p in pathlib.Path(root).rglob("*") if p.is_file())


def over_quota(owner: str, slug: str, size: int) -> bool:
    with db.connect() as c:
        row = c.execute("SELECT quota_bytes FROM users WHERE name=?", (owner,)).fetchone()
        used = c.execute(
            "SELECT coalesce(sum(size_bytes),0) n FROM packages WHERE owner=? AND slug<>?", (owner, slug)
        ).fetchone()["n"]
    limit = row["quota_bytes"] if row and row["quota_bytes"] is not None else DEFAULT_QUOTA
    return used + size > limit


def too_many(owner: str, slug: str) -> bool:
    with db.connect() as c:
        return c.execute("SELECT count(*) n FROM packages WHERE owner=? AND slug<>?", (owner, slug)).fetchone()["n"] >= MAX_PACKAGES


def prepare(path, owner: str, kind="zip") -> dict:
    """Unpacks and checks a zip or single test json. On success the result has "dir"; otherwise "code" and "problems"."""
    dest = staging_dir() / secrets.token_hex(12)
    roots = (dest, staging_dir(), catalog.packages_dir())
    if kind == "json":
        problems = contract.unpack_test_file(path, dest)
    else:
        problems = bundle.safe_extract(path, dest)
        if not problems:
            problems = contract.check_package(dest)
    if contract.errors(problems):
        shutil.rmtree(dest, ignore_errors=True)
        return {"code": "invalid", "problems": _public_problems(contract.errors(problems), roots)}
    package = contract.read_json_file(dest / "package.json")
    size = _tree_size(dest)
    if over_quota(owner, package["slug"], size):
        shutil.rmtree(dest, ignore_errors=True)
        return {"code": "quota", "problems": [{"path": "", "message": "Vượt hạn mức dung lượng của tài khoản."}]}
    if too_many(owner, package["slug"]):
        shutil.rmtree(dest, ignore_errors=True)
        return {"code": "quota", "problems": [{"path": "", "message": f"Mỗi tài khoản có tối đa {MAX_PACKAGES} package."}]}
    with db.connect() as c:
        is_update = c.execute("SELECT 1 FROM packages WHERE owner=? AND slug=?", (owner, package["slug"])).fetchone() is not None
    lessons = [contract.read_json_file(dest / "lessons" / x / "lesson.json")["title"] for x in package.get("lessons", [])]
    tests = [contract.read_test_file(dest / "tests" / f"{x}.json")["title"] for x in package.get("tests", [])]
    return {
        "dir": dest,
        "title": package["title"],
        "slug": package["slug"],
        "lessons": lessons,
        "tests": tests,
        "is_update": is_update,
        "removed": catalog.removed_ids(owner, dest),
        "warnings": _public_problems([p for p in problems if p.severity != "error"], roots),
        "size": size,
    }


def drop(upload_id: str) -> None:
    stage = stages.pop(upload_id, None)
    if stage:
        shutil.rmtree(stage["dir"], ignore_errors=True)


def drop_parts_session(session_id: str) -> None:
    ps = part_sessions.pop(session_id, None)
    if ps:
        path = ps.get("path")
        if path:
            pathlib.Path(path).unlink(missing_ok=True)


def expire(now=None) -> None:
    now = time.time() if now is None else now
    for upload_id, stage in list(stages.items()):
        if now - stage["created"] > STAGE_TTL and not stage["committing"]:
            drop(upload_id)
    for session_id, ps in list(part_sessions.items()):
        touched = ps.get("touched", ps.get("created", 0))
        if now - touched > STAGE_TTL:
            drop_parts_session(session_id)


def get_parts_session(session_id: str, user: str) -> dict | None:
    expire()
    ps = part_sessions.get(session_id)
    return ps if ps and ps["user"] == user else None


def keep(user: str, info: dict) -> str:
    """Stores a checked upload. Each person has one; a newer one replaces the older."""
    expire()
    for upload_id, stage in list(stages.items()):
        if stage["user"] == user and not stage["committing"]:
            drop(upload_id)
    upload_id = secrets.token_urlsafe(18)
    stages[upload_id] = {"user": user, "dir": info["dir"], "slug": info["slug"], "size": info["size"], "created": time.time(), "committing": False}
    return upload_id


def get(upload_id: str, user: str) -> dict | None:
    expire()
    stage = stages.get(upload_id)
    return stage if stage and stage["user"] == user else None
