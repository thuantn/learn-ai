"""Learning app: login, lessons, podcast position, flashcards, Ask box."""
import asyncio
import hmac
import json
import logging
import mimetypes
import os
import pathlib
import secrets
import time
import urllib.error
import urllib.request
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fsrs import Card, Rating, Scheduler
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import ClientDisconnect

from . import auth, bundle, catalog, db, sandbox, uploads

log = logging.getLogger("learn")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"
VN = timezone(timedelta(hours=7))
_PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN") or "'self'"
_FRAME_SRC = f"{_PUBLIC_ORIGIN}/s/" if _PUBLIC_ORIGIN != "'self'" else "'self'"
_SCRIPT_SRC = f"{_PUBLIC_ORIGIN}/static/" if _PUBLIC_ORIGIN != "'self'" else "'self'"
CSP = (
    f"default-src 'self'; script-src {_SCRIPT_SRC}; " "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; "
    "connect-src 'self'; media-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; "
    f"frame-src {_FRAME_SRC}"
)
HEADERS = {
    "Content-Security-Policy": CSP,
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
JSON_LIMIT, DOC_LIMIT = 16 * 1024, 2 * 1024 * 1024
ASK_INPUT_MAX, QUESTION_MAX = 24000, 2000
ASK_PER_MINUTE = 6
SHARE_PER_MINUTE, JOIN_PER_MINUTE = 30, 10
FEEDBACK_MAX, FEEDBACK_PER_HOUR = 2000, 20
FEEDBACK_KINDS = ("comment", "wrong", "abuse")
HASHING = asyncio.Semaphore(2)  # each Argon2 call uses about 19 MB
PUBLIC_PATHS = {"/login", "/healthz", "/favicon.ico"}
PASSWORD_PATHS = {"/change-password", "/api/change-password", "/logout"}

limiter = auth.LoginLimiter()
proxy = auth.ProxyIp(os.environ.get("TRUSTED_PROXY", ""))
scheduler = Scheduler(enable_fuzzing=False)
ask_recent = defaultdict(list)
share_recent = defaultdict(list)
join_recent = defaultdict(list)


async def backup_loop(dest):
    while True:
        try:
            await asyncio.to_thread(db.backup, dest)
        except Exception:
            log.exception("backup failed")
        await asyncio.sleep(86400)


@asynccontextmanager
async def lifespan(_):
    db.init()
    if len(os.environ.get("LINK_SECRET", "")) < 32:
        raise RuntimeError("LINK_SECRET is required, 32+ characters")
    uploads.clear_staging()
    catalog.sweep()
    dest = os.environ.get("BACKUP_DIR")
    task = asyncio.create_task(backup_loop(dest)) if dest else None
    yield
    if task:
        task.cancel()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
# The slim image has no /etc/mime.types.
for _type, _ext in (("application/manifest+json", ".webmanifest"), ("font/woff2", ".woff2"), ("audio/mpeg", ".mp3")):
    mimetypes.add_type(_type, _ext)

hosts = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]
if hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts + ["127.0.0.1"])


def client_ip(request):
    return proxy.client(request.client.host if request.client else None, request.headers.get("cf-connecting-ip"))


def origin_ok(request):
    origin = request.headers.get("origin")
    expected = os.environ.get("PUBLIC_ORIGIN")
    if expected:
        return origin == expected
    return origin == f"{request.url.scheme}://{request.headers.get('host')}"


def bad(status, code, message):
    return JSONResponse({"code": code, "error": message}, status_code=status)


@app.middleware("http")
async def guard(request: Request, call_next):
    resp = await _guarded(request, call_next)
    for k, v in HEADERS.items():
        if k == "X-Frame-Options" and request.url.path.startswith("/s/"):
            continue
        resp.headers.setdefault(k, v)
    if not request.url.path.startswith(("/static/", "/s/")):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


async def _guarded(request, call_next):
    """Denies by default: only the login page, health check and public static files skip the session."""
    path = request.url.path
    if request.method not in ("GET", "HEAD") and not origin_ok(request):
        return bad(403, "origin", "Yêu cầu không hợp lệ.")
    if path in PUBLIC_PATHS or path.startswith("/static/") or path.startswith("/s/"):
        return await call_next(request)
    found = await asyncio.to_thread(auth.lookup_session, request.cookies.get(auth.cookie_name()))
    wants_api = path.startswith("/api/")
    if not found:
        return bad(401, "login", "Cần đăng nhập.") if wants_api else RedirectResponse("/login", 303)
    request.state.user, request.state.must_change = found
    if request.state.must_change and path not in PASSWORD_PATHS:
        return bad(403, "must_change", "Cần đổi mật khẩu trước.") if wants_api else RedirectResponse("/change-password", 303)
    return await call_next(request)


@app.exception_handler(Exception)
async def crashed(request, exc):
    log.exception("error on %s", request.url.path)
    return bad(500, "server", "Có lỗi ở server. Thử lại sau.")


async def read_json(request, limit=JSON_LIMIT):
    """Reads at most limit bytes, even if the client lies about or omits Content-Length."""
    if "application/json" not in request.headers.get("content-type", ""):
        return None
    size, parts = 0, []
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        parts.append(chunk)
    try:
        data = json.loads(b"".join(parts))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def page(name, status=200):
    return FileResponse(WEB / name, media_type="text/html; charset=utf-8", status_code=status)


