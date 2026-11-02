"""Browser attack + real-lesson checks for the sandbox. Not collected by pytest.

  python tests/e2e_sandbox.py PACKAGES_DIR CONTENT_DIR --browser chrome|webkit|firefox
"""
import argparse
import http.server
import json
import os
import pathlib
import re
import secrets
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORT = 8792
OUTSIDE_PORT = 8793
BASE = f"http://127.0.0.1:{PORT}"
OUTSIDE = f"http://127.0.0.1:{OUTSIDE_PORT}"
SHOTS = pathlib.Path(tempfile.gettempdir()) / "learn-ai-sandbox-shots"
SHOTS.mkdir(exist_ok=True)
USER = "an@example.com"
NEW_PW = "ngựa vàng chạy qua cầu mây"
FAILS = []
OUTSIDE_REQUESTS = []


def check(name, ok, info=""):
    if not ok:
        FAILS.append(name)
    print("OK  " if ok else "FAIL", name, str(info)[:220] if not ok or info else "", flush=True)


def record(name, value):
    print("REC", name, str(value)[:220], flush=True)


class StubOutside(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def _handle(self):
        OUTSIDE_REQUESTS.append(self.path)
        if self.path.startswith("/v1/chat/completions") and self.command == "POST":
            text = "**Đúng**: công thức \\( J(w,b) \\) đo sai số.\n\n- Ý một\n\n<script>window.pwned=1</script><img src=x onerror=\"window.pwned=2\">"
            out = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def start_outside_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", OUTSIDE_PORT), StubOutside)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def wait_js(page, expr, seconds=15):
    end = time.time() + seconds
    while not page.evaluate(expr):
        if time.time() > end:
            raise TimeoutError(expr)
        page.wait_for_timeout(100)


def watch(pg, errs):
    pg.on("pageerror", lambda e: errs.append("js: " + str(e)))
    pg.on("console", lambda m: errs.append(f"console: {m.text[:50]} @ {m.location} on {pg.url}") if m.type == "error" and "401" not in m.text and "Load failed" not in m.text and "purify.min.js" not in m.location.get("url", "") else None)  # Load failed: WebKit reports fetches cut short by leaving a page


def make_env(data_dir, packages_dir, extras=None):
    env = dict(
        os.environ,
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
        DATA_DIR=str(data_dir),
        PACKAGES_DIR=str(packages_dir),
        COOKIE_SECURE="0",
        PUBLIC_ORIGIN=BASE,
        LINK_SECRET=secrets.token_urlsafe(24),
        AI_API_KEY="stub",
        AI_BASE_URL=f"{OUTSIDE}/v1",
    )
    if extras:
        env.update(extras)
    return env


def add_user(env):
    add = subprocess.run(
        [sys.executable, "-m", "app.cli", "add-user", USER],
        cwd=ROOT, env=env, capture_output=True, encoding="utf-8",
    )
    return add.stdout.rsplit(": ", 1)[1].strip()


def start_app(env):
    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=env,
    )
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/healthz", timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    return srv


def stop_app(srv):
    if srv is None:
        return
    srv.terminate()
    try:
        srv.wait(10)
    except subprocess.TimeoutExpired:
        srv.kill()


def login(page, temp_pw):
    page.goto(BASE + "/login")
    page.fill("#loginUser", USER)
    page.fill("#loginPass", temp_pw)
    page.click("#submitBtn")
    page.wait_for_url("**/change-password", timeout=5000)
    page.fill("#pass1", NEW_PW)
    page.fill("#pass2", NEW_PW)
    page.click("#submitBtn")
    page.wait_for_url(BASE + "/", timeout=10000)


def frame_for(page):
    for f in page.frames:
        if f.url.startswith(f"{BASE}/s/"):
            return f
    return None


def wait_frame(page, timeout=15):
    end = time.time() + timeout
    while True:
        f = frame_for(page)
        if f:
            return f
        if time.time() > end:
            raise TimeoutError("sandbox frame not found")
        page.wait_for_timeout(100)


