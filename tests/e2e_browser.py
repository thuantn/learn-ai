"""Whole-app check in real Chrome against a local server and a stub AI. Not run in CI, because it needs real lesson content.

  python tests/e2e_browser.py PACKAGE_DIR
"""
import http.server
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = pathlib.Path(sys.argv[1]).resolve()
PORT, AI_PORT = 8790, 8791
BASE = f"http://127.0.0.1:{PORT}"
SHOTS = pathlib.Path(tempfile.gettempdir()) / "learn-ai-shots"
SHOTS.mkdir(exist_ok=True)
fails = []
seen_ai = []


def check(name, ok, info=""):
    if not ok:
        fails.append(name)
    print("OK  " if ok else "FAIL", name, str(info)[:220] if not ok or info else "", flush=True)


class FakeAI(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        seen_ai.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        text = "**Đúng**: công thức \\( J(w,b) \\) đo sai số.\n\n- Ý một\n\n<script>window.pwned=1</script><img src=x onerror=\"window.pwned=2\">"
        out = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


threading.Thread(target=http.server.ThreadingHTTPServer(("127.0.0.1", AI_PORT), FakeAI).serve_forever, daemon=True).start()
data = tempfile.mkdtemp(prefix="learn-e2e-")
env = dict(os.environ, DATA_DIR=data, PACKAGES_DIR=os.path.join(data, "packages"), LINK_SECRET="e2e-secret-e2e-secret-e2e-secret", COOKIE_SECURE="0", PUBLIC_ORIGIN=BASE, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
           AI_API_KEY="stub", AI_BASE_URL=f"http://127.0.0.1:{AI_PORT}/v1")
add = subprocess.run([sys.executable, "-m", "app.cli", "add-user", "an@example.com"], cwd=ROOT, env=env, capture_output=True, encoding="utf-8")
temp = add.stdout.rsplit(": ", 1)[1].strip()
archive = os.path.join(data, "package.zip")
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(PACKAGE.rglob("*")):
        if f.is_file():
            z.write(f, f.relative_to(PACKAGE).as_posix())
imported = subprocess.run([sys.executable, "-m", "app.cli", "import-package", archive, "an@example.com"], cwd=ROOT, env=env, capture_output=True, encoding="utf-8")
PACKAGE_ID = imported.stdout.strip().splitlines()[-1]
with sqlite3.connect(os.path.join(data, "learn.db")) as c:
    c.execute("UPDATE packages SET ask_status='approved' WHERE id=?", (PACKAGE_ID,))
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"], cwd=ROOT, env=env)
for _ in range(50):
    try:
        urllib.request.urlopen(BASE + "/healthz", timeout=1)
        break
    except OSError:
        time.sleep(0.2)
L2 = json.loads((PACKAGE / "lessons" / "bai02" / "lesson.json").read_text(encoding="utf-8-sig"))
L2_KEY = f"{PACKAGE_ID}.bai02"
NEW_PW = "ngựa vàng chạy qua cầu mây"


def wait_js(page, expr, seconds=15):
    # page.wait_for_function evaluates a string in the page, which the app's CSP correctly refuses.
    end = time.time() + seconds
    while not page.evaluate(expr):
        if time.time() > end:
            raise TimeoutError(expr)
        page.wait_for_timeout(100)


def watch(pg, errs):
    pg.on("pageerror", lambda e: errs.append("js: " + str(e)))
    pg.on("console", lambda m: errs.append(f"console: {m.text[:50]} @ {m.location} on {pg.url} screen={pg.evaluate('document.querySelector(\".screen.active\")?.id')}") if m.type == "error" and "401" not in m.text and "purify.min.js" not in m.location["url"] else None)  # purify trips CSP while stripping the hostile onerror the stub sends; "cannot run script" checks it never ran


try:
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
        ctx = br.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        outside = []
        ctx.route(re.compile(rf"^https?://(?!127\.0\.0\.1:{PORT})"), lambda r: (outside.append(r.request.url), r.abort()))
        pg = ctx.new_page()
        errs = []
        watch(pg, errs)

        pg.goto(BASE + "/")
        check("sent to login", pg.url.endswith("/login"), pg.url)
        check("login page has no app shell", pg.locator(".studio-dock").count() == 0)
        pg.fill("#loginUser", "an@example.com")
        pg.fill("#loginPass", "sai mật khẩu rồi nhé")
        pg.click("#submitBtn")
        pg.wait_for_selector("#alertBox.error")
        check("wrong password message", "Sai tên đăng nhập" in pg.inner_text("#alertBox"))
        errs.clear()
        pg.fill("#loginPass", temp)
        pg.click("#submitBtn")
        pg.wait_for_url("**/change-password")
        pg.goto(BASE + "/")
        check("temp password cannot enter app", pg.url.endswith("/change-password"), pg.url)
        pg.fill("#pass1", "ngắn")
        pg.fill("#pass2", "ngắn")
        pg.click("#submitBtn")
        check("short password refused", "15" in pg.inner_text("#alertBox"))
        pg.fill("#pass1", "passwordpassword")
        pg.fill("#pass2", "passwordpassword")
        pg.click("#submitBtn")
        wait_js(pg, "document.querySelector('#alertBox').textContent.includes('dễ đoán')")
        errs.clear()
        pg.fill("#pass1", NEW_PW)
        pg.fill("#pass2", NEW_PW)
        pg.click("#submitBtn")
        pg.wait_for_url(BASE + "/")
        pg.wait_for_selector("#screen-home.active")
        n_lessons = len(json.loads((PACKAGE / "package.json").read_text(encoding="utf-8-sig"))["lessons"])
        check("every lesson listed", pg.locator("#lessonList .stream-row").count() == n_lessons)
        check("no due cards before starting", "Không có thẻ" in pg.inner_text(".dock-foot"), pg.inner_text(".dock-foot"))

        pg.locator(f'#lessonList [data-lesson="{L2_KEY}"]').click()
        pg.wait_for_selector("#screen-review.active")
        check("summary shown", pg.locator("#summary .summary-band").count() == len(L2["summary"]))
        pg.get_by_role("button", name="Tiếp tục: Nghe podcast").click()
        pg.wait_for_selector("#screen-listen.active")
        total = pg.locator('#screen-listen [data-time="total"]').inner_text()
        check("long version length", total in ("22:59", "23:00"), total)

        # Real audio: play, seek, come back after reload at the same place.
        pg.locator("#screen-listen").get_by_role("button", name="Phát", exact=True).click()
        pg.wait_for_timeout(2500)
        state = pg.evaluate("({t:audio.currentTime,paused:audio.paused,err:audio.error&&audio.error.code})")
        check("audio really plays", state["t"] > 0 and not state["paused"] and state["err"] is None, state)
        pg.evaluate("audio.currentTime=524")
        pg.wait_for_timeout(1500)
        pg.locator("#screen-listen").get_by_role("button", name="Dừng", exact=True).click()
        pg.wait_for_timeout(500)
        pg.reload()
        pg.wait_for_selector("#screen-listen.active")
        check("position restored", pg.locator('#screen-listen [data-time="now"]').inner_text().startswith(("8:4", "8:5")), pg.locator('#screen-listen [data-time="now"]').inner_text())
        pg.keyboard.press("ArrowRight")
        pg.wait_for_timeout(600)
        check("arrow key seeks", pg.evaluate("Math.round(pendingSeek ?? audio.currentTime)") > 530)
        pg.locator('#screen-listen [data-track="short"]').click()
        total = pg.locator('#screen-listen [data-time="total"]').inner_text()
        check("short version length", total in ("6:45", "6:46"), total)
        pg.locator('#screen-listen [data-track="long"]').click()

        # Ask box: formula renders, hostile HTML does not run.
        pg.fill("#askInput", "Vì sao cập nhật đồng thời?")
        pg.click("#askSend")
        pg.wait_for_selector(".md-answer strong")
        pg.wait_for_timeout(1500)
        check("ask renders formula", pg.locator(".md-answer mjx-container").count() >= 1, pg.inner_html(".md-answer")[:200])
        check("AI output cannot run script", pg.evaluate("window.pwned") is None and pg.locator(".md-answer script").count() == 0)
        check("server added context and ZDR", seen_ai and seen_ai[-1]["messages"][0]["role"] == "system" and seen_ai[-1]["provider"] == {"zdr": True})

        pg.get_by_role("button", name="Tiếp tục: Flashcard").click()
        pg.wait_for_selector("#screen-flashcard.active")
        wait_js(pg, "document.querySelector('#fcQuestion').textContent.length>0")
        check("cards of this lesson only", len(pg.evaluate("state.cards")) == len(L2["cards"]), len(pg.evaluate("state.cards")))
        pg.screenshot(path=SHOTS / "desktop-card.png")
        pg.keyboard.press("Space")
        check("space reveals answer", pg.locator("#fcAnswerPane").is_visible())
        pg.keyboard.press("1")
        wait_js(pg, "state.idx===1")
        for i in range(1, len(L2["cards"])):
            pg.get_by_role("button", name="Hiện đáp án").click()
            pg.get_by_role("button", name="Dễ").click()
            wait_js(pg, f"state.idx==={i + 1} || document.querySelector('#screen-finish.active')")
        pg.wait_for_selector("#screen-finish.active")
        check("finish shows counts", str(len(L2["cards"])) in pg.inner_text("#finishNote"), pg.inner_text("#finishNote"))
        pg.get_by_role("button", name="Về trang đầu").click()
        pg.wait_for_selector("#screen-home.active")

        # Phone sizes and themes.
        for w, h in ((360, 720), (390, 844), (768, 1000), (1024, 768), (1440, 900), (1920, 1080)):
            pg.set_viewport_size({"width": w, "height": h})
            for dark in (True, False):
                pg.evaluate("t=>document.documentElement.setAttribute('data-theme',t)", "dark" if dark else "light")
                for s in ("home", "library", "review", "listen", "flashcard", "finish"):
                    pg.evaluate("s=>go(s)", s)
                    pg.wait_for_timeout(150)
                    over = pg.evaluate("document.documentElement.scrollWidth-document.documentElement.clientWidth")
                    check(f"{w} {s} no sideways", over <= 0, over) if over > 0 else None
                    if w < 768:
                        small = pg.evaluate("""()=>[...document.querySelectorAll('.screen.active button,.screen.active a,.mobile-floating-capsule button')]
                          .filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&(r.height<44||r.width<40)})
                          .map(e=>(e.getAttribute('aria-label')||e.innerText).trim().slice(0,20)+' '+Math.round(e.getBoundingClientRect().width)+'x'+Math.round(e.getBoundingClientRect().height))""")
                        check(f"{w} {s} touch targets", not small, small) if small else None
                        covered = pg.evaluate("""()=>{const y=document.documentElement.scrollHeight;window.scrollTo(0,y);const c=document.querySelector('.mobile-floating-capsule').getBoundingClientRect();
                          const hit=[...document.querySelectorAll('.screen.active button,.screen.active a')].filter(e=>{const r=e.getBoundingClientRect();return r.height>0&&r.bottom>c.top&&r.top<c.bottom});window.scrollTo(0,0);return hit.map(e=>e.innerText)}""")
                        check(f"{w} {s} dock covers nothing at end of page", not covered, covered) if covered else None
                    if w in (390, 1440):
                        pg.screenshot(path=SHOTS / f"{w}-{'dark' if dark else 'light'}-{s}.png", full_page=True)
        pg.set_viewport_size({"width": 1440, "height": 900})
        pg.evaluate("document.documentElement.setAttribute('data-theme','dark')")

        check("no outside requests", not outside, outside[:3])
        check("no page errors", not errs, errs[:3])

        pg.evaluate("go('home')")
        pg.click("#accountMenu summary")
        pg.get_by_role("button", name="Đăng xuất").first.click()
        pg.wait_for_url("**/login")
        pg.goto(BASE + "/api/me")
        check("logout ends session", "login" in pg.inner_text("body") or pg.url.endswith("/login"))
        br.close()
finally:
    srv.terminate()
    srv.wait(10)
print("FAILS:", len(fails))
for f in fails:
    print(" ", f)
print("shots:", SHOTS)