def set_session_cookie(resp, token):
    secure = os.environ.get("COOKIE_SECURE", "1") == "1"
    resp.set_cookie(auth.cookie_name(), token, httponly=True, secure=secure, samesite="strict", path="/", max_age=auth.ABSOLUTE_SECONDS)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/")
async def home():
    return page("app.html")


@app.get("/login")
async def login_page(request: Request):
    return page("login.html")


@app.get("/change-password")
async def change_password_page(request: Request):
    if not request.state.must_change:
        return RedirectResponse("/", 303)
    return page("password.html")


@app.get("/lesson/{lesson_id}")
async def lesson_page(lesson_id: str, request: Request):
    with db.connect() as c:
        if not catalog.lesson_for(c, request.state.user, lesson_id):
            return page("no-lesson.html", 404)
    return page("lesson.html")


@app.post("/login")
async def login(request: Request):
    data = await read_json(request)
    name = str((data or {}).get("username", "")).strip().lower()[:254]
    password = str((data or {}).get("password", ""))
    ip = client_ip(request)
    if limiter.blocked(ip, name):
        log.warning("login blocked name=%r ip=%s", name, ip)
        return bad(429, "wait", "Thử lại sau ít phút.")
    with db.connect() as c:
        row = c.execute("SELECT pw_hash, must_change FROM users WHERE name=?", (name,)).fetchone()
    stored = row["pw_hash"] if row else None
    ok = False
    if len(password) <= auth.MAX_PASSWORD:
        async with HASHING:
            ok = await asyncio.to_thread(auth.verify_password, stored, password)
    if not ok:
        limiter.failed(ip, name)
        log.warning("login failed name=%r ip=%s", name, ip)
        return bad(401, "login", "Sai tên đăng nhập hoặc mật khẩu.")
    limiter.succeeded(ip, name)
    with db.connect() as c:
        token = auth.new_session(c, name)
    log.info("login ok name=%r ip=%s", name, ip)
    resp = JSONResponse({"must_change": bool(row["must_change"])})
    set_session_cookie(resp, token)
    return resp


@app.post("/logout")
async def logout(request: Request):
    auth.end_session(request.cookies.get(auth.cookie_name()))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.cookie_name(), path="/", secure=os.environ.get("COOKIE_SECURE", "1") == "1", httponly=True, samesite="strict")
    return resp


@app.post("/api/change-password")
async def change_password(request: Request):
    if not request.state.must_change:
        return bad(403, "not_needed", "Tài khoản này không cần đổi mật khẩu. Hãy liên hệ quản trị.")
    data = await read_json(request)
    new = str((data or {}).get("password", ""))
    user = request.state.user
    problem = auth.password_problem(user, new)
    if problem:
        return bad(400, "weak", problem)
    with db.connect() as c:
        old = c.execute("SELECT pw_hash FROM users WHERE name=?", (user,)).fetchone()["pw_hash"]
    async with HASHING:
        same = await asyncio.to_thread(auth.verify_password, old, new)
        if same:
            return bad(400, "weak", "Mật khẩu mới phải khác mật khẩu tạm.")
        hashed = await asyncio.to_thread(auth.hash_password, new)
    with db.connect() as c:
        c.execute("UPDATE users SET pw_hash=?, must_change=0 WHERE name=?", (hashed, user))
        c.execute("DELETE FROM sessions WHERE user=?", (user,))
        token = auth.new_session(c, user)
    log.info("password changed name=%r", user)
    resp = JSONResponse({"ok": True})
    set_session_cookie(resp, token)
    return resp


@app.get("/api/me")
async def me(request: Request):
    return {"id": request.state.user}


# ---------- Lessons ----------

@app.get("/api/lessons")
async def lessons(request: Request):
    user = request.state.user
    now = time.time()
    with db.connect() as c:
        lessons = catalog.lessons_for(c, user)
        progress = {r["lesson"]: r for r in c.execute("SELECT * FROM lesson_progress WHERE user=?", (user,))}
        positions = {r["episode"]: r["seconds"] for r in c.execute("SELECT episode, seconds FROM listen_pos WHERE user=?", (user,))}
        due_rows, lesson_map = _due_rows(c, user, now)
        due = {}
        for r in due_rows:
            due[r["lesson"]] = due.get(r["lesson"], 0) + 1
        next_due = None
        for r in c.execute(
            "SELECT card_id, lesson, due FROM card_state WHERE user=? AND due>? ORDER BY due",
            (user, now),
        ).fetchall():
            lesson = lesson_map.get(r["lesson"])
            if not lesson:
                continue
            bare_id = r["card_id"].split(".", 1)[1]
            if _find_card(lesson, bare_id):
                next_due = r["due"]
                break
    out = []
    for x in lessons:
        p = progress.get(x["id"])
        tracks = {}
        for key, t in x["tracks"].items():
            pos = positions.get(f"{x['id']}:{key}", 0)
            tracks[key] = {
                "url": t["url"],
                "duration": t["duration"],
                "position": 0 if pos >= t["duration"] - 15 else pos,
                "label": t["label"],
            }
        out.append({
            "id": x["id"],
            "title": x["title"],
            "order": x["ord"] + 1,
            "page": x["page"],
            "summary": x["summary"],
            "status": p["status"] if p else "new",
            "track": p["track"] if p else default_track(tracks),
            "due": due.get(x["id"], 0),
            "tracks": tracks,
            "suggest": [card["q"] for card in x["cards"][:3]],
            "package_id": x["package_id"],
            "package_title": x["package_title"],
            "author": x["author"],
            "mine": x["mine"],
            "ask": bool(os.environ.get("AI_API_KEY")) and x["ask_status"] == "approved",
        })
    return {"lessons": out, "due_total": sum(due.values()), "next_due": next_due}


