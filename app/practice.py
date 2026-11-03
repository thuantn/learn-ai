"""Practice test attempts, grading, clock and DTO gating."""
import json
import random
import secrets
import sqlite3
import time

from . import ai, catalog

clock = time.time
GRACE = 5
_rng = random.SystemRandom()


class Refused(Exception):
    def __init__(self, code: str, status: int, message: str):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


def grade(item: dict, chosen: list[str]) -> bool:
    return len(chosen) == len(item["correct"]) and set(chosen) == set(item["correct"])


def _percent(score: int, total: int) -> int:
    return round(score * 100 / total) if total else 0


def _passed(score: int, total: int, pass_percent: int) -> bool:
    # On the exact counts: 140/180 is 77.8%, which rounds to 78 but does not reach a 78% bar.
    return total > 0 and score * 100 >= pass_percent * total


def revealed(row, answer_row) -> bool:
    if row["mode"] in ("exam", "practice") and row["submitted_at"] is not None:
        return True
    if row["mode"] in ("practice", "review") and answer_row is not None and answer_row["correct"] is not None:
        return True
    return False


def public_item(item: dict, order, answer_row, reveal: bool) -> dict:
    by_id = {o["id"]: o for o in item["options"]}
    ordered = [by_id[oid] for oid in order]
    chosen = json.loads(answer_row["chosen"]) if answer_row else []
    flagged = bool(answer_row["flagged"]) if answer_row else False
    checked = bool(answer_row is not None and answer_row["correct"] is not None)
    if reveal:
        options = [{"id": o["id"], "text": o["text"], "why": o.get("why", "")} for o in ordered]
    else:
        options = [{"id": o["id"], "text": o["text"]} for o in ordered]
    out = {
        "id": item["id"],
        "domain": item["domain"],
        "type": item["type"],
        "required": len(item["correct"]),
        "question": item["question"],
        "options": options,
        "chosen": chosen,
        "flagged": flagged,
        "checked": checked,
    }
    if reveal:
        out["correct"] = list(item["correct"])
        out["is_correct"] = bool(answer_row["correct"]) if checked else grade(item, chosen)
        out["explanation"] = item["explanation"]
        out["best_practice"] = item.get("best_practice", "")
        out["docs"] = list(item.get("docs", []))
    return out


def item_in(c, row, item_id: str) -> dict | None:
    layout = json.loads(row["layout"])
    if not any(entry["id"] == item_id for entry in layout):
        return None
    data = catalog.revision_data(c, row["revision_id"])
    if not data:
        return None
    for item in data["items"]:
        if item["id"] == item_id:
            return item
    return None


def _record_first_answer(c, user: str, package_id: str, test_key: str, item_id: str, ahash: str, chosen: list[str], is_correct: bool, at: float):
    if not chosen:
        return
    c.execute(
        """INSERT INTO test_first_answer(user, package_id, test_key, item, answer_hash, chosen, correct, at)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(user, test_key, item, answer_hash) DO NOTHING""",
        (user, package_id, test_key, item_id, ahash, json.dumps(chosen), int(is_correct), at),
    )


def _finalize(c, row, data: dict, at: float) -> None:
    if row["mode"] == "review":
        c.execute("UPDATE test_attempt SET submitted_at=? WHERE id=?", (at, row["id"]))
        return
    layout = json.loads(row["layout"])
    items_by_id = {x["id"]: x for x in data["items"]}
    answers = {r["item"]: r for r in c.execute("SELECT * FROM test_answer WHERE attempt=?", (row["id"],)).fetchall()}
    pkg_id = c.execute("SELECT package_id FROM test_revision WHERE id=?", (row["revision_id"],)).fetchone()["package_id"]
    score = 0
    for entry in layout:
        item = items_by_id.get(entry["id"])
        if not item:
            continue
        ans = answers.get(entry["id"])
        if ans is not None and ans["correct"] is not None:
            if ans["correct"]:
                score += 1
            continue
        if ans is None:
            continue
        chosen = json.loads(ans["chosen"])
        is_correct = grade(item, chosen)
        ahash = catalog.answer_hash(item)
        c.execute(
            "UPDATE test_answer SET answer_hash=?, correct=?, graded_at=? WHERE attempt=? AND item=?",
            (ahash, int(is_correct), at, row["id"], entry["id"]),
        )
        if is_correct:
            score += 1
        if row["mode"] == "exam" and chosen:
            _record_first_answer(c, row["user"], pkg_id, row["test_key"], entry["id"], ahash, chosen, is_correct, at)
    c.execute(
        "UPDATE test_attempt SET submitted_at=?, score=?, total=? WHERE id=?",
        (at, score, len(layout), row["id"]),
    )


