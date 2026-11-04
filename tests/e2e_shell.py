"""Real-browser checks for the app shell around lessons: titles and focus, top bar fit, the steps and what Done means,
coming back from a lesson page, the lesson page's theme, and replies that arrive late. Own temporary server and data.
  python tests/e2e_shell.py [--browser chrome|webkit]
"""
import argparse
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
NEW_PW = "ngựa vàng chạy qua cầu mây"
FAILS = []
DARK_STYLE = "<style>@media (prefers-color-scheme: dark){body{background:rgb(1,2,3)}}</style>"
FAB = '<button id="fab" type="button" style="position:fixed;right:18px;bottom:18px">Hỏi</button>'


def check(name, ok, info=""):
    print("OK  " if ok else "FAIL", name, "" if ok else str(info)[:220], flush=True)
    if not ok:
        FAILS.append(name)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def poll(fn, timeout=10, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        try:
            got = fn()
            if got:
                return got
        except Exception:
            pass
        time.sleep(step)
    return fn()


def make_package(dest):
    """Two lessons in one package. The second has the page's own Ask button, and both have dark rules."""
    root = pathlib.Path(tempfile.mkdtemp()) / "p"
    shutil.copytree(ROOT / "sample" / "package", root)
    shutil.copytree(root / "lessons" / "sample", root / "lessons" / "hai")
    pkg = json.loads((root / "package.json").read_text("utf-8"))
    pkg.update(slug="vo-app", title="Gói Vỏ App", lessons=["sample", "hai"])
    (root / "package.json").write_text(json.dumps(pkg), "utf-8")
    for name, title in (("sample", "Bài Một"), ("hai", "Bài Hai")):
        folder = root / "lessons" / name
        lesson = json.loads((folder / "lesson.json").read_text("utf-8"))
        cards = [{"id": f"{name}-c{i}", "q": f"Thẻ {name} {i}?", "a": f"Đáp {i}"} for i in range(5)]
        lesson.update(title=title, cards=cards, tracks={})
        for q in lesson.get("quiz", []):
            q["id"] = q["id"].replace("sample-", f"{name}-")
        (folder / "lesson.json").write_text(json.dumps(lesson), "utf-8")
        page = (folder / "page" / "index.html").read_text("utf-8").replace("</head>", DARK_STYLE + "</head>")
        if name == "hai":
            page = page.replace("</body>", FAB + "</body>")
        (folder / "page" / "index.html").write_text(page, "utf-8")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(root).as_posix())
    return dest


def login_first(pg, base, name, temp):
    pg.goto(base + "/")
    pg.wait_for_url("**/login*")
    pg.fill("#loginUser", name)
    pg.fill("#loginPass", temp)
    pg.click("#submitBtn")
    pg.wait_for_url("**/change-password*")
    pg.fill("#pass1", NEW_PW)
    pg.fill("#pass2", NEW_PW)
    pg.click("#submitBtn")
    pg.wait_for_selector("#screen-home.active")


def new_page(br, errs, width=1280, height=900, scheme="dark", state=None, phone=False):
    ctx = br.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce", color_scheme=scheme, storage_state=state, has_touch=phone, is_mobile=phone)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append("js: " + str(e)[:200]))
    pg.on("console", lambda m: errs.append("csp: " + m.text[:200]) if m.type == "error" and "Content Security Policy" in m.text else None)
    pg.on("dialog", lambda d: d.accept())
    return pg


NAV = """() => { const n = document.querySelector('.stage-nav'); if (!n || !n.offsetParent) return { hidden: true }; const nb = n.getBoundingClientRect();
  return { clipped: n.scrollWidth - n.clientWidth, over: Math.max(...[...n.children].map(c => c.getBoundingClientRect().right - nb.right)), ask: !!document.querySelector('.topbar-ask-btn').offsetParent }; }"""


def lesson_frame(pg):
    # pg.frames only updates while Playwright runs, so this waits with its call and not with time.sleep.
    for _ in range(100):
        found = next((f for f in pg.frames if "/s/" in f.url), None)
        if found:
            return found
        pg.wait_for_timeout(100)
    return None


