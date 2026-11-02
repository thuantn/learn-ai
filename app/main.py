"""Learning app: login, lessons, podcast position, flashcards, Ask box."""
import asyncio
import json
import logging
import mimetypes
import os
import pathlib
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

from . import auth, db, sandbox

log = logging.getLogger("learn")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"
VN = timezone(timedelta(hours=7))
_PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN") or "'self'"
_FRAME_SRC = f"{_PUBLIC_ORIGIN}/s/" if _PUBLIC_ORIGIN != "'self'" else "'self'"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; "
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
HASHING = asyncio.Semaphore(2)  # each Argon2 call uses about 19 MB
PUBLIC_PATHS = {"/login", "/healthz", "/favicon.ico"}
PASSWORD_PATHS = {"/change-password", "/api/change-password", "/logout"}

limiter = auth.LoginLimiter()
proxy = auth.ProxyIp(os.environ.get("TRUSTED_PROXY", ""))
scheduler = Scheduler(enable_fuzzing=False)
ask_recent = defaultdict(list)


def load_content():
    root = pathlib.Path(os.environ.get("CONTENT_DIR", "sample")).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    lessons = sorted(manifest["lessons"], key=lambda x: -x["order"])
    return root, lessons, set(manifest["files"])


CONTENT_ROOT, LESSONS, FILES = load_content()
BY_ID = {x["id"]: x for x in LESSONS}
BY_DOC = {x["doc"]: x for x in LESSONS}


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
    if not request.url.path.startswith(("/static/", "/content/", "/s/")):
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


def page(name):
    return FileResponse(WEB / name, media_type="text/html; charset=utf-8")


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
    return {"id": request.state.user, "ai": bool(os.environ.get("AI_API_KEY"))}


# ---------- Lessons ----------

def track_public(lesson, positions):
    out = {}
    for key, t in lesson["tracks"].items():
        pos = positions.get(f"{lesson['id']}:{key}", 0)
        out[key] = {"url": "/content/" + t["file"], "duration": t["duration"], "position": 0 if pos >= t["duration"] - 15 else pos, "label": t["label"]}
    return out


def card_front(lesson_id, card_id, user_wrong):
    if card_id in user_wrong:
        return user_wrong[card_id]
    for card in BY_ID[lesson_id]["cards"]:
        if card["id"] == card_id:
            return card["q"], card["a"]
    return None


@app.get("/api/lessons")
async def lessons(request: Request):
    user = request.state.user
    now = time.time()
    with db.connect() as c:
        progress = {r["lesson"]: r for r in c.execute("SELECT * FROM lesson_progress WHERE user=?", (user,))}
        positions = {r["episode"]: r["seconds"] for r in c.execute("SELECT episode, seconds FROM listen_pos WHERE user=?", (user,))}
        due = {r["lesson"]: r["n"] for r in c.execute("SELECT lesson, count(*) n FROM card_state WHERE user=? AND due<=? GROUP BY lesson", (user, now))}
        upcoming = c.execute("SELECT min(due) m FROM card_state WHERE user=? AND due>?", (user, now)).fetchone()["m"]
    out = []
    for x in LESSONS:
        p = progress.get(x["id"])
        out.append({
            "id": x["id"], "title": x["title"], "order": x["order"], "page": "/content/" + x["page"], "summary": x["summary"],
            "status": p["status"] if p else "new", "track": p["track"] if p else "long", "due": due.get(x["id"], 0),
            "tracks": track_public(x, positions), "suggest": [card["q"] for card in x["cards"][:3]],
        })
    return {"lessons": out, "due_total": sum(due.values()), "next_due": upcoming}


def known_lesson(lesson_id):
    return BY_ID.get(lesson_id)


@app.post("/api/lessons/{lesson_id}/start")
async def start_lesson(lesson_id: str, request: Request):
    lesson = known_lesson(lesson_id)
    if not lesson:
        return bad(404, "lesson", "Không có bài này.")
    user = request.state.user
    now = time.time()
    with db.connect() as c:
        c.execute(
            "INSERT INTO lesson_progress VALUES(?,?,'in_progress','long',?) ON CONFLICT(user, lesson) DO NOTHING",
            (user, lesson_id, now),
        )
        for card in lesson["cards"]:
            add_card(c, user, card["id"], lesson_id, now)
    return {"ok": True}


def add_card(c, user, card_id, lesson_id, now):
    c.execute(
        "INSERT INTO card_state VALUES(?,?,?,?,?) ON CONFLICT(user, card_id) DO NOTHING",
        (user, card_id, lesson_id, now, Card().to_json()),
    )