@app.post("/api/lessons/{lesson_id}/start")
async def start_lesson(lesson_id: str, request: Request):
    user = request.state.user
    now = time.time()
    with db.connect() as c:
        lesson = catalog.lesson_for(c, user, lesson_id)
        if not lesson:
            return bad(404, "lesson", "Không có bài này.")
        c.execute(
            "INSERT INTO lesson_progress VALUES(?,?,'in_progress',?,?) ON CONFLICT(user, lesson) DO NOTHING",
            (user, lesson_id, default_track(lesson["tracks"]), now),
        )
        for card in lesson["cards"]:
            add_card(c, user, card["id"], lesson_id, lesson["package_id"], now)
    return {"ok": True}


def default_track(tracks):
    return "long" if "long" in tracks else next(iter(tracks), "long")


def add_card(c, user, bare_id, lesson_key, package_id, now):
    c.execute(
        "INSERT INTO card_state VALUES(?,?,?,?,?) ON CONFLICT(user, card_id) DO NOTHING",
        (user, catalog.progress_id(package_id, bare_id), lesson_key, now, Card().to_json()),
    )


@app.post("/api/lessons/{lesson_id}/finish")
async def finish_lesson(lesson_id: str, request: Request):
    user = request.state.user
    with db.connect() as c:
        if not catalog.lesson_for(c, user, lesson_id):
            return bad(404, "lesson", "Không có bài này.")
        c.execute("UPDATE lesson_progress SET status='done', updated_at=? WHERE user=? AND lesson=?", (time.time(), user, lesson_id))
    return {"ok": True}


@app.post("/api/lessons/{lesson_id}/frame")
async def lesson_frame(lesson_id: str, request: Request):
    if not sandbox._secret():
        return Response(status_code=404)
    user = request.state.user
    now = time.time()
    with db.connect() as c:
        lesson = catalog.lesson_for(c, user, lesson_id)
        if not lesson:
            return bad(404, "lesson", "Không có bài này.")
        row = c.execute("SELECT rowid FROM users WHERE name=?", (user,)).fetchone()
        if not row:
            return bad(403, "user", "Tài khoản không tồn tại.")
        user_id = row["rowid"]
        expires = now + int(os.environ.get("LINK_TTL_SECONDS", str(sandbox.LINK_TTL_SECONDS_DEFAULT)))
        token = sandbox.make_token(user_id, lesson_id, now)
        learner = sandbox.learner_code(user_id, lesson["package_id"])
    return JSONResponse({
        "url": f"/s/{token}/page/index.html",
        "expires": expires,
        "doc": lesson["doc"],
        "title": lesson["title"],
        "learner": learner,
        "author": lesson["author"],
        "package_title": lesson["package_title"],
        "ask": bool(os.environ.get("AI_API_KEY")) and lesson["ask_status"] == "approved",
    })


@app.post("/api/lessons/{lesson_id}/quiz-answer")
async def lesson_quiz_answer(lesson_id: str, request: Request):
    data = await read_json(request)
    qid = str((data or {}).get("id", ""))
    option = (data or {}).get("option")
    if not isinstance(option, int) or isinstance(option, bool):
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    user, now = request.state.user, time.time()
    with db.connect() as c:
        lesson = catalog.lesson_for(c, user, lesson_id)
        if not lesson:
            return bad(404, "lesson", "Không có bài này.")
        quiz_item = None
        for q in lesson["quiz"]:
            if q["id"] == qid:
                quiz_item = q
                break
        if not quiz_item:
            return bad(400, "input", "Không có câu hỏi này.")
        correct = option == quiz_item["answer"]
        if not correct:
            _record_wrong(c, user, lesson, quiz_item, now)
    return {"correct": correct}


@app.put("/api/listen")
async def save_listen(request: Request):
    data = await read_json(request)
    episode = str((data or {}).get("episode", ""))
    lesson_key, _, track = episode.partition(":")
    seconds = (data or {}).get("seconds")
    user, now = request.state.user, time.time()
    with db.connect() as c:
        lesson = catalog.lesson_for(c, user, lesson_key)
        if not lesson:
            return bad(404, "lesson", "Không có bài này.")
        if track not in lesson["tracks"] or not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
            return bad(400, "input", "Dữ liệu không hợp lệ.")
        seconds = max(0.0, min(float(seconds), float(lesson["tracks"][track]["duration"])))
        c.execute("INSERT OR REPLACE INTO listen_pos VALUES(?,?,?,?)", (user, episode, seconds, now))
        c.execute(
            "INSERT INTO lesson_progress VALUES(?,?,'in_progress',?,?) ON CONFLICT(user, lesson) DO UPDATE SET track=excluded.track, updated_at=excluded.updated_at",
            (user, lesson_key, track, now),
        )
    return {"ok": True}