def _maybe_expire(c, row) -> sqlite3.Row:
    if row["mode"] != "exam" or row["submitted_at"] is not None or row["paused_at"] is not None:
        return row
    data = catalog.revision_data(c, row["revision_id"])
    if not data:
        return row
    limit = (data.get("time_limit_minutes") or 0) * 60
    if limit > 0 and clock() - row["started_at"] - row["paused_total"] > limit + GRACE:
        deadline = row["started_at"] + row["paused_total"] + limit
        _finalize(c, row, data, deadline)
        c.commit()
        row = c.execute("SELECT * FROM test_attempt WHERE id=?", (row["id"],)).fetchone()
    return row


def _finalize_expired_for(c, user: str, test_key: str | None = None) -> None:
    if test_key:
        rows = c.execute(
            "SELECT * FROM test_attempt WHERE user=? AND test_key=? AND mode='exam' AND submitted_at IS NULL AND paused_at IS NULL",
            (user, test_key),
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT * FROM test_attempt WHERE user=? AND mode='exam' AND submitted_at IS NULL AND paused_at IS NULL",
            (user,),
        ).fetchall()
    for row in rows:
        _maybe_expire(c, row)


def load(c, user: str, attempt_id: str) -> sqlite3.Row | None:
    row = c.execute("SELECT * FROM test_attempt WHERE id=? AND user=?", (attempt_id, user)).fetchone()
    if not row:
        return None
    rev = c.execute("SELECT package_id FROM test_revision WHERE id=?", (row["revision_id"],)).fetchone()
    if not rev or not catalog.has_access(c, user, rev["package_id"]):
        return None
    return _maybe_expire(c, row)


def _domain_breakdown(layout: list[dict], items_by_id: dict, answers: dict) -> list[dict]:
    groups = {}
    for entry in layout:
        item = items_by_id.get(entry["id"])
        if not item:
            continue
        raw = (item.get("domain") or "").strip() or "Khác"
        key = raw.casefold()
        if key not in groups:
            groups[key] = {"domain": raw, "correct": 0, "total": 0}
        elif groups[key]["domain"].islower() and not raw.islower():
            groups[key]["domain"] = raw
        groups[key]["total"] += 1
        ans = answers.get(entry["id"])
        if ans is not None and ans["correct"]:
            groups[key]["correct"] += 1
    out = []
    for g in groups.values():
        g["percent"] = round(g["correct"] * 100 / g["total"]) if g["total"] else 0
        out.append(g)
    out.sort(key=lambda x: (x["percent"], x["domain"].casefold()))
    return out


def view(c, user: str, row) -> dict | None:
    rev = c.execute(
        "SELECT tr.package_id, tr.data, p.ask_status FROM test_revision tr JOIN packages p ON p.id = tr.package_id WHERE tr.id=?",
        (row["revision_id"],),
    ).fetchone()
    if not rev or not catalog.has_access(c, user, rev["package_id"]):
        return None
    data = json.loads(rev["data"])
    if row["submitted_at"] is not None:
        status = "submitted"
    elif row["paused_at"] is not None:
        status = "paused"
    else:
        status = "open"
    limit = (data.get("time_limit_minutes") or 0) * 60 if row["mode"] == "exam" else 0
    end = row["paused_at"] or row["submitted_at"] or clock()
    raw_elapsed = max(0.0, end - row["started_at"] - row["paused_total"])
    elapsed = round(raw_elapsed)
    remaining = max(0, round(limit - raw_elapsed)) if limit > 0 else None

    layout = json.loads(row["layout"])
    items_by_id = {x["id"]: x for x in data["items"]}
    answers = {r["item"]: r for r in c.execute("SELECT * FROM test_answer WHERE attempt=?", (row["id"],)).fetchall()}

    if status == "paused":
        items = []
    else:
        items = [
            public_item(items_by_id[e["id"]], e["options"], answers.get(e["id"]), revealed(row, answers.get(e["id"])))
            for e in layout
            if e["id"] in items_by_id
        ]

    result = None
    if row["submitted_at"] is not None and row["mode"] in ("exam", "practice"):
        score = row["score"] or 0
        total = row["total"] or 0
        percent = _percent(score, total)
        pass_percent = data.get("pass_percent", 70)
        result = {
            "score": score,
            "total": total,
            "percent": percent,
            "passed": _passed(score, total, pass_percent),
            "pass_percent": pass_percent,
            "duration_seconds": elapsed,
            "by_domain": _domain_breakdown(layout, items_by_id, answers),
        }

    return {
        "id": row["id"],
        "test_key": row["test_key"],
        "title": data["title"],
        "lang": data.get("lang", "vi"),
        "mode": row["mode"],
        "status": status,
        "time_limit_seconds": limit,
        "elapsed": elapsed,
        "remaining": remaining,
        "pause_count": row["pause_count"],
        "paused_seconds": round(row["paused_total"]),
        "ask": bool(ai.current() is not None and rev["ask_status"] == "approved"),
        "items": items,
        "result": result,
    }