def prepare_evil_packages():
    src = ROOT / "sample" / "evil"
    dest = pathlib.Path(tempfile.mkdtemp(prefix="learn-evil-pkg-"))
    shutil.copytree(src, dest / "evil")
    pkg = dest / "evil"
    audio_dir = pkg / "lessons" / "evil" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "tests" / "fixtures" / "tone.mp3", audio_dir / "a.mp3")
    return pkg


def install(env, package_dir, data_dir):
    """Zips a package and installs it for the test user through the real path. The Ask box is approved for it."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="learn-zip-"))
    archive = work / "package.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(pathlib.Path(package_dir).rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(package_dir).as_posix())
    out = subprocess.run([sys.executable, "-m", "app.cli", "import-package", str(archive), USER], cwd=ROOT, env=env, capture_output=True, encoding="utf-8")
    if out.returncode:
        raise RuntimeError(out.stdout + out.stderr)
    package_id = out.stdout.strip().splitlines()[-1]
    with sqlite3.connect(pathlib.Path(data_dir) / "learn.db") as c:
        c.execute("UPDATE packages SET ask_status='approved' WHERE id=?", (package_id,))
    shutil.rmtree(work, ignore_errors=True)
    return package_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package_dir", type=pathlib.Path, help="the real converted lessons, as an unpacked package")
    parser.add_argument("--browser", choices=["chrome", "webkit", "firefox"], default="chrome")
    args = parser.parse_args()

    outside_server = start_outside_server()
    app_proc = None

    try:
        with sync_playwright() as p:
            if args.browser == "chrome":
                browser = p.chromium.launch(channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
            elif args.browser == "webkit":
                browser = p.webkit.launch()
            else:
                browser = p.firefox.launch()

            # ---------- Phase EVIL ----------
            evil_pkg = prepare_evil_packages()
            data_dir = tempfile.mkdtemp(prefix="learn-evil-data-")
            env = make_env(data_dir, pathlib.Path(data_dir) / "packages")
            temp_pw = add_user(env)
            evil_id = install(env, evil_pkg, data_dir)
            evil_key, evilnav_key = f"{evil_id}.evil", f"{evil_id}.evilnav"
            app_proc = start_app(env)

            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
            page = ctx.new_page()
            errs = []
            watch(page, errs)
            doc_puts = []
            ask_reqs = []

            def on_request(req):
                if req.method == "PUT" and "/api/doc/" in req.url:
                    doc_puts.append(req.url)
                if req.method == "POST" and req.url.endswith("/api/ask"):
                    ask_reqs.append(req.url)

            page.on("request", on_request)
            login(page, temp_pw)

            page.goto(f"{BASE}/lesson/{evil_key}", wait_until="networkidle")
            frame = wait_frame(page)
            wait_js(page, "document.querySelector('#lessonTopBar') !== null")

            # Wait for attack results saved to evildoc.
            wait_js(page, f"""async () => {{
                const r = await fetch('/api/doc/{evil_key}', {{method:'GET'}});
                const j = await r.json();
                return !!(j.data && j.data.results);
            }}""", seconds=10)

            results = page.evaluate(f"""async () => {{
                const r = await fetch('/api/doc/{evil_key}', {{method:'GET'}});
                const j = await r.json();
                return j.data.results;
            }}""")

            must_blocked = {
                "cookie": lambda v: v == "" or str(v).startswith("err:"),
                "localStorage": lambda v: "blocked" in str(v) or "SecurityError" in str(v),
                "fetch_api_me": lambda v: v == "blocked",
                "fetch_outside": lambda v: v == "blocked",
                "xhr_outside": lambda v: v == "blocked",
                "beacon_outside": lambda v: True,  # sendBeacon may report true while CSP drops it; the stub below decides
                "img_outside": lambda v: v == "blocked",
                "script_outside": lambda v: v == "blocked",
                "css_outside": lambda v: v == "blocked",
                "form_outside": lambda v: True,
                "window_open": lambda v: v == "blocked",
                "top_location": lambda v: "blocked" in str(v),
                "parent_location": lambda v: "blocked" in str(v),
            }
            outside_paths = ["/fetch", "/xhr", "/beacon", "/img", "/script.js", "/css", "/form", "/open", "/top", "/parent"]
            for name, pred in must_blocked.items():
                val = results.get(name)
                check(f"attack {name} blocked", pred(val), val)
            for opath in outside_paths:
                check(f"outside not reached {opath}", not any(r.startswith(opath) for r in OUTSIDE_REQUESTS), [r for r in OUTSIDE_REQUESTS if r.startswith(opath)][:1])

            check("top bar still visible", page.locator("#lessonTopBar").is_visible())
            me_ok = page.evaluate("""async () => {
                const r = await fetch('/api/me', {method:'GET'});
                return r.status === 200;
            }""")
            check("app page /api/me still works", me_ok)
            check("doc.set flood under 10 PUTs", len(doc_puts) < 10, len(doc_puts))
            check("no PUT to doc 'other'", not any("/api/doc/other" in u for u in doc_puts), [u for u in doc_puts if "/api/doc/other" in u])
            check("doc.get other returned only evildoc", results.get("doc_get_other") is None, results.get("doc_get_other"))

            # ask.open
            ask_val = page.input_value("#askInput")
            check("ask.open prefilled input", ask_val == "dien san", ask_val)
            check("no /api/ask before send", len(ask_reqs) == 0, len(ask_reqs))
            page.click("#askSend")
            wait_js(page, "document.getElementById('askSend').disabled === false", seconds=15)
            check("exactly one /api/ask after send", len(ask_reqs) == 1, len(ask_reqs))

            # Bad messages must not crash the host.
            js_errs = [e for e in errs if e.startswith("js:") and "attempting navigation" not in e and "/s/" not in e]  # CSP refusals of the attack page are the point
            check("no pageerror from bad messages", not js_errs, js_errs[:3])

            # Link dialog checks.
            new_pages = []
            ctx.on("page", lambda p: new_pages.append(p))

            frame.click("#ext")
            wait_js(page, "document.getElementById('lessonDialog').open")
            dialog_text = page.locator("#lessonDialogText").inner_text()
            check("https link shows address", "example.org/x" in dialog_text, dialog_text)
            page.get_by_role("button", name="Hủy").click()
            page.wait_for_timeout(200)
            check("cancel closes dialog", not page.locator("#lessonDialog").is_visible())
            check("https cancel did not open new page", len(new_pages) == 0, len(new_pages))

            frame.click("#plain")
            wait_js(page, "document.getElementById('lessonDialog').open")
            dialog_text = page.locator("#lessonDialogText").inner_text()
            check("http link shows unsafe line", "không an toàn" in dialog_text, dialog_text)
            check("http link has no Open button", page.locator("#lessonDialogOk").is_hidden())
            page.get_by_role("button", name="Hủy").click()
            page.wait_for_timeout(200)

            # Direct /s/ access.
            token_url = page.evaluate("""async (key) => {
                const r = await fetch('/api/lessons/' + key + '/frame', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
                const j = await r.json();
                return j.url;
            }""", evil_key)
            direct = ctx.new_page()
            try:  # Chrome reports an empty 403 as a navigation error
                status = direct.goto(BASE + token_url, wait_until="domcontentloaded").status
            except Exception as exc:
                status = 403 if "ERR_HTTP_RESPONSE_CODE_FAILURE" in str(exc) else str(exc)[:80]
            check("direct /s/ html in tab returns 403", status == 403, status)
            direct.close()

            svg_url = token_url.replace("page/index.html", "page/x.svg")
            svg_page = ctx.new_page()
            svg_page.goto(BASE + svg_url, wait_until="domcontentloaded")
            svg_global = svg_page.evaluate("() => window.svgGlobal")
            check("svg script did not run", svg_global is None, svg_global)
            svg_page.close()

            for bad_rel in [token_url.replace("page/index.html", "../lesson.json"), token_url.replace("/page/index.html", "/lesson.json")]:
                status = page.evaluate(f"async () => {{ const r = await fetch('{BASE}{bad_rel}'); return r.status; }}")
                check(f"traversal {bad_rel} returns 404", status == 404, status)

            # RTCPeerConnection result.
            record("RTCPeerConnection result", results.get("rtc"))

            # Self-navigation variant.
            page.goto(f"{BASE}/lesson/{evilnav_key}", wait_until="networkidle")
            page.wait_for_timeout(2200)
            nav_reached = any(r.startswith("/nav") for r in OUTSIDE_REQUESTS)
            cover_visible = page.locator("#lessonCover").is_visible()
            frame_present = page.locator("#lessonFrameWrap iframe").count() > 0
            record("self-navigation reached outside", nav_reached)
            if nav_reached:
                print("self-navigation reached the outside stub")
                check("evilnav closed frame on outside navigation", cover_visible, f"cover={cover_visible}")
            elif cover_visible:
                print("self-navigation blocked; app closed the frame")
                check("evilnav handled self-navigation", True)
            elif frame_present:
                print("self-navigation blocked; frame stayed in place")
                check("evilnav handled self-navigation", True)
            else:
                check("evilnav handled self-navigation", False, "no cover and no frame")

            ctx.close()
            stop_app(app_proc)
            app_proc = None

            # ---------- Expired token ----------
            data_dir_exp = tempfile.mkdtemp(prefix="learn-exp-data-")
            env_exp = make_env(data_dir_exp, pathlib.Path(data_dir_exp) / "packages", {"LINK_TTL_SECONDS": "3"})
            temp_pw_exp = add_user(env_exp)
            evil_exp = install(env_exp, evil_pkg, data_dir_exp)
            app_proc = start_app(env_exp)

            ctx_exp = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
            page_exp = ctx_exp.new_page()
            login(page_exp, temp_pw_exp)
            page_exp.goto(f"{BASE}/lesson/{evil_exp}.evil", wait_until="networkidle")
            frame_exp = wait_frame(page_exp)
            time.sleep(5.1)
            frame_exp.evaluate("""() => {
                const a = document.getElementById('au');
                a.src = '../audio/a.mp3?cb=' + Date.now();
                a.play().catch(() => {});
            }""")
            page_exp.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
            wait_js(page_exp, "document.getElementById('lessonCoverText').textContent.includes('hết hạn')", seconds=10)
            check("expired token notice visible", page_exp.locator("#lessonCover").is_visible())
            check("expired token notice text", "hết hạn" in page_exp.locator("#lessonCoverText").inner_text())
            ctx_exp.close()
            stop_app(app_proc)
            app_proc = None

            # ---------- Phase REAL ----------
            read_lesson = lambda lid: json.loads((args.package_dir / "lessons" / lid / "lesson.json").read_text(encoding="utf-8-sig")) | {"id": lid}
            bai01, bai02 = read_lesson("bai01"), read_lesson("bai02")

            data_dir_real = tempfile.mkdtemp(prefix="learn-real-data-")
            env_real = make_env(data_dir_real, pathlib.Path(data_dir_real) / "packages")
            temp_pw_real = add_user(env_real)
            real_id = install(env_real, args.package_dir, data_dir_real)
            app_proc = start_app(env_real)

            ctx_real = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
            page_real = ctx_real.new_page()
            errs_real = []
            watch(page_real, errs_real)
            login(page_real, temp_pw_real)

            for lesson in (bai01, bai02):
                if lesson is None:
                    continue
                lid = lesson["id"]
                page_real.goto(f"{BASE}/lesson/{real_id}.{lid}", wait_until="networkidle")
                frame_real = wait_frame(page_real)
                wait_js(page_real, "document.querySelector('#lessonTopBar') !== null")

                mjx_count = frame_real.locator("mjx-container").count()
                check(f"{lid} formulas render", mjx_count > 5, mjx_count)

                font_ok = frame_real.evaluate("document.fonts.check('16px \"Be Vietnam Pro\"')")
                record(f"{lid} font loaded", font_ok)

                # Wrong answer becomes a card.
                quiz = lesson.get("quiz", [])
                if quiz:
                    wrong_i = (quiz[0]["answer"] + 1) % len(quiz[0]["options"])
                    frame_real.locator("#qs .q").first.locator(".opt").nth(wrong_i).click()
                    page_real.wait_for_timeout(3000)
                    due = page_real.evaluate("async () => { const r = await fetch('/api/cards/due'); return (await r.json()).cards; }")
                    card = next((c for c in due if c["id"].endswith("-q0") and c["wrong"]), None)
                    check(f"{lid} wrong answer creates card", card is not None, [c["id"] for c in due])

                end = time.time() + 15
                while "tài khoản" not in (save_text := frame_real.locator("#save-state").inner_text()) and time.time() < end:
                    page_real.wait_for_timeout(300)
                check(f"{lid} save-state mentions account", "tài khoản" in save_text, save_text)

                audio_state = frame_real.evaluate("""async () => {
                    const a = document.querySelector('.pc audio');
                    if (!a) return {missing:true};
                    a.muted = true;
                    try { await a.play(); } catch(e) {}
                    await new Promise(r => setTimeout(r, 1200));
                    const ok1 = a.currentTime > 0;
                    a.currentTime = 100;
                    await new Promise(r => setTimeout(r, 1200));
                    return {t:a.currentTime, e:a.error && a.error.code, ok1};
                }""")
                check(f"{lid} audio plays and seeks", audio_state.get("ok1") and audio_state.get("t", 0) >= 99 and audio_state.get("e") is None, audio_state)

                # "Tự giải thích lại" prefills Ask.
                frame_real.locator(".askhere.explain").first.click()
                page_real.wait_for_timeout(300)
                ask_input = page_real.input_value("#askInput")
                check(f"{lid} explain prefills ask", ask_input.startswith("Tự giải thích lại"), ask_input[:60])

                # FAB opens Ask panel.
                frame_real.locator("#fab").click()
                page_real.wait_for_timeout(300)
                ask_open = page_real.locator("#askDock").evaluate("el => el.classList.contains('mobile-open')")
                check(f"{lid} fab opens ask panel", ask_open)

                # http link in bai02.
                if lid == "bai02":
                    frame_real.evaluate("document.querySelector('a[href^=\"http://\"]').click()")
                    wait_js(page_real, "document.getElementById('lessonDialog').open")
                    link_text = page_real.locator("#lessonDialogText").inner_text()
                    check("bai02 http link shows unsafe line", "không an toàn" in link_text, link_text)
                    page_real.get_by_role("button", name="Hủy").click()
                    page_real.wait_for_timeout(200)

            check("no pageerror on real lessons", not errs_real, errs_real[:3])

            page_real.evaluate("document.querySelector('.ask-close-mobile').click()")
            for w, h, side in ((360, 720, 0), (390, 844, 0), (1024, 768, 330), (1440, 900, 360)):
                page_real.set_viewport_size({"width": w, "height": h})
                page_real.wait_for_timeout(800)
                box = page_real.evaluate("(() => { const r = document.querySelector('.lesson-iframe').getBoundingClientRect(); return {w: r.width, h: r.height, over: document.documentElement.scrollWidth - innerWidth}; })()")
                check(f"frame fills {w}px", abs(box["w"] - (w - side)) <= 2 and box["h"] >= h - 80 and box["over"] <= 0, box)
                page_real.screenshot(path=SHOTS / f"real-{args.browser}-{w}.png")

            ctx_real.close()
            browser.close()

    finally:
        stop_app(app_proc)
        outside_server.shutdown()

    print("FAILS:", len(FAILS))
    for f in FAILS:
        print(" ", f)
    print("shots:", SHOTS)
    sys.exit(len(FAILS))


if __name__ == "__main__":
    main()