@app.get("/audio/{lesson_id}/{track}")
async def audio(lesson_id: str, track: str, request: Request):
    user = request.state.user
    with db.connect() as c:
        lesson = catalog.lesson_for(c, user, lesson_id)
        if not lesson or track not in lesson["tracks"]:
            return Response(status_code=404)
        base = catalog.lesson_dir(c, lesson_id)
    if not base:
        return Response(status_code=404)
    target = base / "audio" / lesson["tracks"][track]["file"]
    if target.is_symlink() or not target.is_file():
        return Response(status_code=404)
    return FileResponse(
        target,
        media_type="audio/mpeg",
        headers={
            "Accept-Ranges": "bytes",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300",
        },
    )


# ---------- Flashcards ----------

def _due_rows(c, user, now):
    """Returns card_state rows due<=now whose lesson is accessible and whose bare id still exists."""
    lessons = catalog.lessons_for(c, user)
    lesson_map = {l["id"]: l for l in lessons}
    rows = c.execute(
        "SELECT card_id, lesson, due FROM card_state WHERE user=? AND due<=? ORDER BY due",
        (user, now),
    ).fetchall()
    out = []
    for r in rows:
        lesson = lesson_map.get(r["lesson"])
        if not lesson:
            continue
        bare_id = r["card_id"].split(".", 1)[1]
        if not _find_card(lesson, bare_id):
            continue
        out.append(r)
    return out, lesson_map


def _find_card(lesson, bare_id):
    for card in lesson["cards"]:
        if card["id"] == bare_id:
            return card["q"], card["a"], "card"
    for q in lesson["quiz"]:
        if q["id"] == bare_id:
            answer = q["options"][q["answer"]]
            if q.get("why"):
                answer = f"{answer}. {q['why']}"
            return q["q"], answer, "quiz"
    return None


@app.get("/api/cards/due")
async def due_cards(request: Request):
    user, now = request.state.user, time.time()
    with db.connect() as c:
        rows, lesson_map = _due_rows(c, user, now)
        wrong = {r["card_id"] for r in c.execute("SELECT card_id FROM wrong_card WHERE user=?", (user,))}
    out = []
    for r in rows:
        lesson = lesson_map.get(r["lesson"])
        if not lesson:
            continue
        bare_id = r["card_id"].split(".", 1)[1]
        pair = _find_card(lesson, bare_id)
        if not pair:
            continue
        q, a, target_type = pair
        out.append({
            "id": r["card_id"],
            "lesson": r["lesson"],
            "lesson_order": lesson["ord"] + 1,
            "q": q,
            "a": a,
            "wrong": r["card_id"] in wrong,
            "target_type": target_type,
            "target_id": bare_id,
        })
        if len(out) >= 200:
            break
    return {"cards": out}


@app.post("/api/cards/{card_id}/review")
async def review_card(card_id: str, request: Request):
    data = await read_json(request)
    rating = (data or {}).get("rating")
    if rating not in (1, 2, 3, 4) or isinstance(rating, bool):
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    user, now = request.state.user, time.time()
    with db.connect() as c:
        row = c.execute("SELECT card_json, lesson FROM card_state WHERE user=? AND card_id=?", (user, card_id)).fetchone()
        if not row:
            return bad(404, "card", "Không có thẻ này.")
        lesson = catalog.lesson_for(c, user, row["lesson"])
        bare_id = card_id.partition(".")[2]
        if not bare_id or not lesson or not _find_card(lesson, bare_id):
            return bad(404, "card", "Không có thẻ này.")
        card, _ = scheduler.review_card(Card.from_json(row["card_json"]), Rating(rating), review_datetime=datetime.now(timezone.utc))
        due = card.due.timestamp()
        c.execute("UPDATE card_state SET due=?, card_json=? WHERE user=? AND card_id=?", (due, card.to_json(), user, card_id))
        c.execute("INSERT INTO review_log VALUES(?,?,?,?)", (user, card_id, rating, now))
    return {"due": due}


# ---------- Lesson page storage, used through the bridge ----------

def _record_wrong(c, user, lesson, q, now):
    """Stores one wrong quiz answer as a wrong card and opens an FSRS card."""
    card_id = catalog.progress_id(lesson["package_id"], q["id"])
    answer = q["options"][q["answer"]]
    if q.get("why"):
        answer = f"{answer}. {q['why']}"
    c.execute(
        "INSERT INTO wrong_card VALUES(?,?,?,?,?,?) ON CONFLICT(user, card_id) DO NOTHING",
        (user, card_id, lesson["id"], q["q"], answer, now),
    )
    add_card(c, user, q["id"], lesson["id"], lesson["package_id"], now)


def record_wrong_answers(c, user, lesson, quiz, now):
    """The browser only says which option was picked; whether it was right comes from the lesson."""
    if not isinstance(quiz, dict):
        return
    for i, q in enumerate(lesson["quiz"]):
        picked = quiz.get(f"q{i}")
        if not isinstance(picked, int) or isinstance(picked, bool) or picked == q["answer"]:
            continue
        _record_wrong(c, user, lesson, q, now)


@app.get("/api/doc/{name}")
async def get_doc(name: str, request: Request):
    user = request.state.user
    with db.connect() as c:
        if not catalog.lesson_for(c, user, name):
            return bad(404, "doc", "Không có tài liệu này.")
        row = c.execute("SELECT body FROM user_doc WHERE user=? AND name=?", (user, name)).fetchone()
    return {"data": json.loads(row["body"]) if row else None}