def _make_layout(items: list[dict]) -> list[dict]:
    shuffled = list(items)
    _rng.shuffle(shuffled)
    layout = []
    for item in shuffled:
        opts = [o["id"] for o in item["options"]]
        if item.get("shuffle", True):
            _rng.shuffle(opts)
        layout.append({"id": item["id"], "options": opts})
    return layout


def start(c, user: str, key: str, mode: str, restart: bool = False) -> dict | None:
    if mode not in ("exam", "practice", "review"):
        raise Refused("mode", 400, "Chế độ không hợp lệ.")
    trow = catalog.test_row(c, user, key)
    if not trow:
        return None
    _finalize_expired_for(c, user, key)
    existing = c.execute(
        "SELECT * FROM test_attempt WHERE user=? AND test_key=? AND mode=? AND submitted_at IS NULL",
        (user, key, mode),
    ).fetchone()
    if existing and not restart:
        return view(c, user, existing)
    if existing and restart:
        c.execute("DELETE FROM test_attempt WHERE id=?", (existing["id"],))
    data = catalog.revision_data(c, trow["revision_id"])
    layout = _make_layout(data["items"])
    attempt_id = "a" + secrets.token_hex(12)
    now = clock()
    try:
        c.execute(
            """INSERT INTO test_attempt(id, user, test_key, revision_id, mode, layout, started_at)
               VALUES(?,?,?,?,?,?,?)""",
            (attempt_id, user, key, trow["revision_id"], mode, json.dumps(layout), now),
        )
    except sqlite3.IntegrityError:
        row = c.execute(
            "SELECT * FROM test_attempt WHERE user=? AND test_key=? AND mode=? AND submitted_at IS NULL",
            (user, key, mode),
        ).fetchone()
        return view(c, user, row)
    row = c.execute("SELECT * FROM test_attempt WHERE id=?", (attempt_id,)).fetchone()
    return view(c, user, row)


def _validate_chosen(item: dict, chosen) -> list[str]:
    if not isinstance(chosen, list) or not all(isinstance(x, str) for x in chosen):
        raise Refused("input", 400, "Lựa chọn không hợp lệ.")
    if len(chosen) != len(set(chosen)):
        raise Refused("input", 400, "Lựa chọn không hợp lệ.")
    valid_ids = {o["id"] for o in item["options"]}
    if not all(x in valid_ids for x in chosen):
        raise Refused("input", 400, "Lựa chọn không hợp lệ.")
    return chosen