@app.post("/api/lessons/{lesson_id}/finish")
async def finish_lesson(lesson_id: str, request: Request):
    if not known_lesson(lesson_id):
        return bad(404, "lesson", "Không có bài này.")
    with db.connect() as c:
        c.execute("UPDATE lesson_progress SET status='done', updated_at=? WHERE user=? AND lesson=?", (time.time(), request.state.user, lesson_id))
    return {"ok": True}


@app.post("/api/lessons/{lesson_id}/frame")
async def lesson_frame(lesson_id: str, request: Request):
    if not sandbox._secret():
        return Response(status_code=404)
    lesson = known_lesson(lesson_id)
    if not lesson:
        return bad(404, "lesson", "Không có bài này.")
    user = request.state.user
    now = time.time()
    with db.connect() as c:
        row = c.execute("SELECT rowid FROM users WHERE name=?", (user,)).fetchone()
        if not row:
            return bad(403, "user", "Tài khoản không tồn tại.")
        user_id = row["rowid"]
        expires = now + int(os.environ.get("LINK_TTL_SECONDS", str(sandbox.LINK_TTL_SECONDS_DEFAULT)))
        token = sandbox.make_token(user_id, lesson_id, now)
        learner = sandbox.learner_code(user_id)
    return JSONResponse({
        "url": f"/s/{token}/page/index.html",
        "expires": expires,
        "doc": lesson["doc"],
        "title": lesson["title"],
        "learner": learner,
    })


@app.post("/api/lessons/{lesson_id}/quiz-answer")
async def lesson_quiz_answer(lesson_id: str, request: Request):
    lesson = known_lesson(lesson_id)
    if not lesson:
        return bad(404, "lesson", "Không có bài này.")
    data = await read_json(request)
    qid = str((data or {}).get("id", ""))
    option = (data or {}).get("option")
    if not isinstance(option, int) or isinstance(option, bool):
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    quiz_item = None
    for q in lesson["quiz"]:
        if q["id"] == qid:
            quiz_item = q
            break
    if not quiz_item:
        return bad(400, "input", "Không có câu hỏi này.")
    correct = option == quiz_item["answer"]
    user, now = request.state.user, time.time()
    if not correct:
        with db.connect() as c:
            _record_wrong(c, user, lesson, quiz_item, now)
    return {"correct": correct}


@app.put("/api/listen")
async def save_listen(request: Request):
    data = await read_json(request)
    lesson_id, _, track = str((data or {}).get("episode", "")).partition(":")
    lesson = known_lesson(lesson_id)
    seconds = (data or {}).get("seconds")
    if not lesson or track not in lesson["tracks"] or not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    seconds = max(0.0, min(float(seconds), float(lesson["tracks"][track]["duration"])))
    user, now = request.state.user, time.time()
    with db.connect() as c:
        c.execute("INSERT OR REPLACE INTO listen_pos VALUES(?,?,?,?)", (user, f"{lesson_id}:{track}", seconds, now))
        c.execute(
            "INSERT INTO lesson_progress VALUES(?,?,'in_progress',?,?) ON CONFLICT(user, lesson) DO UPDATE SET track=excluded.track, updated_at=excluded.updated_at",
            (user, lesson_id, track, now),
        )
    return {"ok": True}


# ---------- Flashcards ----------

@app.get("/api/cards/due")
async def due_cards(request: Request):
    user, now = request.state.user, time.time()
    with db.connect() as c:
        rows = c.execute("SELECT card_id, lesson FROM card_state WHERE user=? AND due<=? ORDER BY due LIMIT 200", (user, now)).fetchall()
        wrong = {r["card_id"]: (r["question"], r["answer"]) for r in c.execute("SELECT card_id, question, answer FROM wrong_card WHERE user=?", (user,))}
    out = []
    for r in rows:
        if r["lesson"] not in BY_ID:
            continue
        pair = card_front(r["lesson"], r["card_id"], wrong)
        if pair:
            out.append({"id": r["card_id"], "lesson": r["lesson"], "lesson_order": BY_ID[r["lesson"]]["order"], "q": pair[0], "a": pair[1], "wrong": r["card_id"] in wrong})
    return {"cards": out}


@app.post("/api/cards/{card_id}/review")
async def review_card(card_id: str, request: Request):
    data = await read_json(request)
    rating = (data or {}).get("rating")
    if rating not in (1, 2, 3, 4) or isinstance(rating, bool):
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    user, now = request.state.user, time.time()
    with db.connect() as c:
        row = c.execute("SELECT card_json FROM card_state WHERE user=? AND card_id=?", (user, card_id)).fetchone()
        if not row:
            return bad(404, "card", "Không có thẻ này.")
        card, _ = scheduler.review_card(Card.from_json(row["card_json"]), Rating(rating), review_datetime=datetime.now(timezone.utc))
        due = card.due.timestamp()
        c.execute("UPDATE card_state SET due=?, card_json=? WHERE user=? AND card_id=?", (due, card.to_json(), user, card_id))
        c.execute("INSERT INTO review_log VALUES(?,?,?,?)", (user, card_id, rating, now))
    return {"due": due}