@app.put("/api/doc/{name}")
async def put_doc(name: str, request: Request):
    user = request.state.user
    data = await read_json(request, DOC_LIMIT)
    if data is None:
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    now = time.time()
    with db.connect() as c:
        lesson = catalog.lesson_for(c, user, name)
        if not lesson:
            return bad(404, "doc", "Không có tài liệu này.")
        c.execute("INSERT OR REPLACE INTO user_doc VALUES(?,?,?,?)", (user, name, json.dumps(data, ensure_ascii=False), now))
        record_wrong_answers(c, user, lesson, data.get("quiz"), now)
    return {"ok": True}


# ---------- Library and sharing ----------

def recent_limit(store, user, limit, per=60):
    """In-memory counter per person, kept simple because there is one worker."""
    now = time.time()
    recent = store[user]
    recent[:] = [t for t in recent if now - t < per]
    if len(recent) >= limit:
        return False
    recent.append(now)
    return True


def owned_package(c, package_id, user):
    row = c.execute("SELECT * FROM packages WHERE id=?", (package_id,)).fetchone()
    return row if row and row["owner"] == user else None


def join_url(row):
    return f"/#join={row['id']}.{sandbox.join_signature(row['id'], row['link_nonce'])}" if row["link_nonce"] else None


@app.get("/api/packages")
async def list_packages(request: Request):
    user = request.state.user
    with db.connect() as c:
        titles, first = defaultdict(list), {}
        for r in c.execute(
            """SELECT key, package_id, json_extract(data, '$.title') title FROM package_lessons
               WHERE package_id IN (SELECT id FROM packages WHERE owner=?
                                    UNION SELECT package_id FROM package_access WHERE user=? AND revoked_at IS NULL)
               ORDER BY ord""", (user, user)):
            titles[r["package_id"]].append(r["title"])
            first.setdefault(r["package_id"], r["key"])
        mine = [{
            "id": r["id"], "title": r["title"], "topic": r["topic"], "description": r["description"],
            "version": r["version"], "size_bytes": r["size_bytes"], "lessons": titles[r["id"]], "first_lesson": first.get(r["id"]),
            "people": c.execute("SELECT count(*) n FROM package_access WHERE package_id=? AND revoked_at IS NULL", (r["id"],)).fetchone()["n"],
            "link_on": bool(r["link_nonce"]),
            "feedback": c.execute("SELECT count(*) n FROM feedback WHERE package_id=?", (r["id"],)).fetchone()["n"],
        } for r in c.execute("SELECT * FROM packages WHERE owner=? ORDER BY updated_at DESC", (user,)).fetchall()]
        shared = [{
            "id": r["id"], "title": r["title"], "topic": r["topic"], "description": r["description"],
            "author": r["owner"], "lessons": titles[r["id"]], "first_lesson": first.get(r["id"]),
        } for r in c.execute(
            """SELECT p.* FROM packages p JOIN package_access a ON a.package_id=p.id
               WHERE a.user=? AND a.revoked_at IS NULL ORDER BY a.granted_at DESC""", (user,)).fetchall()]
        row = c.execute("SELECT quota_bytes FROM users WHERE name=?", (user,)).fetchone()
    quota = row["quota_bytes"] if row and row["quota_bytes"] is not None else uploads.DEFAULT_QUOTA
    return {"mine": mine, "shared": shared, "used": sum(x["size_bytes"] for x in mine), "quota": quota}


@app.get("/api/packages/{package_id}/people")
async def package_people(package_id: str, request: Request):
    with db.connect() as c:
        if not owned_package(c, package_id, request.state.user):
            return bad(404, "package", "Không có package này.")
        rows = c.execute("SELECT user, via, granted_at FROM package_access WHERE package_id=? AND revoked_at IS NULL ORDER BY granted_at", (package_id,)).fetchall()
    return {"people": [{"email": r["user"], "via": r["via"], "granted_at": r["granted_at"]} for r in rows]}


@app.post("/api/packages/{package_id}/share")
async def share_package(package_id: str, request: Request):
    user = request.state.user
    data = await read_json(request)
    email = str((data or {}).get("email", "")).strip().lower()[:254]
    with db.connect() as c:
        if not owned_package(c, package_id, user):
            return bad(404, "package", "Không có package này.")
        if not recent_limit(share_recent, user, SHARE_PER_MINUTE):
            return bad(429, "rate_limited", "Thử lại sau ít phút.")
        if email == user:
            return bad(400, "self", "Đây là tài khoản của bạn.")
        if not email or not c.execute("SELECT 1 FROM users WHERE name=?", (email,)).fetchone():
            return bad(404, "no_account", "Email này chưa có tài khoản trong app.")
        c.execute(
            """INSERT INTO package_access(package_id, user, via, granted_at, revoked_at) VALUES(?,?,'email',?,NULL)
               ON CONFLICT(package_id, user) DO UPDATE SET revoked_at=NULL, via='email', granted_at=excluded.granted_at""",
            (package_id, email, time.time()),
        )
    return {"ok": True}