def open_lesson(br, base, key, state, scheme, theme, errs):
    pg = new_page(br, errs, scheme=scheme, state=state)
    pg.add_init_script(f"try {{ localStorage.setItem('theme', '{theme}'); }} catch (e) {{}}")

    # This server has no AI key, which hides the app's Ask button; claim it is on, to see what the page's own button does.
    def ask_on(route):
        got = route.fetch()
        route.fulfill(response=got, json={**got.json(), "ask": True})
    pg.route("**/api/lessons/*/frame", ask_on)
    pg.goto(f"{base}/lesson/{key}")
    frame = lesson_frame(pg)
    frame.wait_for_selector("#send")
    pg.wait_for_timeout(200)
    return pg, frame


def run(br, base, temp, sample, hai):
    errs = []
    a = new_page(br, errs)
    login_first(a, base, "an@example.com", temp["an@example.com"])
    state = a.context.storage_state()
    a.wait_for_selector("#lessonList .stream-row")

    # Skip link, titles, focus after moving between screens.
    fresh = new_page(br, errs, state=state)
    fresh.goto(base + "/#home")
    fresh.wait_for_selector("#lessonList .stream-row")
    fresh.keyboard.press("Tab")
    check("phím Tab đầu tiên tới link bỏ qua", fresh.evaluate("document.activeElement.classList.contains('skip-link')"), fresh.evaluate("document.activeElement.className"))
    if fresh.locator(".skip-link").count():
        fresh.keyboard.press("Enter")
        check("link bỏ qua đưa focus vào màn đang mở", fresh.evaluate("document.activeElement.id") == "screen-home", fresh.evaluate("document.activeElement.id"))
    fresh.context.close()
    a.click(".stage-tab[data-nav=library]")
    a.wait_for_selector("#screen-library.active")
    check("tiêu đề tab theo màn", a.title() == "Thư viện | Học AI", a.title())
    check("đổi màn thì focus vào màn mới", a.evaluate("document.activeElement.id") == "screen-library", a.evaluate("document.activeElement.id"))

    # Library wording and semantics.
    row = a.locator("#libMine .stream-row").first
    row.wait_for()
    text = row.inner_text()
    check("Thư viện: Chia sẻ thay cho Share", "Chia sẻ" in text and "Share" not in text and "share" not in text, text)
    check("Thư viện: chưa có góp ý thì không có nút góp ý", row.locator("[data-act=lib-feedback]").count() == 0, text)
    check("Thư viện: heading tiếng Việt", "Được chia sẻ" in a.inner_text("#screen-library"))
    used = a.evaluate("(() => { const m = document.getElementById('libMeter').parentElement; return [m.getAttribute('role'), m.getAttribute('aria-valuenow'), m.getAttribute('aria-label')]; })()")
    check("thanh dung lượng là progressbar", used[0] == "progressbar" and used[1] is not None and used[2], used)
    up = a.evaluate("document.getElementById('upMeter').parentElement.getAttribute('role')")
    check("thanh tải lên là progressbar", up == "progressbar", up)
    admin_text = (ROOT / "web" / "admin.html").read_text("utf-8") + (ROOT / "web" / "static" / "admin.js").read_text("utf-8")
    check("một cách viết Xóa", "Xoá" not in admin_text and "xoá" not in admin_text)

    # Top bar at the widths where it was clipped, inside a lesson.
    a.click(".stage-tab[data-nav=home]")
    a.wait_for_selector("#lessonList .stream-row")
    # This server has no AI key, which hides Ask everywhere; take that away so the layout rules are what is measured.
    a.evaluate("document.body.classList.remove('no-ask')")
    check("ngoài bài vẫn có nút Hỏi ở thanh trên", a.evaluate(NAV).get("ask") is True, a.evaluate(NAV))
    a.locator("#lessonList .stream-row", has_text="Bài Một").locator("[data-act=start]").click()
    a.wait_for_selector("#screen-review.active")
    a.evaluate("document.body.classList.remove('no-ask')")
    for w in (1024, 1100, 1200, 1280, 1366, 1440):
        a.set_viewport_size({"width": w, "height": 800})
        a.wait_for_timeout(120)
        nav = a.evaluate(NAV)
        check(f"thanh trên không bị cắt trong bài ở {w} px", nav.get("clipped", 9) <= 1 and nav.get("over", 9) <= 1, nav)
        check(f"trong bài không có Hỏi trùng ở {w} px", nav.get("ask") is False, nav)
    a.set_viewport_size({"width": 1024, "height": 800})
    skip_h = a.evaluate("document.querySelector('.screen.active .flow-skip').getBoundingClientRect().height")
    check("nút Bỏ qua không xuống dòng ở 1024 px", skip_h < 48, skip_h)
    names = a.evaluate("[...document.querySelectorAll('[data-nav=tests], [data-nav=library]')].filter(e => e.closest('.stage-nav')).map(e => e.getAttribute('aria-label'))")
    check("tab thanh trên luôn có tên", set(names) == {"Thư viện", "Bộ đề"}, names)
    a.set_viewport_size({"width": 1280, "height": 900})

    # Steps, with reading as the last one. This package has no audio.
    steps = a.evaluate("[...document.querySelector('#screen-review .flow-steps').children].map(e => e.textContent.trim())")
    check("các bước gồm cả Đọc bài", steps == ["1. Ôn lại", "2. Flashcard", "3. Đọc bài"], steps)
    href = a.evaluate("document.querySelector('#screen-review .flow-steps a')?.getAttribute('href')")
    check("bước Đọc bài mở đúng bài", href == f"/lesson/{sample}", href)

    # Coming back from the lesson page returns to where you were.
    a.locator("#screen-review a[data-article]").first.click()
    a.wait_for_url("**/lesson/**")
    lesson_frame(a).wait_for_selector("#send")
    a.click(".lesson-back")
    a.wait_for_selector("#screen-review.active")
    check("Về app quay lại đúng màn, đúng bài", a.evaluate("state.lesson.id") == sample and a.evaluate("document.body.classList.contains('in-lesson')"), a.evaluate("state.lesson.id"))

    # Late or doubled inputs on flashcards.
    a.evaluate("go('flashcard')")
    a.wait_for_selector("#fcCard:not([hidden])")
    check("màn thẻ nói rõ là thẻ của mọi bài", a.locator("#fcScope").count() == 1 and "mọi bài" in a.inner_text("#fcScope"))
    posts = []
    a.on("request", lambda r: posts.append(r.url) if r.method == "POST" and "/review" in r.url else None)
    a.keyboard.press("Space")
    a.wait_for_selector("#fcAnswerPane:not([hidden])")
    a.evaluate("() => { rateCard(3); rateCard(3); }")
    poll(lambda: a.evaluate("state.reviewed") >= 1)
    a.wait_for_timeout(300)
    check("bấm chấm hai lần chỉ tính một", len(posts) == 1 and a.evaluate("state.idx") == 1, [len(posts), a.evaluate("state.idx")])

    # An audio error no longer pulls you off the screen you are on.
    a.evaluate("() => { audio.src = '/static/none.mp3'; audio.dispatchEvent(new Event('error')); }")
    a.wait_for_timeout(100)
    check("lỗi audio không đá sang màn khác", a.evaluate("location.hash") == "#flashcard" and a.locator("#screen-flashcard.active").count() == 1, a.evaluate("location.hash"))
    check("lỗi audio có báo", "Không tải được" in a.evaluate("document.getElementById('dockNote').textContent"), a.evaluate("document.getElementById('dockNote').textContent"))
    a.evaluate("() => { audio.removeAttribute('src'); }")

    # Second lesson: finish the steps without reading it. Not done yet, and the screen says what is left.
    a.goto(base + "/#home")
    a.wait_for_selector("#lessonList .stream-row")
    a.locator("#lessonList .stream-row", has_text="Bài Hai").locator("[data-act=start]").click()
    a.wait_for_selector("#screen-review.active")
    a.evaluate("() => finish()")
    a.wait_for_selector("#screen-finish.active")
    finish_text = a.inner_text("#screen-finish")
    check("chưa đọc bài thì chưa ghi Đã xong", "Đã xong" not in finish_text and "Còn một bước" in finish_text, finish_text)
    main_btn = a.locator("#screen-finish .finish-cta .btn-studio-primary:visible")
    check("nút chính là đọc bài", main_btn.count() == 1 and main_btn.get_attribute("data-article") is not None, main_btn.count())
    api_lesson = lambda key: next(x for x in a.evaluate("async () => (await (await fetch('/api/lessons')).json()).lessons") if x["id"] == key)
    check("server vẫn ghi đang học", api_lesson(hai)["status"] == "in_progress", api_lesson(hai)["status"])
    a.goto(base + "/#home")
    a.wait_for_selector("#lessonList .stream-row")
    row_text = a.locator("#lessonList .stream-row", has_text="Bài Hai").inner_text()
    check("danh sách ghi rõ còn đọc bài", "chưa đọc bài" in row_text, row_text)
    check("không còn chữ thẻ đến hạn", "đến hạn" not in a.inner_text("#screen-home"), a.inner_text("#screen-home"))

    # Reading it completes the lesson, and coming back from there lands on the finish screen.
    a.locator("#lessonList .stream-row", has_text="Bài Hai").locator("[data-act=start]").click()
    a.wait_for_selector("#screen-review.active")
    a.evaluate("() => finish()")
    a.wait_for_selector("#screen-finish.active")
    a.locator("#screen-finish a[data-article]").click()
    a.wait_for_url("**/lesson/**")
    lesson_frame(a).wait_for_selector("#send")
    check("mở trang bài thì xong bài", api_lesson(hai)["status"] == "done", api_lesson(hai)["status"])
    a.click(".lesson-back")
    a.wait_for_selector("#screen-finish.active")
    poll(lambda: "Đã xong" in a.inner_text("#screen-finish"))
    check("quay lại màn kết thúc ghi Đã xong", "Đã xong" in a.inner_text("#screen-finish"), a.inner_text("#screen-finish"))
    check("bài cuối thì không có nút bài tiếp theo", a.locator("#screen-finish [data-act=start]:visible").count() == 0)

    # The lesson before it offers the next one once read. Bài Một was opened above.
    a.goto(base + "/#home")
    a.wait_for_selector("#lessonList .stream-row")
    a.locator("#lessonList .stream-row", has_text="Bài Một").locator("[data-act=start]").click()
    a.wait_for_selector("#screen-review.active")
    a.evaluate("() => finish()")
    a.wait_for_selector("#screen-finish.active")
    next_btn = a.locator("#screen-finish .finish-cta [data-act=start]")
    check("xong bài thì nút chính là học bài tiếp theo",
          next_btn.count() == 1 and next_btn.get_attribute("data-lesson") == hai and "btn-studio-primary" in next_btn.get_attribute("class") and "Bài 2" in next_btn.inner_text(), next_btn.count())

    # Lesson pages follow the app's theme, not the operating system's.
    for scheme, theme, want_dark in (("dark", "light", False), ("light", "dark", True)):
        pg, frame = open_lesson(br, base, hai, state, scheme, theme, errs)
        bg = frame.evaluate("getComputedStyle(document.body).backgroundColor")
        check(f"hệ điều hành {scheme}, app {theme}: trang bài theo app", (bg == "rgb(1, 2, 3)") == want_dark and f"/theme-{theme}/" in frame.url, [bg, frame.url])
        pg.context.close()

    # One Ask button: the page's own when it has one, the app's otherwise.
    pg, frame = open_lesson(br, base, hai, state, "dark", "dark", errs)
    pad = frame.evaluate("document.body.style.paddingBottom")
    check("trang có nút Hỏi riêng: ẩn nút trùng, chừa chỗ cuối trang", pg.evaluate("document.getElementById('lessonAskBtn').hidden") and pad == "72px", pad)
    pg.context.close()
    pg, frame = open_lesson(br, base, sample, state, "dark", "dark", errs)
    check("trang không có nút riêng: giữ nút của app", not pg.evaluate("document.getElementById('lessonAskBtn').hidden"))

    # A failed older save of the learner's notes must not win over what they wrote after it.
    pg.evaluate("""() => {
        const real = window.fetch;
        window.fetch = (u, o) => {
            if (String(u).startsWith('/api/doc/') && o && o.method === 'PUT' && !window.__held) {
                window.__held = String(u);
                return new Promise((_, rej) => { window.__fail = () => rej(new TypeError('offline')); });
            }
            return real(u, o);
        };
    }""")
    frame.evaluate("window.LearnBridge.call('doc.set', { data: { v: 1 } })")
    poll(lambda: pg.evaluate("!!window.__fail"), timeout=8)
    frame.evaluate("window.LearnBridge.call('doc.set', { data: { v: 2 } })")
    pg.wait_for_timeout(200)
    pg.evaluate("window.__fail()")
    url = pg.evaluate("window.__held")
    saved = poll(lambda: (lambda d: d if d and d.get("v") == 2 else None)(pg.evaluate("async url => (await (await fetch(url)).json()).data", url)), timeout=12)
    check("ghi chú mới không bị bản cũ lỗi đè", saved and saved.get("v") == 2, saved)
    pg.context.close()

    # A person with nothing yet: the way forward is the library.
    b = new_page(br, errs)
    login_first(b, base, "binh@example.com", temp["binh@example.com"])
    b.wait_for_selector("#homeEmptyCta:not([hidden])")
    cta = b.evaluate("[...document.querySelectorAll('#homeEmptyCta > *')].map(e => [e.textContent.trim(), e.classList.contains('btn-studio-primary')])")
    check("trang đầu trống: nút chính là Mở Thư viện", cta and cta[0] == ["Mở Thư viện", True] and cta[1][1] is False, cta)
    b.context.close()

    # Phone: the last tab opens a menu and says so.
    ph = new_page(br, errs, 390, 844, state=state, phone=True)
    ph.goto(base + "/#home")
    ph.wait_for_selector("#screen-home.active")
    label = ph.inner_text(".capsule-menu-btn").strip()
    check("tab cuối trên điện thoại là Menu", label == "Menu" and ph.get_attribute(".capsule-menu-btn", "aria-label") == "Menu", label)
    ph.click(".capsule-menu-btn")
    ph.wait_for_selector("#navDrawer.open")
    ph.wait_for_timeout(350)  # it slides in
    check("menu có Đăng xuất", ph.locator("#navDrawer [data-act=logout]").is_visible())
    ph.click(".drawer-close-btn")
    for w in (360, 390):
        ph.set_viewport_size({"width": w, "height": 740})
        ph.wait_for_timeout(100)
        over = ph.evaluate("document.documentElement.scrollWidth - innerWidth")
        check(f"không tràn ngang ở {w} px", over <= 0, over)
    ph.context.close()

    check("console sạch", not errs, errs[:4])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=["chrome", "webkit"], default="chrome")
    args = parser.parse_args()
    work = pathlib.Path(tempfile.mkdtemp(prefix="learn-shell-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, DATA_DIR=str(work / "data"), PACKAGES_DIR=str(work / "packages"), COOKIE_SECURE="0",
               PUBLIC_ORIGIN=base, LINK_SECRET="e2e-secret-e2e-secret-e2e-secret-e2e", PYTHONUTF8="1")
    env.pop("AI_API_KEY", None)

    def cli(*a):
        return subprocess.run([sys.executable, "-m", "app.cli", *a], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")

    temp = {n: cli("add-user", n).stdout.rsplit(": ", 1)[1].strip() for n in ("an@example.com", "binh@example.com")}
    pid = cli("import-package", str(make_package(work / "shell.zip")), "an@example.com").stdout.strip().splitlines()[-1].strip()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/healthz", timeout=1)
                break
            except OSError:
                time.sleep(0.25)
        with sync_playwright() as p:
            br = p.webkit.launch() if args.browser == "webkit" else p.chromium.launch(channel="chrome")
            run(br, base, temp, f"{pid}.sample", f"{pid}.hai")
            br.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)
        shutil.rmtree(work, ignore_errors=True)
    print("FAILS:", len(FAILS), FAILS[:12], flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