def save(c, row, item_id: str, chosen=None, flagged=None) -> None:
    if row["submitted_at"] is not None:
        raise Refused("submitted", 409, "Lượt làm đã nộp.")
    if row["paused_at"] is not None:
        raise Refused("paused", 409, "Lượt làm đang tạm dừng.")
    item = item_in(c, row, item_id)
    if not item:
        raise Refused("item", 404, "Không có câu hỏi này.")
    if chosen is None and flagged is None:
        raise Refused("input", 400, "Dữ liệu không hợp lệ.")
    if flagged is not None and not isinstance(flagged, bool):
        raise Refused("input", 400, "Dữ liệu không hợp lệ.")
    if chosen is not None:
        _validate_chosen(item, chosen)
        max_choices = 1 if item["type"] == "single" else len(item["correct"])
        if len(chosen) > max_choices:
            raise Refused("input", 400, "Chọn quá số lượng cho phép.")
        ans = c.execute("SELECT correct FROM test_answer WHERE attempt=? AND item=?", (row["id"], item_id)).fetchone()
        if ans is not None and ans["correct"] is not None:
            raise Refused("checked", 409, "Câu này đã kiểm tra.")

    if chosen is not None and flagged is not None:
        c.execute(
            """INSERT INTO test_answer(attempt, item, chosen, flagged) VALUES(?,?,?,?)
               ON CONFLICT(attempt, item) DO UPDATE SET chosen=excluded.chosen, flagged=excluded.flagged""",
            (row["id"], item_id, json.dumps(chosen), int(flagged)),
        )
    elif chosen is not None:
        c.execute(
            """INSERT INTO test_answer(attempt, item, chosen) VALUES(?,?,?)
               ON CONFLICT(attempt, item) DO UPDATE SET chosen=excluded.chosen""",
            (row["id"], item_id, json.dumps(chosen)),
        )
    else:
        c.execute(
            """INSERT INTO test_answer(attempt, item, flagged) VALUES(?,?,?)
               ON CONFLICT(attempt, item) DO UPDATE SET flagged=excluded.flagged""",
            (row["id"], item_id, int(flagged)),
        )


def check(c, row, item_id: str, chosen) -> dict:
    if row["submitted_at"] is not None:
        raise Refused("submitted", 409, "Lượt làm đã nộp.")
    if row["paused_at"] is not None:
        raise Refused("paused", 409, "Lượt làm đang tạm dừng.")
    item = item_in(c, row, item_id)
    if not item:
        raise Refused("item", 404, "Không có câu hỏi này.")
    if row["mode"] not in ("practice", "review"):
        raise Refused("mode", 400, "Chế độ Thi thử không kiểm tra từng câu.")
    ans = c.execute("SELECT * FROM test_answer WHERE attempt=? AND item=?", (row["id"], item_id)).fetchone()
    if ans is not None and ans["correct"] is not None:
        raise Refused("checked", 409, "Câu này đã kiểm tra.")
    _validate_chosen(item, chosen)
    required = len(item["correct"])
    if len(chosen) != required:
        raise Refused("count", 400, f"Cần chọn đủ {required} đáp án.")

    now = clock()
    is_correct = grade(item, chosen)
    ahash = catalog.answer_hash(item)
    c.execute(
        """INSERT INTO test_answer(attempt, item, chosen, answer_hash, correct, graded_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(attempt, item) DO UPDATE SET
             chosen=excluded.chosen,
             answer_hash=excluded.answer_hash,
             correct=excluded.correct,
             graded_at=excluded.graded_at""",
        (row["id"], item_id, json.dumps(chosen), ahash, int(is_correct), now),
    )
    if row["mode"] != "review" and chosen:
        pkg_id = c.execute("SELECT package_id FROM test_revision WHERE id=?", (row["revision_id"],)).fetchone()["package_id"]
        _record_first_answer(c, row["user"], pkg_id, row["test_key"], item_id, ahash, chosen, is_correct, now)

    layout = json.loads(row["layout"])
    order = next((e["options"] for e in layout if e["id"] == item_id), None)
    ans = c.execute("SELECT * FROM test_answer WHERE attempt=? AND item=?", (row["id"], item_id)).fetchone()
    return public_item(item, order, ans, True)


def pause(c, row) -> dict:
    if row["submitted_at"] is not None:
        raise Refused("submitted", 409, "Lượt làm đã nộp.")
    if row["paused_at"] is None:
        c.execute("UPDATE test_attempt SET paused_at=?, pause_count=pause_count+1 WHERE id=?", (clock(), row["id"]))
        row = c.execute("SELECT * FROM test_attempt WHERE id=?", (row["id"],)).fetchone()
    return view(c, row["user"], row)