@app.post("/api/packages/{package_id}/unshare")
async def unshare_package(package_id: str, request: Request):
    data = await read_json(request)
    email = str((data or {}).get("email", "")).strip().lower()[:254]
    with db.connect() as c:
        if not owned_package(c, package_id, request.state.user):
            return bad(404, "package", "Không có package này.")
        c.execute("UPDATE package_access SET revoked_at=? WHERE package_id=? AND user=?", (time.time(), package_id, email))
    return {"ok": True}


@app.get("/api/packages/{package_id}/link")
async def get_link(package_id: str, request: Request):
    with db.connect() as c:
        row = owned_package(c, package_id, request.state.user)
    if not row:
        return bad(404, "package", "Không có package này.")
    return {"url": join_url(row)}


@app.post("/api/packages/{package_id}/link")
async def new_link(package_id: str, request: Request):
    with db.connect() as c:
        if not owned_package(c, package_id, request.state.user):
            return bad(404, "package", "Không có package này.")
        c.execute("UPDATE packages SET link_nonce=? WHERE id=?", (secrets.token_urlsafe(32), package_id))
        row = owned_package(c, package_id, request.state.user)
    return {"url": join_url(row)}


@app.delete("/api/packages/{package_id}/link")
async def link_off(package_id: str, request: Request):
    with db.connect() as c:
        if not owned_package(c, package_id, request.state.user):
            return bad(404, "package", "Không có package này.")
        c.execute("UPDATE packages SET link_nonce=NULL WHERE id=?", (package_id,))
    return {"ok": True}


@app.post("/api/join")
async def join_package(request: Request):
    user = request.state.user
    if not recent_limit(join_recent, user, JOIN_PER_MINUTE):
        return bad(429, "rate_limited", "Thử lại sau ít phút.")
    data = await read_json(request)
    package_id, _, signature = str((data or {}).get("token", "")).partition(".")
    with db.connect() as c:
        row = c.execute("SELECT id, owner, link_nonce FROM packages WHERE id=?", (package_id,)).fetchone()
        if not row or not row["link_nonce"] or not hmac.compare_digest(signature.encode(), sandbox.join_signature(package_id, row["link_nonce"]).encode()):
            return bad(404, "link", "Link không còn hiệu lực.")
        if row["owner"] != user:
            access = c.execute("SELECT revoked_at FROM package_access WHERE package_id=? AND user=?", (package_id, user)).fetchone()
            if access and access["revoked_at"] is not None:
                return bad(403, "revoked", "Bạn không còn quyền với bài này. Nhờ tác giả share lại.")
        if (data or {}).get("preview") is True:
            title = c.execute("SELECT title FROM packages WHERE id=?", (package_id,)).fetchone()["title"]
            return {"title": title, "author": row["owner"], "mine": row["owner"] == user}
        if row["owner"] != user:
            c.execute(
                "INSERT INTO package_access(package_id, user, via, granted_at) VALUES(?,?,'link',?) ON CONFLICT(package_id, user) DO NOTHING",
                (package_id, user, time.time()),
            )
        first = c.execute("SELECT key FROM package_lessons WHERE package_id=? ORDER BY ord LIMIT 1", (package_id,)).fetchone()
    return {"package_id": package_id, "first_lesson": first["key"] if first else None}


@app.post("/api/packages/{package_id}/leave")
async def leave_package(package_id: str, request: Request):
    with db.connect() as c:
        left = c.execute(
            "UPDATE package_access SET revoked_at=? WHERE package_id=? AND user=? AND revoked_at IS NULL",
            (time.time(), package_id, request.state.user),
        ).rowcount
    return {"ok": True} if left else bad(404, "package", "Không có package này.")


@app.delete("/api/packages/{package_id}")
async def delete_package(package_id: str, request: Request):
    user = request.state.user
    with db.connect() as c:
        if not owned_package(c, package_id, user):
            return bad(404, "package", "Không có package này.")
    await asyncio.to_thread(catalog.delete_package, package_id)
    log.info("package deleted user=%r id=%s", user, package_id)
    return {"ok": True}


# ---------- Feedback ----------

@app.post("/api/lessons/{lesson_id}/feedback")
async def send_feedback(lesson_id: str, request: Request):
    user = request.state.user
    data = await read_json(request) or {}
    with db.connect() as c:
        lesson = catalog.lesson_for(c, user, lesson_id)
        if not lesson:
            return bad(404, "lesson", "Không có bài này.")
        kind, target_type, target_id = data.get("kind"), data.get("target_type"), str(data.get("target_id") or "")
        text = data.get("text")
        if kind not in FEEDBACK_KINDS or not isinstance(text, str) or not 0 < len(text.strip()) <= FEEDBACK_MAX:
            return bad(400, "input", "Góp ý đang trống hoặc quá dài.")
        pools = {"lesson": None, "card": lesson["cards"], "quiz": lesson["quiz"]}
        if not isinstance(target_type, str) or target_type not in pools or (pools[target_type] is not None and target_id not in {x["id"] for x in pools[target_type]}):
            return bad(400, "input", "Dữ liệu không hợp lệ.")
        hour_ago = time.time() - 3600
        if c.execute("SELECT count(*) n FROM feedback WHERE author=? AND created_at>?", (user, hour_ago)).fetchone()["n"] >= FEEDBACK_PER_HOUR:
            return bad(429, "rate_limited", "Bạn đã gửi nhiều góp ý. Thử lại sau.")
        c.execute(
            "INSERT INTO feedback(package_id, lesson, target_type, target_id, kind, author, body, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (lesson["package_id"], lesson_id, target_type, "" if target_type == "lesson" else target_id, kind, user, text.strip(), time.time()),
        )
    return {"ok": True}


