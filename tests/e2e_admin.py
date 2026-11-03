"""Real-browser checks for the admin page and the Ask approval flow, against a local fake provider.
  python tests/e2e_admin.py [--browser chrome|webkit]
"""
import argparse
import base64
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

from playwright.sync_api import sync_playwright

from e2e_platform import FAILS, ROOT, SHOTS, XSS, check, free_port, login_first, make_zip, upload

KEY = "sk-test-abcd1234"
SEEN = []
# The server runs with the provider address swapped here, because production code has no setting for it.
LAUNCH = """
import sys, uvicorn
from app import ai
ai.PROVIDERS["openrouter"]["base"] = sys.argv[1]
uvicorn.run("app.main:app", port=int(sys.argv[2]), log_level="warning")
"""


class FakeAI(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append({"auth": self.headers.get("Authorization"), "body": body})
        out = json.dumps({"choices": [{"message": {"content": "**Trả lời giả** \\(x^2\\)"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def add_test_to_zip(dest):
    test_json = json.dumps({
        "title": "Đề Quản Trị",
        "description": "Mô tả đề",
        "items": [{
            "id": "q1",
            "type": "single",
            "domain": "Chung",
            "question": "Câu hỏi trong bộ đề?",
            "options": [{"id": "A", "text": "Lựa chọn đúng", "why": "Vì đây là đáp án đúng"}, {"id": "B", "text": "Lựa chọn sai", "why": "Vì sai"}],
            "correct": ["A"],
            "explanation": "Lời giải chi tiết cho câu hỏi.",
        }]
    })
    with zipfile.ZipFile(dest, "r") as zin:
        entries = {item.filename: zin.read(item.filename) for item in zin.infolist()}
    pkg = json.loads(entries["package.json"].decode("utf-8"))
    pkg["tests"] = ["t1"]
    entries["package.json"] = json.dumps(pkg).encode("utf-8")
    entries["tests/t1.json"] = test_json.encode("utf-8")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for fname, data in entries.items():
            zout.writestr(fname, data)
    return dest


def new_page(br, errs, width=1280, height=900):
    ctx = br.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce")
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append("js: " + str(e)[:160]))
    pg.on("console", lambda m: errs.append("csp: " + m.text[:160]) if m.type == "error" and "Content Security Policy" in m.text else None)
    pg.on("dialog", lambda d: d.accept("Nội dung vi phạm") if d.type == "prompt" else d.accept())
    return pg


def call(pg, method, url, body=None):
    return pg.evaluate("""async ([method, url, body]) => {
        const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
        return { status: r.status, text: await r.text() };
    }""", [method, url, body])


def commit_upload(pg, path):
    upload(pg, path)
    pg.wait_for_selector("#upAttest", state="visible")
    pg.check("#upAttest")
    pg.click("#upCommit")
    pg.wait_for_selector("#uploadDialog", state="hidden")


def layout(pg, base):
    for width, height in ((360, 740), (390, 844), (1024, 768), (1440, 900)):
        pg.set_viewport_size({"width": width, "height": height})
        pg.goto(base + "/admin")
        pg.wait_for_selector("#userList .stream-row")
        over = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check(f"admin {width}px no horizontal scroll", over <= 0, over)
        small = pg.evaluate("""() => [...document.querySelectorAll('.admin-page button, .admin-page a, .admin-page select, .admin-page input')]
            .filter(e => e.offsetParent && e.getBoundingClientRect().height < 44).map(e => e.id || e.textContent.trim()).slice(0, 5)""")
        check(f"admin {width}px touch targets", not small, small)
        colors = pg.evaluate("(() => { const s = getComputedStyle(document.getElementById('aiProvider')); return [s.color, s.backgroundColor]; })()")
        check(f"admin {width}px provider select is readable", colors[0] != colors[1] and colors[1] not in ("rgb(255, 255, 255)", "rgba(0, 0, 0, 0)"), colors)
        narrow = pg.evaluate("[...document.querySelectorAll('.admin-page .lib-info')].filter(e => e.offsetWidth < 240).length")
        check(f"admin {width}px rows keep their width", narrow == 0, narrow)
        pg.screenshot(path=str(SHOTS / f"admin-{width}.png"), full_page=True)


def run(br, base, temp, work):
    errs = []
    boss = new_page(br, errs)
    an = new_page(br, errs)
    binh = new_page(br, errs)
    cuong = new_page(br, errs)
    for pg, name in ((boss, "boss@example.com"), (an, "an@example.com"), (binh, "binh@example.com"), (cuong, "cuong@example.com")):
        login_first(pg, base, name, temp[name])
        pg.wait_for_url(base + "/")

    # A normal account cannot tell the admin page exists.
    r = cuong.goto(base + "/admin")
    unknown = cuong.context.request.get(base + "/no-such-route")
    check("/admin looks like an unknown route", r.status == 404 and r.body() == unknown.body(), r.status)
    r = cuong.context.request.get(base + "/api/admin/overview")
    check("admin API looks like an unknown route", r.status == 404 and r.body() == unknown.body(), r.status)
    cuong.goto(base + "/#library")
    cuong.wait_for_selector("#screen-library.active")
    check("no admin link for a normal account", not cuong.locator("#libAdmin").is_visible())

    # The author asks for Ask.
    an.goto(base + "/#library")
    an.wait_for_selector("#screen-library.active")
    commit_upload(an, add_test_to_zip(make_zip(work / "v1.zip", "bai-hoi", f"Bài {XSS}", content="# Bản một\n")))
    an.wait_for_selector("#libMine .stream-row")
    pid = call(an, "GET", "/api/packages")
    pid = json.loads(pid["text"])["mine"][0]["id"]
    key = f"{pid}.sample"
    call(an, "POST", f"/api/packages/{pid}/share", {"email": "binh@example.com"})
    an.click("#libMine [data-act=lib-ask]")
    an.wait_for_selector("#libMine .meta-pill:has-text('chờ admin duyệt')")
    check("author sees the request is waiting", True)
    check("request button is gone", an.locator("#libMine [data-act=lib-ask]").count() == 0)

    # The admin page, before any key.
    boss.goto(base + "/#library")
    boss.wait_for_selector("#screen-library.active")
    check("admin link for an admin", boss.locator("#libAdmin").is_visible())
    boss.goto(base + "/admin")
    boss.wait_for_selector("#pendingList .stream-row")
    check("pending package is listed", "Bài <img" in boss.locator("#pendingList").inner_text())
    check("package title stays text", boss.evaluate("window.__xss") is None)
    check("no key yet is stated", "Chưa có khóa" in boss.inner_text("#aiCurrent"))
    boss.screenshot(path=str(SHOTS / "admin-empty.png"), full_page=True)

    # Key entry.
    boss.fill("#aiKey", "short")
    boss.click("#aiForm button[type=submit]")
    boss.wait_for_selector("#aiResult:has-text('không hợp lệ')")
    check("a bad key is refused", True)
    boss.select_option("#aiProvider", "openrouter")
    boss.fill("#aiKey", KEY)
    boss.click("#aiForm button[type=submit]")
    boss.wait_for_selector("#aiCurrent:has-text('1234')")
    check("only the last 4 characters show", KEY not in boss.content() and boss.input_value("#aiKey") == "")
    boss.reload()
    boss.wait_for_selector("#aiCurrent:has-text('1234')")
    check("still only the last 4 after reload", KEY not in boss.content())
    boss.click("#aiTest")
    boss.wait_for_selector("#aiResult:has-text('Kết nối được')")
    check("connection test works", SEEN and SEEN[-1]["auth"] == "Bearer " + KEY)
    check("connection test asks for ZDR", SEEN[-1]["body"].get("provider") == {"zdr": True}, SEEN[-1]["body"])

    # A learner has no Ask until the admin approves.
    binh.goto(f"{base}/lesson/{key}", wait_until="networkidle")
    check("no Ask before approval", not binh.locator("#lessonAskBtn").is_visible())
    calls = len(SEEN)

    # The admin reads, the author changes the text meanwhile: the approval must fail.
    boss.click("#pendingList [type=button]")
    boss.wait_for_selector("#reviewDialog[open]")
    check("review shows what the AI will read", "Bản một" in boss.inner_text("#reviewBody"))
    shown = boss.inner_text("#reviewBody")
    check("admin duyệt thấy đề", "Bộ đề: Đề Quản Trị" in shown and "Câu hỏi trong bộ đề?" in shown and "Lựa chọn đúng" in shown and "Lời giải chi tiết" in shown)
    sample = json.loads((ROOT / "sample/package/lessons/sample/lesson.json").read_text("utf-8"))
    missing = [t for q in sample["quiz"] for t in [q["q"], *q["options"], q.get("why", "")] if t and t not in shown]
    missing += [t for t in sample["summary"] if t not in shown]
    check("review shows every quiz option and explanation", not missing, missing[:3])
    check("review states there is no Internet option", "Internet" in boss.inner_text("#reviewDialog"))
    boss.screenshot(path=str(SHOTS / "admin-review.png"))
    boss.screenshot(path=str(SHOTS / "admin-review-1280.png"))
    an.goto(base + "/#library")
    an.wait_for_selector("#libMine .stream-row")
    commit_upload(an, add_test_to_zip(make_zip(work / "v2.zip", "bai-hoi", f"Bài {XSS}", content="# Bản hai, chưa ai đọc\n")))
    boss.click("#reviewApprove")
    boss.wait_for_selector("#reviewError:not([hidden])")
    check("approving text that changed is refused", "thay đổi" in boss.inner_text("#reviewError"))
    boss.click("#reviewClose")

    # Now it reads the new text and approves.
    boss.reload()
    boss.wait_for_selector("#pendingList .stream-row")
    boss.click("#pendingList [type=button]")
    boss.wait_for_selector("#reviewDialog[open]")
    check("review shows the new text", "Bản hai" in boss.inner_text("#reviewBody"))
    boss.click("#reviewApprove")
    boss.wait_for_selector("#pendingEmpty:not([hidden])")
    check("approved package leaves the queue", True)

    binh.goto(f"{base}/lesson/{key}", wait_until="networkidle")
    check("Ask appears after approval", binh.locator("#lessonAskBtn").is_visible())
    if not binh.locator("#askDock").is_visible():
        binh.click("#lessonAskBtn")
    binh.fill("#askInput", "Vì sao?")
    binh.click("#askSend")
    binh.wait_for_selector("text=Trả lời giả")
    check("learner gets an answer", len(SEEN) == calls + 1)
    check("lesson text reached the provider inside the data block", "Bản hai" in SEEN[-1]["body"]["messages"][0]["content"])

    # The thread is still there after a reload, with its formatting, and the next question follows on from it.
    binh.goto(f"{base}/lesson/{key}", wait_until="networkidle")
    if not binh.locator("#askDock").is_visible():
        binh.click("#lessonAskBtn")
    binh.wait_for_selector("#askThread .is-question")
    check("question survives a reload", binh.locator("#askThread .is-question").inner_text() == "Vì sao?")
    check("answer survives a reload with its formatting", binh.locator("#askThread .md-answer strong").inner_text() == "Trả lời giả")
    binh.wait_for_selector("#askThread mjx-container", state="attached")
    binh.fill("#askInput", "Còn gì nữa?")
    binh.click("#askSend")
    for _ in range(50):
        if binh.locator("#askThread .md-answer").count() == 2 and "Đang trả lời" not in binh.locator("#askThread").inner_text():
            break
        binh.wait_for_timeout(100)
    sent = SEEN[-1]["body"]["messages"]
    check("follow-up carries the earlier turn", [m["role"] for m in sent] == ["system", "user", "assistant", "user"] and sent[1]["content"] == "Vì sao?", [m["role"] for m in sent])

    # The app page shows the same thread, and what is asked there shows on the lesson page.
    binh.goto(f"{base}/#home", wait_until="networkidle")
    binh.wait_for_selector("#askThread .is-question", state="attached")
    check("app page shows the thread from the lesson page", binh.locator("#askThread .is-question").all_inner_texts() == ["Vì sao?", "Còn gì nữa?"], binh.locator("#askThread").inner_text())
    if not binh.locator("#askForm").is_visible():
        binh.click(".capsule-ask-btn")
    binh.fill("#askInput", "Từ trang app")
    binh.click("#askSend")
    binh.wait_for_selector("#askThread .md-answer >> nth=2")
    for _ in range(50):
        if "Đang trả lời" not in binh.locator("#askThread").inner_text():
            break
        binh.wait_for_timeout(100)
    sent = SEEN[-1]["body"]["messages"]
    check("app page follows on from the lesson page", len(sent) == 6 and sent[1]["content"] == "Vì sao?", [m["role"] for m in sent])
    binh.goto(f"{base}/lesson/{key}", wait_until="networkidle")
    binh.wait_for_selector("#askThread .is-question >> nth=2", state="attached")
    check("lesson page shows what was asked on the app page", binh.locator("#askThread .is-question").nth(2).inner_text() == "Từ trang app")

    # A thread too long for the panel on a phone: the input stays on screen, the panel opens on the last answer.
    binh.set_viewport_size({"width": 390, "height": 500})
    binh.wait_for_timeout(300)
    if not binh.locator("#askForm").is_visible():
        binh.click("#lessonAskBtn")
    binh.wait_for_timeout(400)
    spot = binh.evaluate("""() => {
        const b = id => document.getElementById(id).getBoundingClientRect();
        const dock = b('askDock'), last = document.getElementById('askThread').lastElementChild.getBoundingClientRect();
        return {input: b('askInput').bottom, send: b('askSend').bottom, bottom: dock.bottom, top: dock.top, last: last.top};
    }""")
    check("input stays on screen in a long thread", spot["input"] <= spot["bottom"] and spot["send"] <= spot["bottom"] + 1, spot)
    check("panel opens on the last answer", spot["top"] <= spot["last"] < spot["bottom"], spot)
    binh.set_viewport_size({"width": 390, "height": 844})
    binh.wait_for_timeout(300)
    if not binh.locator("#askForm").is_visible():
        binh.click("#lessonAskBtn")
    binh.wait_for_timeout(300)
    binh.screenshot(path=str(SHOTS / "ask-thread-390.png"))
    binh.set_viewport_size({"width": 1280, "height": 900})
    binh.wait_for_timeout(200)
    # The page's dialog handler accepts everything, so saying no needs its own stand-in.
    binh.evaluate("window.realConfirm = window.confirm; window.confirm = () => false")
    if not binh.locator("#askClear").is_visible():
        binh.click("#lessonAskBtn")
    binh.click("#askClear")
    binh.wait_for_timeout(200)
    check("dismissing the question keeps the thread", binh.locator("#askThread .is-question").count() == 3)
    binh.evaluate("window.confirm = window.realConfirm")
    binh.click("#askClear")
    binh.wait_for_selector("#askThread .is-question", state="detached")
    check("clear hides itself", not binh.locator("#askClear").is_visible())
    binh.goto(f"{base}/lesson/{key}", wait_until="networkidle")
    binh.wait_for_timeout(400)
    check("cleared stays cleared", binh.locator("#askThread .ask-bubble").count() == 0)
    if not binh.locator("#askDock").is_visible():
        binh.click("#lessonAskBtn")

    # Turning it off works at once, for a page already open too.
    boss.click("#packageList button:has-text('Tắt ô Hỏi')")
    boss.wait_for_selector("#packageList .meta-pill:has-text('đã tắt')")
    calls = len(SEEN)
    binh.fill("#askInput", "Câu sau khi tắt")
    binh.click("#askSend")
    binh.wait_for_selector("text=chưa được bật")
    check("off stops sending at once", len(SEEN) == calls)
    binh.goto(f"{base}/lesson/{key}", wait_until="networkidle")
    check("Ask is gone after reload", not binh.locator("#lessonAskBtn").is_visible())

    # A new version with other text goes back to the queue.
    call(an, "POST", f"/api/packages/{pid}/ask-request")
    boss.reload()
    boss.wait_for_selector("#pendingList .stream-row")
    boss.click("#pendingList [type=button]")
    boss.wait_for_selector("#reviewDialog[open]")
    boss.click("#reviewApprove")
    boss.wait_for_selector("#pendingEmpty:not([hidden])")
    an.goto(base + "/#library")
    an.wait_for_selector("#libMine .stream-row")
    commit_upload(an, add_test_to_zip(make_zip(work / "v3.zip", "bai-hoi", f"Bài {XSS}", content="# Bản ba\n")))
    boss.reload()
    boss.wait_for_selector("#pendingList .stream-row")
    check("changed text goes back to the queue", True)

    # A report reaches the admin, who removes the package.
    r = call(binh, "POST", f"/api/lessons/{key}/feedback", {"kind": "abuse", "target_type": "lesson", "text": f"Báo cáo {XSS}"})
    check("report accepted", r["status"] == 200, r)
    boss.reload()
    boss.wait_for_selector("#abuseList .stream-row")
    check("report reaches the admin as text", "Báo cáo <img" in boss.inner_text("#abuseList") and boss.evaluate("window.__xss") is None)
    layout(boss, base)
    boss.set_viewport_size({"width": 360, "height": 740})
    boss.goto(base + "/admin")
    boss.wait_for_selector("#pendingList .stream-row")
    boss.click("#pendingList [type=button]")
    boss.wait_for_selector("#reviewDialog[open]")
    box = boss.locator("#reviewDialog").bounding_box()
    check("review fits at 360", box["x"] > 0 and box["x"] + box["width"] < 360, box)
    boss.screenshot(path=str(SHOTS / "admin-review-360.png"))
    boss.click("#reviewClose")
    boss.set_viewport_size({"width": 1280, "height": 900})

    binh.goto(f"{base}/lesson/{key}", wait_until="networkidle")
    boss.click("#abuseList button:has-text('Gỡ package')")
    boss.wait_for_selector("#packagesEmpty:not([hidden])")
    check("package is removed", True)
    check("removal is logged with the reason", "Nội dung vi phạm" in boss.inner_text("#logList"))
    check("removal log carries no key", KEY not in boss.content())
    binh.reload()
    check("removed package is gone for the learner", binh.locator("iframe.lesson-iframe").count() == 0 and "Không mở được" in binh.locator("h1").inner_text())
    check("no page errors or CSP blocks", not errs, errs[:4])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=["chrome", "webkit"], default="chrome")
    args = parser.parse_args()
    SHOTS.mkdir(exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="learn-admin-"))
    port, ai_port = free_port(), free_port()
    base = f"http://127.0.0.1:{port}"
    threading.Thread(target=http.server.ThreadingHTTPServer(("127.0.0.1", ai_port), FakeAI).serve_forever, daemon=True).start()
    env = dict(os.environ, DATA_DIR=str(work / "data"), PACKAGES_DIR=str(work / "packages"), COOKIE_SECURE="0",
               PUBLIC_ORIGIN=base, LINK_SECRET="e2e-secret-e2e-secret-e2e-secret-e2e", PYTHONUTF8="1",
               KEY_ENCRYPTION_KEY=base64.urlsafe_b64encode(b"e" * 32).decode())
    for name in ("AI_API_KEY", "AI_BASE_URL"):
        env.pop(name, None)

    def cli(*a):
        return subprocess.run([sys.executable, "-m", "app.cli", *a], cwd=ROOT, env=env, capture_output=True, encoding="utf-8")

    temp = {n: cli("add-user", n).stdout.rsplit(": ", 1)[1].strip() for n in ("boss@example.com", "an@example.com", "binh@example.com", "cuong@example.com")}
    cli("set-admin", "boss@example.com", "on")
    srv = subprocess.Popen([sys.executable, "-c", LAUNCH, f"http://127.0.0.1:{ai_port}/v1", str(port)], cwd=ROOT, env=env)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/healthz", timeout=1)
                break
            except OSError:
                time.sleep(0.25)
        with sync_playwright() as p:
            br = p.webkit.launch() if args.browser == "webkit" else p.chromium.launch(channel="chrome")
            run(br, base, temp, work)
            br.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)
        shutil.rmtree(work, ignore_errors=True)
    print("FAILS:", len(FAILS), FAILS[:10], flush=True)
    print("shots:", SHOTS)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