def resume(c, row) -> dict:
    if row["submitted_at"] is not None:
        raise Refused("submitted", 409, "Lượt làm đã nộp.")
    if row["paused_at"] is not None:
        added = max(0.0, clock() - row["paused_at"])
        c.execute("UPDATE test_attempt SET paused_total=paused_total+?, paused_at=NULL WHERE id=?", (added, row["id"]))
        row = c.execute("SELECT * FROM test_attempt WHERE id=?", (row["id"],)).fetchone()
    return view(c, row["user"], row)


def submit(c, row) -> dict:
    if row["submitted_at"] is not None:
        raise Refused("submitted", 409, "Lượt làm đã nộp.")
    if row["paused_at"] is not None:
        raise Refused("paused", 409, "Lượt làm đang tạm dừng.")
    data = catalog.revision_data(c, row["revision_id"])
    _finalize(c, row, data, clock())
    row = c.execute("SELECT * FROM test_attempt WHERE id=?", (row["id"],)).fetchone()
    return view(c, row["user"], row)


def discard(c, row) -> None:
    if row["submitted_at"] is not None:
        raise Refused("submitted", 409, "Lượt làm đã nộp.")
    c.execute("DELETE FROM test_attempt WHERE id=?", (row["id"],))


def _summary_from_row(c, user: str, trow, ai_on: bool) -> dict:
    key = trow["key"]
    open_map = {"exam": None, "practice": None, "review": None}
    for r in c.execute(
        "SELECT id, mode FROM test_attempt WHERE user=? AND test_key=? AND submitted_at IS NULL",
        (user, key),
    ):
        open_map[r["mode"]] = r["id"]
    best = None
    for r in c.execute(
        "SELECT score, total FROM test_attempt WHERE user=? AND test_key=? AND submitted_at IS NOT NULL AND mode IN ('exam', 'practice')",
        (user, key),
    ):
        pct = _percent(r["score"] or 0, r["total"] or 0)
        if best is None or pct > best:
            best = pct
    pool = c.execute("SELECT count(*) n FROM test_pool WHERE user=? AND test_key=?", (user, key)).fetchone()["n"]
    return {
        "key": key,
        "package_id": trow["package_id"],
        "package_title": trow["package_title"],
        "title": trow["title"],
        "description": trow["description"],
        "items": trow["item_count"],
        "minutes": trow["time_limit_minutes"],
        "pass_percent": trow["pass_percent"],
        "best_percent": best,
        "pool": pool,
        "open": open_map,
        "ask": bool(ai_on and trow["ask_status"] == "approved"),
    }


def list_tests(c, user: str) -> list[dict]:
    _finalize_expired_for(c, user)
    ai_on = ai.current() is not None
    rows = c.execute(
        """SELECT pt.*, p.owner, p.title AS package_title, p.ask_status
           FROM package_tests pt
           JOIN packages p ON p.id = pt.package_id
           WHERE p.owner=? OR EXISTS(
               SELECT 1 FROM package_access pa
               WHERE pa.package_id = p.id AND pa.user=? AND pa.revoked_at IS NULL
           )
           ORDER BY p.updated_at DESC, pt.ord""",
        (user, user),
    ).fetchall()
    return [_summary_from_row(c, user, r, ai_on) for r in rows]


def test_detail(c, user: str, key: str) -> dict | None:
    trow = catalog.test_row(c, user, key)
    if not trow:
        return None
    _finalize_expired_for(c, user, key)
    summary = _summary_from_row(c, user, trow, ai.current() is not None)
    history = []
    for r in c.execute(
        """SELECT ta.id, ta.mode, ta.score, ta.total, ta.submitted_at, tr.data
           FROM test_attempt ta
           JOIN test_revision tr ON tr.id = ta.revision_id
           WHERE ta.user=? AND ta.test_key=? AND ta.submitted_at IS NOT NULL AND ta.mode IN ('exam', 'practice')
           ORDER BY ta.submitted_at DESC, ta.id DESC""",
        (user, key),
    ):
        pass_pct = json.loads(r["data"]).get("pass_percent", 70)
        history.append({
            "id": r["id"],
            "mode": r["mode"],
            "percent": _percent(r["score"] or 0, r["total"] or 0),
            "passed": _passed(r["score"] or 0, r["total"] or 0, pass_pct),
            "at": r["submitted_at"],
        })
    return {**summary, "history": history}