@app.get("/api/packages/{package_id}/feedback")
async def package_feedback(package_id: str, request: Request):
    with db.connect() as c:
        if not owned_package(c, package_id, request.state.user):
            return bad(404, "package", "Không có package này.")
        lessons = {r["key"]: json.loads(r["data"]) for r in c.execute("SELECT key, data FROM package_lessons WHERE package_id=?", (package_id,))}
        rows = c.execute("SELECT * FROM feedback WHERE package_id=? ORDER BY created_at DESC, id DESC LIMIT 200", (package_id,)).fetchall()
    out = []
    for r in rows:
        lesson = lessons.get(r["lesson"]) or {}
        pool = {"card": lesson.get("cards", []), "quiz": lesson.get("quiz", [])}.get(r["target_type"], [])
        out.append({
            "id": r["id"], "lesson_title": lesson.get("title"), "target_type": r["target_type"], "target_id": r["target_id"],
            "target_text": next((x["q"] for x in pool if x["id"] == r["target_id"]), None),
            "kind": r["kind"], "author": r["author"], "body": r["body"], "created_at": r["created_at"],
        })
    return {"feedback": out}


# ---------- Upload ----------

@app.post("/api/uploads")
async def upload_package(request: Request):
    user = request.state.user
    if "application/zip" not in request.headers.get("content-type", ""):
        return bad(400, "input", "Cần gửi file zip.")
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > bundle.MAX_ZIP:
        return bad(413, "too_large", "File zip quá lớn, tối đa 90 MB.")
    if not uploads.begin(user):
        return bad(429, "busy", "Đang có file khác được tải lên. Thử lại sau.")
    zip_path = None
    try:
        if await asyncio.to_thread(uploads.disk_low):
            return bad(507, "disk", "Máy chủ sắp hết dung lượng. Báo quản trị.")
        zip_path = uploads.staging_dir() / f"{secrets.token_hex(12)}.zip"
        try:
            await uploads.receive(request.stream(), zip_path)
        except uploads.TooLarge:
            return bad(413, "too_large", "File zip quá lớn, tối đa 90 MB.")
        except (ClientDisconnect, asyncio.TimeoutError):
            return bad(400, "interrupted", "Tải lên bị ngắt giữa chừng. Thử lại.")
        info = await asyncio.to_thread(uploads.prepare, zip_path, user)
    finally:
        if zip_path:
            zip_path.unlink(missing_ok=True)
        uploads.end(user)
    if "dir" not in info:
        return JSONResponse({"code": info["code"], "problems": info["problems"]}, status_code=413 if info["code"] == "quota" else 400)
    upload_id = uploads.keep(user, info)
    log.info("upload staged user=%r slug=%r size=%d", user, info["slug"], info["size"])
    return {"upload_id": upload_id, **{k: info[k] for k in ("title", "slug", "lessons", "is_update", "removed", "warnings", "size")}}


@app.post("/api/uploads/{upload_id}/commit")
async def commit_upload(upload_id: str, request: Request):
    user = request.state.user
    stage = uploads.get(upload_id, user)
    if not stage:
        return bad(404, "upload", "Bản tải lên đã hết hạn. Tải lại file.")
    if stage["committing"]:
        return bad(409, "busy", "Bản này đang được cài.")
    stage["committing"] = True  # refusals below keep the stage, so the author can send again without uploading again
    try:
        data = await read_json(request)
        if not data or data.get("attest") is not True:
            return bad(400, "attest", "Cần xác nhận nội dung trước khi đăng.")
        confirmed = data.get("confirm_removed") or []
        removed = await asyncio.to_thread(catalog.removed_ids, user, stage["dir"])
        if not isinstance(confirmed, list) or set(removed) - set(x for x in confirmed if isinstance(x, str)):
            return JSONResponse({"code": "confirm_removed", "error": "Cần xác nhận phần bị xóa.", "removed": removed}, status_code=409)
        if await asyncio.to_thread(uploads.over_quota, user, stage["slug"], stage["size"]) or await asyncio.to_thread(uploads.too_many, user, stage["slug"]):
            return bad(413, "quota", "Vượt hạn mức dung lượng của tài khoản.")
        result = await asyncio.to_thread(catalog.install_version, user, stage["dir"])
    finally:
        stage["committing"] = False
    await asyncio.to_thread(uploads.drop, upload_id)
    log.info("package installed user=%r id=%s version=%d", user, result["id"], result["version"])
    return {"package_id": result["id"], "version": result["version"]}


@app.delete("/api/uploads/{upload_id}")
async def cancel_upload(upload_id: str, request: Request):
    stage = uploads.get(upload_id, request.state.user)
    if stage and not stage["committing"]:
        await asyncio.to_thread(uploads.drop, upload_id)
    return {"ok": True}


# ---------- Ask box ----------

def lesson_context(lesson):
    points = "\n".join("- " + p for p in lesson["summary"])
    cards = "\n".join(f"- {x['q']} {x['a']}" for x in lesson["cards"])
    content = lesson.get("content", "")[:60000]
    return (
        f"Bạn là trợ giảng cho bài \"{lesson['title']}\". Trả lời bằng tiếng Việt, ngắn gọn và chính xác, dùng Markdown; công thức viết trong \\( \\). "
        "Nếu câu hỏi ngoài phạm vi học tập, hãy nói vậy.\n\n"
        f"Nội dung bài:\n{content}\n\n"
        f"Tóm tắt bài:\n{points}\n\nÝ quan trọng:\n{cards}"
    )


