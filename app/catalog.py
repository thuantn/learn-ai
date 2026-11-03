"""Package catalog: install, query and remove lesson packages."""
import hashlib
import json
import logging
import os
import pathlib
import re
import secrets
import shutil
import time

from fsrs import Card

from . import contract, db

log = logging.getLogger("learn")
_ID_RE = re.compile(r"^p[0-9a-f]{12}$")


def packages_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("PACKAGES_DIR", "packages")).resolve()


def _new_id(c) -> str:
    while True:
        pid = "p" + secrets.token_hex(6)
        if not c.execute("SELECT 1 FROM packages WHERE id=?", (pid,)).fetchone():
            return pid


def _package_dir(package_id: str, version: int) -> pathlib.Path:
    return packages_dir() / package_id / str(version)


def _dir_versions(package_path: pathlib.Path) -> list[int]:
    if not package_path.is_dir():
        return []
    out = []
    for child in package_path.iterdir():
        if child.is_dir() and child.name.isdigit():
            out.append(int(child.name))
    return out


def _total_size(root: pathlib.Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def _hash_ask(parts) -> str:
    """Stable hash over the AI-readable parts of a package."""
    h = hashlib.sha256()
    for part in parts:
        h.update(json.dumps(part, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def _read_unpacked(unpacked: pathlib.Path):
    package = contract.read_json_file(unpacked / "package.json")
    lessons = []
    ask_parts = []
    for idx, lesson_id in enumerate(package["lessons"]):
        lesson_dir = unpacked / "lessons" / lesson_id
        lesson = contract.read_json_file(lesson_dir / "lesson.json")
        tracks = {}
        for key, track in lesson.get("tracks", {}).items():
            seconds = 0
            audio_path = lesson_dir / "audio" / track["file"]
            try:
                seconds = contract.audio_seconds(audio_path)
            except Exception:
                seconds = 0
            tracks[key] = {"file": track["file"], "label": track["label"], "duration": seconds}
        content_path = lesson_dir / "content.md"
        content = content_path.read_text(encoding="utf-8") if content_path.is_file() else ""
        data = {
            "ord": idx,
            "title": lesson.get("title", ""),
            "summary": lesson.get("summary", []),
            "cards": lesson.get("cards", []),
            "quiz": lesson.get("quiz", []),
            "tracks": tracks,
            "content": content,
        }
        lessons.append((lesson_id, data))
        ask_parts.extend([lesson.get("title", ""), content, lesson.get("summary", []), lesson.get("cards", []), lesson.get("quiz", [])])
    return package, lessons, _hash_ask(ask_parts)


def progress_id(package_id: str, bare_id: str) -> str:
    return f"{package_id}.{bare_id}"


def _has_access(c, user: str, package_id: str) -> bool:
    row = c.execute("SELECT owner FROM packages WHERE id=?", (package_id,)).fetchone()
    if not row:
        return False
    if row["owner"] == user:
        return True
    access = c.execute(
        "SELECT 1 FROM package_access WHERE package_id=? AND user=? AND revoked_at IS NULL",
        (package_id, user),
    ).fetchone()
    return access is not None


def install_version(owner: str, unpacked) -> dict:
    """Installs or updates a package and returns {id, version, created}."""
    unpacked = pathlib.Path(unpacked).resolve()
    package, lessons, ask_hash = _read_unpacked(unpacked)
    slug = package["slug"]
    title = package.get("title", "")
    topic = package.get("topic", "")
    description = package.get("description", "")
    size_bytes = _total_size(unpacked)

    with db.connect() as c:
        existing = c.execute(
            "SELECT id, version FROM packages WHERE owner=? AND slug=?", (owner, slug)
        ).fetchone()
        package_id = existing["id"] if existing else _new_id(c)
        versions = _dir_versions(packages_dir() / package_id)
        if existing:
            versions.append(existing["version"])
        version = max(versions, default=0) + 1

        target = _package_dir(package_id, version)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(str(unpacked), str(target))

        now = time.time()
        try:
            c.execute("BEGIN")
            if existing:
                # The status comes from the row inside this statement: an admin may have decided while the files copied.
                c.execute(
                    """UPDATE packages SET
                        title=?, topic=?, description=?, version=?, size_bytes=?, updated_at=?,
                        ask_status=CASE WHEN ask_hash=? THEN ask_status
                                        WHEN ask_status='approved' THEN 'pending'
                                        WHEN ask_status='rejected' THEN 'none'
                                        ELSE ask_status END,
                        ask_hash=?
                       WHERE id=?""",
                    (title, topic, description, version, size_bytes, now, ask_hash, ask_hash, package_id),
                )
            else:
                c.execute(
                    """INSERT INTO packages
                        (id, owner, slug, title, topic, description, version, size_bytes,
                         ask_status, ask_hash, created_at, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (package_id, owner, slug, title, topic, description, version, size_bytes,
                     "none", ask_hash, now, now),
                )

            c.execute("DELETE FROM package_lessons WHERE package_id=?", (package_id,))
            for lesson_id, data in lessons:
                key = progress_id(package_id, lesson_id)
                c.execute(
                    "INSERT INTO package_lessons(key, package_id, ord, data) VALUES(?,?,?,?)",
                    (key, package_id, data["ord"], json.dumps(data, ensure_ascii=False)),
                )

            if existing:
                _add_new_cards(c, package_id, lessons, now)

            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            shutil.rmtree(target, ignore_errors=True)
            raise

    if existing:
        old_dir = _package_dir(package_id, existing["version"])
        shutil.rmtree(old_dir, ignore_errors=True)

    return {"id": package_id, "version": version, "created": existing is None}


def _add_new_cards(c, package_id: str, lessons, now: float):
    """Adds new bare card ids for users who already started this package.

    Quiz questions become cards only when answered wrong; they must not be
    added automatically on update.
    """
    by_lesson = {}
    for lesson_id, data in lessons:
        key = progress_id(package_id, lesson_id)
        for card in data["cards"]:
            by_lesson[card["id"]] = key
    prefix = progress_id(package_id, "")
    users = {
        r["user"]
        for r in c.execute("SELECT DISTINCT user FROM lesson_progress WHERE substr(lesson,1,14)=?", (prefix,))
    }
    for user in users:
        for bare, lesson_key in by_lesson.items():
            card_id = progress_id(package_id, bare)
            c.execute(
                "INSERT INTO card_state(user, card_id, lesson, due, card_json) VALUES(?,?,?,?,?) ON CONFLICT(user, card_id) DO NOTHING",
                (user, card_id, lesson_key, now, Card().to_json()),
            )


def removed_ids(owner: str, unpacked) -> list[str]:
    """Returns bare ids and whole lessons that exist in the installed package but are missing from unpacked."""
    unpacked = pathlib.Path(unpacked)
    package = contract.read_json_file(unpacked / "package.json")
    slug = package["slug"]
    with db.connect() as c:
        row = c.execute("SELECT id FROM packages WHERE owner=? AND slug=?", (owner, slug)).fetchone()
        if not row:
            return []
        package_id = row["id"]
        existing = {}
        for r in c.execute("SELECT key, data FROM package_lessons WHERE package_id=?", (package_id,)):
            data = json.loads(r["data"])
            existing[r["key"]] = set()
            existing[r["key"]].update(card["id"] for card in data["cards"])
            existing[r["key"]].update(q["id"] for q in data["quiz"])
        new = {}
        for lesson_id in package["lessons"]:
            lesson = contract.read_json_file(unpacked / "lessons" / lesson_id / "lesson.json")
            key = progress_id(package_id, lesson_id)
            new[key] = set()
            new[key].update(card["id"] for card in lesson.get("cards", []))
            new[key].update(q["id"] for q in lesson.get("quiz", []))
        removed = []
        for key in sorted(existing):
            bare = key.split(".", 1)[1]
            if key not in new:
                removed.append(f"lesson:{bare}")
                continue
            for bare_id in sorted(existing[key] - new[key]):
                removed.append(bare_id)
        return removed


def _lesson_dict(package_id: str, key: str, owner: str, ask_status: str, data: dict, user: str) -> dict:
    tracks = {}
    for tkey, track in data["tracks"].items():
        tracks[tkey] = {**track, "url": f"/audio/{key}/{tkey}"}
    return {
        "id": key,
        "doc": key,
        "package_id": package_id,
        "package_title": data.get("package_title", ""),
        "author": owner,
        "mine": user == owner,
        "ord": data["ord"],
        "title": data["title"],
        "summary": data["summary"],
        "cards": data["cards"],
        "quiz": data["quiz"],
        "tracks": tracks,
        "ask_status": ask_status,
        "content": data.get("content", ""),
        "page": f"/lesson/{key}",
    }


def lesson_for(c, user: str, key: str) -> dict | None:
    row = c.execute("SELECT package_id, data FROM package_lessons WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    package_id = row["package_id"]
    if not _has_access(c, user, package_id):
        return None
    package = c.execute("SELECT owner, title, ask_status FROM packages WHERE id=?", (package_id,)).fetchone()
    data = json.loads(row["data"])
    data["package_title"] = package["title"]
    return _lesson_dict(package_id, key, package["owner"], package["ask_status"], data, user)


def lessons_for(c, user: str) -> list[dict]:
    rows = c.execute(
        """SELECT pl.key, pl.package_id, json_remove(pl.data, '$.content') data, p.owner, p.title, p.ask_status
           FROM package_lessons pl
           JOIN packages p ON p.id = pl.package_id
           WHERE p.owner=? OR EXISTS(
               SELECT 1 FROM package_access pa
               WHERE pa.package_id = p.id AND pa.user=? AND pa.revoked_at IS NULL
           )
           ORDER BY p.updated_at DESC, pl.ord""",
        (user, user),
    ).fetchall()
    out = []
    for row in rows:
        data = json.loads(row["data"])
        data["package_title"] = row["title"]
        out.append(_lesson_dict(row["package_id"], row["key"], row["owner"], row["ask_status"], data, user))
    return out


def has_access(c, user: str, package_id: str) -> bool:
    return _has_access(c, user, package_id)


def lesson_dir(c, key: str) -> pathlib.Path | None:
    row = c.execute(
        """SELECT p.id, p.version FROM packages p
           JOIN package_lessons pl ON pl.package_id = p.id
           WHERE pl.key=?""",
        (key,),
    ).fetchone()
    if not row:
        return None
    bare_id = key.split(".", 1)[1]
    return _package_dir(row["id"], row["version"]) / "lessons" / bare_id


def purge_rows(c, package_id: str):
    """Removes all progress rows prefixed with this package id."""
    prefix = progress_id(package_id, "")
    tables = [
        ("card_state", "lesson"),
        ("wrong_card", "lesson"),
        ("review_log", "card_id"),
        ("lesson_progress", "lesson"),
        ("listen_pos", "episode"),
        ("user_doc", "name"),
        ("ask_message", "lesson"),
    ]
    for table, col in tables:
        c.execute(f"DELETE FROM {table} WHERE substr({col},1,14)=?", (prefix,))


def delete_package(package_id: str) -> None:
    with db.connect() as c:
        purge_rows(c, package_id)
        c.execute("DELETE FROM packages WHERE id=?", (package_id,))
    shutil.rmtree(packages_dir() / package_id, ignore_errors=True)


def sweep() -> None:
    """Removes versions older than the one in use. Anything else stays: after a database restore, a dir unknown to the
    database or newer than its version may be the only copy."""
    root = packages_dir()
    if not root.is_dir():
        return
    with db.connect() as c:
        current = {
            r["id"]: r["version"]
            for r in c.execute("SELECT id, version FROM packages")
        }
    for child in root.iterdir():
        if not _ID_RE.match(child.name):
            continue
        if child.name not in current:
            log.warning("package dir not in database, kept: %s", child.name)
            continue
        keep = current[child.name]
        for sub in child.iterdir():
            if sub.is_dir() and sub.name.isdigit() and int(sub.name) < keep:
                shutil.rmtree(sub, ignore_errors=True)