# ---------- Lesson page storage, used through the shim ----------

def _record_wrong(c, user, lesson, q, now):
    """Stores one wrong quiz answer as a wrong card and opens an FSRS card."""
    answer = q["options"][q["answer"]]
    if q.get("why"):
        answer = f"{answer}. {q['why']}"
    c.execute(
        "INSERT INTO wrong_card VALUES(?,?,?,?,?,?) ON CONFLICT(user, card_id) DO NOTHING",
        (user, q["id"], lesson["id"], q["q"], answer, now),
    )
    add_card(c, user, q["id"], lesson["id"], now)


def record_wrong_answers(c, user, lesson, quiz, now):
    """The browser only says which option was picked; whether it was right comes from the manifest."""
    if not isinstance(quiz, dict):
        return
    for i, q in enumerate(lesson["quiz"]):
        picked = quiz.get(f"q{i}")
        if not isinstance(picked, int) or isinstance(picked, bool) or picked == q["answer"]:
            continue
        _record_wrong(c, user, lesson, q, now)


@app.get("/api/doc/{name}")
async def get_doc(name: str, request: Request):
    if name not in BY_DOC:
        return bad(404, "doc", "Không có tài liệu này.")
    with db.connect() as c:
        row = c.execute("SELECT body FROM user_doc WHERE user=? AND name=?", (request.state.user, name)).fetchone()
    return {"data": json.loads(row["body"]) if row else None}


@app.put("/api/doc/{name}")
async def put_doc(name: str, request: Request):
    lesson = BY_DOC.get(name)
    if not lesson:
        return bad(404, "doc", "Không có tài liệu này.")
    data = await read_json(request, DOC_LIMIT)
    if data is None:
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    user, now = request.state.user, time.time()
    with db.connect() as c:
        c.execute("INSERT OR REPLACE INTO user_doc VALUES(?,?,?,?)", (user, name, json.dumps(data, ensure_ascii=False), now))
        record_wrong_answers(c, user, lesson, data.get("quiz"), now)
    return {"ok": True}


# ---------- Ask box ----------

def clean_input(raw):
    """A string or a list of user and assistant turns. System prompts come only from this server."""
    if isinstance(raw, str):
        return [{"role": "user", "content": raw}] if 0 < len(raw) <= ASK_INPUT_MAX else None
    if not isinstance(raw, list) or not raw or len(raw) > 100:
        return None
    total = 0
    out = []
    for m in raw:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str):
            return None
        total += len(m["content"])
        out.append({"role": m["role"], "content": m["content"]})
    if total > ASK_INPUT_MAX or out[-1]["role"] != "user":
        return None
    return out


def lesson_context(lesson):
    points = "\n".join("- " + p for p in lesson["summary"])
    cards = "\n".join(f"- {x['q']} {x['a']}" for x in lesson["cards"])
    return (
        f"Bạn là trợ giảng cho bài \"{lesson['title']}\". Trả lời bằng tiếng Việt, ngắn gọn và chính xác, dùng Markdown; công thức viết trong \\( \\). "
        "Nếu câu hỏi ngoài phạm vi học tập, hãy nói vậy.\n\n"
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
    lesson = known_lesson((data or {}).get("lesson"))
    if not lesson:
        return bad(400, "input", "Dữ liệu không hợp lệ.")
    if isinstance(data.get("question"), str):
        question = data["question"].strip()
        if not 0 < len(question) <= QUESTION_MAX:
            return bad(400, "input", "Câu hỏi quá dài hoặc đang trống.")
        messages = [{"role": "system", "content": lesson_context(lesson)}, {"role": "user", "content": question}]
    else:
        messages = clean_input(data.get("input"))
        if not messages:
            return bad(400, "input", "Dữ liệu không hợp lệ.")
    if not await asyncio.to_thread(take_quota, request.state.user):
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


@app.get("/content/{rel:path}")
async def content(rel: str):
    if rel not in FILES:
        return Response(status_code=404)
    return serve_listed(CONTENT_ROOT, rel)


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
    user_id, lesson = parsed
    with db.connect() as c:
        if not sandbox.can_read(c, user_id, lesson):
            return Response(status_code=403)
    packages_dir = pathlib.Path(os.environ.get("PACKAGES_DIR", "packages")).resolve()
    base = (packages_dir / "lessons" / lesson).resolve()
    if not base.is_dir():
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