def call_ai(messages):
    body = {"model": os.environ.get("AI_MODEL", "deepseek/deepseek-v4.1-flash"), "messages": messages, "max_tokens": 1500}
    if os.environ.get("AI_ZDR", "1") == "1":
        body["provider"] = {"zdr": True}
    base = os.environ.get("AI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    req = urllib.request.Request(
        base + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + os.environ["AI_API_KEY"], "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def take_quota(user):
    now = time.time()
    recent = ask_recent[user]
    recent[:] = [t for t in recent if now - t < 60]
    if len(recent) >= ASK_PER_MINUTE:
        return False
    day = datetime.now(VN).strftime("%Y-%m-%d")
    limit = int(os.environ.get("AI_DAILY_LIMIT", "50"))
    with db.connect() as c:
        c.execute("INSERT INTO ask_usage VALUES(?,?,0) ON CONFLICT(user, day) DO NOTHING", (user, day))
        taken = c.execute("UPDATE ask_usage SET n=n+1 WHERE user=? AND day=? AND n<?", (user, day, limit)).rowcount
    if taken:
        recent.append(now)
    return bool(taken)


@app.post("/api/ask")
async def ask(request: Request):
    if not os.environ.get("AI_API_KEY"):
        return bad(503, "disabled", "Ô Hỏi chưa được bật.")
    data = await read_json(request, ASK_INPUT_MAX * 4)
    user = request.state.user
    lesson_key = (data or {}).get("lesson")
    with db.connect() as c:
        lesson = catalog.lesson_for(c, user, lesson_key)
    if not lesson:
        return bad(404, "lesson", "Không có bài này.")
    if lesson["ask_status"] != "approved":
        return bad(503, "disabled", "Ô Hỏi chưa được bật.")
    question = (data or {}).get("question")
    if not isinstance(question, str):
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    question = question.strip()
    if not 0 < len(question) <= QUESTION_MAX:
        return bad(400, "input", "Câu hỏi quá dài hoặc đang trống.")
    messages = [{"role": "system", "content": lesson_context(lesson)}, {"role": "user", "content": question}]
    if not await asyncio.to_thread(take_quota, user):
        return bad(429, "rate_limited", "Đã hết lượt hỏi. Thử lại sau.")
    try:
        text = await asyncio.to_thread(call_ai, messages)
    except urllib.error.HTTPError as e:
        log.warning("ai http %s", e.code)
        return bad(502, "ai", "Dịch vụ AI đang lỗi. Thử lại sau.")
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as e:
        log.warning("ai failed %s", type(e).__name__)
        return bad(502, "ai", "Dịch vụ AI đang lỗi. Thử lại sau.")
    return {"text": text}


# ---------- Static files ----------

def serve_listed(root, rel, extra=None):
    """Serves only listed files, so traversal, directory listing and symlinks have nothing to reach."""
    target = root / rel
    if target.is_symlink() or not target.is_file() or root not in target.resolve().parents:
        return Response(status_code=404)
    kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if kind.startswith("text/") or kind.endswith("javascript"):
        kind += "; charset=utf-8"
    headers = {"Cache-Control": "private, max-age=300"}
    if extra:
        headers.update(extra)
    return FileResponse(target, media_type=kind, headers=headers)


STATIC_FILES = {p.relative_to(WEB / "static").as_posix() for p in (WEB / "static").rglob("*") if p.is_file()} if (WEB / "static").exists() else set()


@app.get("/static/{rel:path}")
async def static(rel: str):
    if rel not in STATIC_FILES:
        return Response(status_code=404)
    extra = {"Cross-Origin-Resource-Policy": "cross-origin"}
    if rel.lower().endswith(".woff2"):
        extra["Access-Control-Allow-Origin"] = "*"
    return serve_listed(WEB / "static", rel, extra=extra)


@app.get("/s/{token}/{rel:path}")
async def sandbox_file(token: str, rel: str, request: Request):
    if not sandbox._secret():
        return Response(status_code=404)
    if not rel.startswith(("page/", "audio/")):
        return Response(status_code=404)
    parsed = sandbox.read_token(token, time.time())
    if parsed is None:
        return Response(status_code=403)
    user_id, lesson_key = parsed
    with db.connect() as c:
        if not sandbox.can_read(c, user_id, lesson_key):
            return Response(status_code=403)
        base = catalog.lesson_dir(c, lesson_key)
    if not base or not base.is_dir():
        return Response(status_code=404)
    page_root = (base / "page").resolve()
    audio_root = (base / "audio").resolve()
    target = base / rel
    if target.is_symlink():
        return Response(status_code=404)
    resolved = target.resolve()
    under_page = page_root in resolved.parents
    under_audio = audio_root in resolved.parents
    if not (under_page or under_audio) or not resolved.is_file():
        return Response(status_code=404)
    if resolved.suffix.lower() == ".html" and request.headers.get("Sec-Fetch-Dest") != "iframe":
        return Response(status_code=403)
    return serve_listed(base, rel, extra=sandbox.page_headers(rel))
