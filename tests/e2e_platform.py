"""Real-browser checks for the library, upload, share and feedback. Own temporary server and data.
  python tests/e2e_platform.py [--browser chrome|webkit]
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
import urllib.request
import zipfile

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
NEW_PW = "ngựa vàng chạy qua cầu mây"
FAILS = []
SHOTS = pathlib.Path(tempfile.gettempdir()) / "learn-ai-platform-shots"
XSS = "<img src=x onerror=window.__xss=1>"
CARDS = [{"id": f"c{i}", "q": f"Thẻ {i}?", "a": f"Đáp {i}"} for i in range(5)]


def check(name, ok, info=""):
    print("OK  " if ok else "FAIL", name, "" if ok else str(info)[:200], flush=True)
    if not ok:
        FAILS.append(name)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_zip(dest, slug, title, tracks=None, cards=CARDS, content=None, extra_files=None):
    """Starts from the bridge sample, so the page and its quiz are real."""
    work = pathlib.Path(tempfile.mkdtemp())
    root = work / "p"
    shutil.copytree(ROOT / "sample" / "package", root)
    pkg = json.loads((root / "package.json").read_text("utf-8"))
    pkg.update(slug=slug, title=title)
    (root / "package.json").write_text(json.dumps(pkg), "utf-8")
    lesson_file = root / "lessons" / "sample" / "lesson.json"
    lesson = json.loads(lesson_file.read_text("utf-8"))
    lesson.update(title=title, cards=cards, tracks=tracks or {})
    lesson_file.write_text(json.dumps(lesson), "utf-8")
    if content:
        (root / "lessons" / "sample" / "content.md").write_text(content, "utf-8")
    if tracks:
        (root / "lessons" / "sample" / "audio").mkdir(exist_ok=True)
        for t in tracks.values():
            shutil.copy(ROOT / "tests" / "fixtures" / "tone.mp3", root / "lessons" / "sample" / "audio" / t["file"])
    if extra_files:
        for rel_path, data in extra_files.items():
            target = root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(root).as_posix())
    return dest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=["chrome", "webkit"], default="chrome")
    args = parser.parse_args()
    SHOTS.mkdir(exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="learn-platform-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, DATA_DIR=str(work / "data"), PACKAGES_DIR=str(work / "packages"), COOKIE_SECURE="0",
               PUBLIC_ORIGIN=base, LINK_SECRET="e2e-secret-e2e-secret-e2e-secret-e2e", PYTHONUTF8="1")
    env.pop("AI_API_KEY", None)

    def add_user(name):
        out = subprocess.run([sys.executable, "-m", "app.cli", "add-user", name], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
        return out.stdout.rsplit(": ", 1)[1].strip()

    temp = {n: add_user(n) for n in ("an@example.com", "binh@example.com", "cuong@example.com")}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/healthz", timeout=1)
                break
            except OSError:
                import time
                time.sleep(0.25)
        filler1 = os.urandom(4_500_000)
        filler2 = os.urandom(2_500_000)
        good = make_zip(work / "good.zip", "bai-mau", f"Bài {XSS}", extra_files={"lessons/sample/page/filler1.mp3": filler1})
        good2 = make_zip(work / "good2.zip", "bai-mau", f"Bài {XSS}", extra_files={
            "lessons/sample/page/filler1.mp3": filler1,
            "lessons/sample/page/filler2.mp3": filler2,
        })
        audio = make_zip(work / "audio.zip", "co-audio", "Bài có audio", tracks={"short": {"file": "s.mp3", "label": "Ngắn"}})
        bad = work / "bad.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("../evil.txt", "x")
        with sync_playwright() as p:
            br = p.webkit.launch() if args.browser == "webkit" else p.chromium.launch(channel="chrome")
            run(br, base, temp, good, audio, bad, good2=good2)
            br.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)
        shutil.rmtree(work, ignore_errors=True)
    print("FAILS:", len(FAILS), FAILS[:10], flush=True)
    print("shots:", SHOTS)
    return 1 if FAILS else 0


dialogs = []


def new_page(br, errs, width=1280, height=900):
    ctx = br.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce")
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append("js: " + str(e)[:160]))
    pg.on("console", lambda m: errs.append("csp: " + m.text[:160]) if m.type == "error" and "Content Security Policy" in m.text else None)
    pg.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    return pg


def login_first(pg, base, name, temp, path="/"):
    pg.goto(base + path)
    pg.wait_for_url("**/login*")
    pg.fill("#loginUser", name)
    pg.fill("#loginPass", temp)
    pg.click("#submitBtn")
    pg.wait_for_url("**/change-password*")
    pg.fill("#pass1", NEW_PW)
    pg.fill("#pass2", NEW_PW)
    pg.click("#submitBtn")


def upload(pg, path):
    pg.locator("#screen-library [data-act=lib-upload]").first.click()
    pg.set_input_files("#upFile", str(path))


def run(br, base, temp, good, audio, bad, good2=None):
    errs = []
    a = new_page(br, errs)
    login_first(a, base, "an@example.com", temp["an@example.com"])
    a.wait_for_url(base + "/**")

    # A new account has nothing yet.
    a.wait_for_selector("#screen-home.active")
    check("new account sees guidance", a.locator("#homeEmptyCta").is_visible() and "Chưa có" in a.locator("#home-title").inner_text())
    check("no start button yet", not a.locator("#homeCta").is_visible())
    check("no lesson tabs yet", not a.locator(".stage-tab[data-nav=review]").is_visible() and not a.locator(".stage-tab[data-article]").is_visible())
    a.screenshot(path=str(SHOTS / "empty.png"))
    for screen in ("review", "listen", "flashcard"):
        a.goto(f"{base}/#{screen}")
        a.wait_for_timeout(200)
        check(f"empty account: {screen} goes home", a.locator("#screen-home.active").count() == 1)
    check("empty account: screens do not crash", not errs, errs[:3])

    # A bad zip shows problems.
    a.goto(base + "/#library")
    a.wait_for_selector("#screen-library.active")
    upload(a, bad)
    a.wait_for_selector("#upError:not([hidden])")
    check("bad zip lists problems", a.locator("#upProblems li").count() > 0, a.locator("#upError").inner_text())
    a.screenshot(path=str(SHOTS / "upload-error.png"))
    a.click("#upError [data-act=up-close]")

    # A good zip needs the checkbox.
    parts_puts = []
    a.on("request", lambda r: parts_puts.append(r.url) if r.method == "PUT" and "/api/uploads/parts/" in r.url else None)
    dropped = []

    def drop_first_part(route):
        # The tunnel cuts requests at random: the first try of part 0 fails, the page must send it again.
        if route.request.method == "PUT" and route.request.url.endswith("/0") and not dropped:
            dropped.append(route.request.url)
            return route.abort("connectionreset")
        route.continue_()
    a.route("**/api/uploads/parts/**", drop_first_part)
    upload(a, good)
    try:
        a.wait_for_selector("#upConfirm:not([hidden])", timeout=30000)
    except Exception:
        print("DIALOG:", a.inner_text("#uploadDialog")[:400], "ERRS:", errs[:5], "PUTS:", parts_puts[:6])
        raise
    a.unroute("**/api/uploads/parts/**")
    part0 = [u for u in parts_puts if u.endswith("/0")]
    check("dialog upload used PUT parts, resent the dropped part and reached confirm", dropped and len(part0) >= 2 and a.locator("#upConfirm").is_visible(), parts_puts)
    check("confirm is locked until the box is ticked", a.locator("#upCommit").is_disabled())
    box = a.locator("#uploadDialog").bounding_box()
    check("dialog is centred", abs(box["x"] + box["width"] / 2 - 640) < 2, box)
    check("title shown as text", XSS in a.locator("#upTitle").inner_text())
    a.screenshot(path=str(SHOTS / "upload-confirm.png"))
    a.check("#upAttest")
    a.click("#upCommit")
    a.wait_for_selector("#libMine .stream-row")
    check("package appears in library", "Bài <img" in a.locator("#libMine").inner_text())
    a.screenshot(path=str(SHOTS / "library.png"))
    a.goto(base + "/#home")
    a.wait_for_selector("#lessonList .stream-row")
    check("package appears on home", a.locator("#lessonList .stream-row").count() == 1)
    check("package title did not run as HTML", a.evaluate("window.__xss") is None)

    # Upload second version of the same package that adds one file
    if good2 is None:
        with zipfile.ZipFile(good, "r") as z:
            f1 = z.read("lessons/sample/page/filler1.mp3") if "lessons/sample/page/filler1.mp3" in z.namelist() else os.urandom(4_500_000)
        f2 = os.urandom(2_500_000)
        good2 = make_zip(good.parent / "good2.zip", "bai-mau", f"Bài {XSS}", extra_files={
            "lessons/sample/page/filler1.mp3": f1,
            "lessons/sample/page/filler2.mp3": f2,
        })
    a.goto(base + "/#library")
    a.wait_for_selector("#libMine .stream-row")
    v2_puts = []
    a.on("request", lambda r: v2_puts.append(r) if r.method == "PUT" and "/api/uploads/parts/" in r.url else None)
    upload(a, good2)
    a.wait_for_selector("#upConfirm:not([hidden])", timeout=30000)
    check("dialog showed the reuse line", "Dùng lại" in a.locator("#upReuseStatus").text_content())
    v2_put_bytes = sum(len(r.post_data_buffer or b"") for r in v2_puts)
    v2_zip_size = good2.stat().st_size
    check("fewer PUT bytes were sent than the zip size", v2_put_bytes < v2_zip_size, f"{v2_put_bytes} < {v2_zip_size}")
    check("confirm screen appears", a.locator("#upConfirm").is_visible())
    a.check("#upAttest")
    a.click("#upCommit")
    a.wait_for_selector("#uploadDialog", state="hidden")
    v2_version = a.evaluate("async () => (await (await fetch('/api/packages')).json()).mine[0].version")  # newest update first
    check("after commit the package has the new version", v2_version == 2, v2_version)
    a.goto(base + "/#home")
    a.wait_for_selector("#lessonList .stream-row")

    # No audio: the session has no Listen step, and no Ask box without approval.
    check("no audio hides Listen", not a.locator(".stage-tab[data-nav=listen]").is_visible())
    check("no Ask without approval", not a.locator("#askDock").is_visible() and not a.locator(".capsule-ask-btn").is_visible())
    asks = []
    a.on("request", lambda r: asks.append(r.url) if "/api/ask" in r.url else None)
    a.locator("#homeCta [data-act=start]").click()
    a.wait_for_selector("#screen-review.active")
    check("next step says Flashcard", "Flashcard" in a.locator("#screen-review [data-next-listen]").inner_text())
    a.locator("#screen-review [data-next-listen]").click()
    a.wait_for_selector("#screen-flashcard.active")
    check("skips to flashcard", a.evaluate("location.hash") == "#flashcard")

    # Report a wrong card.
    a.wait_for_selector("#fcCard:not([hidden])")
    a.click("[data-act=fb-card]")
    a.wait_for_selector("#feedbackDialog[open]")
    check("reporter is told the author sees the email", "email" in a.locator("#feedbackDialog").inner_text())
    a.fill("#fbText", "Thẻ này sai.")
    a.click("#fbSend")
    a.wait_for_selector("#feedbackDialog:not([open])", state="attached")

    # A package with one track plays.
    a.goto(base + "/#library")
    a.wait_for_selector("#libMine .stream-row")
    upload(a, audio)
    a.wait_for_selector("#upConfirm:not([hidden])")
    a.check("#upAttest")
    a.click("#upCommit")
    a.locator("#libMine .stream-row", has_text="Bài có audio").wait_for()
    a.locator("#libMine .stream-row", has_text="Bài có audio").locator("[data-act=start]").click()
    a.wait_for_selector("#screen-review.active")
    a.locator("#screen-review [data-next-listen]").click()
    a.wait_for_selector("#screen-listen.active")
    check("single track shown", a.locator(".track-big:visible").count() == 1)
    played = a.evaluate("""async () => {
        const url = state.lesson.tracks.short.url;
        const r = await fetch(url, {headers: {Range: 'bytes=0-9'}});
        return {status: r.status, url};
    }""")
    check("audio serves a range", played["status"] == 206 and played["url"].startswith("/audio/"), played)

    # Share by email.
    b = new_page(br, errs)
    login_first(b, base, "binh@example.com", temp["binh@example.com"])
    b.wait_for_url(base + "/**")
    a.goto(base + "/#library")
    row = a.locator("#libMine .stream-row", has_text="Bài <img")
    row.locator("[data-act=lib-share]").click()
    a.wait_for_selector("#shareDialog[open]")
    a.fill("#shareEmail", "khong-co@example.com")
    a.click("#shareForm button[type=submit]")
    a.wait_for_selector("#shareError:not([hidden])")
    check("unknown email reported", "chưa có tài khoản" in a.locator("#shareError").inner_text())
    a.fill("#shareEmail", "BINH@example.com")
    a.click("#shareForm button[type=submit]")
    a.wait_for_selector("#sharePeople .share-person")
    check("person listed", "binh@example.com" in a.locator("#sharePeople").inner_text())

    # A link opened by someone not logged in, with a temporary password.
    a.click("#shareLinkOff [data-act=share-new]")
    a.wait_for_selector("#shareLinkOn:not([hidden])")
    a.screenshot(path=str(SHOTS / "share.png"))
    link = a.input_value("#shareLink")
    c = new_page(br, errs)
    login_first(c, base, "cuong@example.com", temp["cuong@example.com"], link.replace(base, ""))
    c.wait_for_url("**/lesson/**")
    check("link survives login and password change", "/lesson/p" in c.url, c.url)
    check("joining asked first", any("Thêm vào thư viện" in x for x in dialogs), dialogs[:2])
    a.click("[data-act=share-close]")

    # Binh learns the shared lesson and sees the author.
    b.goto(base + "/#library")
    b.wait_for_selector("#libShared .stream-row")
    check("shared list shows author", "an@example.com" in b.locator("#libShared").inner_text())
    href = b.evaluate("(document.querySelector('#libShared [data-act=start]').dataset.lesson)")
    b.goto(f"{base}/lesson/{href}")
    b.wait_for_selector("iframe.lesson-iframe")
    b.wait_for_timeout(1000)
    check("lesson bar shows author", "an@example.com" in b.locator("#lessonTitle").inner_text())
    check("lesson title did not run as HTML", b.evaluate("window.__xss") is None)
    check("no Ask button on lesson page", not b.locator("#lessonAskBtn").is_visible())
    check("no Ask dock on lesson page", not b.locator("#askDock").is_visible())
    width = b.locator("iframe.lesson-iframe").bounding_box()["width"]
    check("lesson uses the full width without Ask", width >= 1270, width)
    b.screenshot(path=str(SHOTS / "lesson-no-ask.png"))
    # Report the quiz question just answered; the button appears only after an answer.
    check("no report button before answering", not b.locator("#lessonQuizWrongBtn").is_visible())
    next(f for f in b.frames if "/s/" in f.url).click("#send")
    b.wait_for_selector("#lessonQuizWrongBtn:not([hidden])")
    b.click("#lessonQuizWrongBtn")
    b.wait_for_selector("#feedbackDialog[open]")
    b.fill("#fbText", "Câu này sai đáp án.")
    b.click("#fbSend")
    b.wait_for_selector("#feedbackDialog:not([open])", state="attached")
    b.click("#lessonFeedbackBtn")
    b.wait_for_selector("#feedbackDialog[open]")
    b.fill("#fbText", XSS)
    b.click("#fbSend")
    b.wait_for_selector("#feedbackDialog:not([open])", state="attached")

    # A reads feedback; the HTML stays text.
    a.goto(base + "/#library")
    row = a.locator("#libMine .stream-row", has_text="Bài <img")
    row.locator("[data-act=lib-feedback]").click()
    a.wait_for_selector("#fbList .fb-card")
    text = a.locator("#fbList").inner_text()
    check("author reads feedback with email", "binh@example.com" in text and "Thẻ này sai." in text and "Câu này sai đáp án." in text, text)
    check("feedback HTML stays text", XSS in text and a.evaluate("window.__xss") is None, text)
    a.screenshot(path=str(SHOTS / "feedback.png"))
    a.click("[data-act=fb-list-close]")

    # Revoke while the page is open.
    row.locator("[data-act=lib-share]").click()
    a.wait_for_selector("#sharePeople .share-person")
    a.locator("#sharePeople .share-person", has_text="binh@example.com").locator("[data-act=share-remove]").click()
    a.wait_for_timeout(500)
    a.click("[data-act=share-close]")
    # The next thing the learner does in the open page tells them.
    frame = next(f for f in b.frames if "/s/" in f.url)
    frame.click("#send")
    b.wait_for_selector("#lessonCover:not([hidden])")
    check("revoked while open: told, frame removed", "không còn quyền" in b.locator("#lessonCoverText").inner_text() and b.locator("iframe.lesson-iframe").count() == 0, b.locator("#lessonCover").inner_text())
    b.goto(f"{base}/lesson/{href}")
    check("revoked: reload is refused", b.locator("iframe.lesson-iframe").count() == 0 and "Không mở được" in b.locator("h1").inner_text())
    b.goto(base + "/#library")
    b.wait_for_timeout(600)
    check("revoked: not in shared list", b.locator("#libShared .stream-row").count() == 0)

    # Delete.
    a.goto(base + "/#library")
    a.wait_for_selector("#libMine .stream-row")
    a.locator("#libMine .stream-row", has_text="Bài có audio").locator("[data-act=lib-delete]").click()
    a.wait_for_timeout(800)
    check("delete removes the row", a.locator("#libMine .stream-row").count() == 1)

    # Layout.
    for width, height in ((360, 740), (390, 844), (1024, 768), (1440, 900)):
        for screen in ("home", "library"):
            a.set_viewport_size({"width": width, "height": height})
            a.goto(f"{base}/#{screen}")
            a.wait_for_timeout(500)
            over = a.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            check(f"{screen} {width}px no horizontal scroll", over <= 0, over)
            small = a.evaluate("""() => [...document.querySelectorAll('.screen.active button, .screen.active a')]
                .filter(e => e.offsetParent && e.getBoundingClientRect().height < 40).map(e => e.textContent.trim()).slice(0, 4)""")
            check(f"{screen} {width}px touch targets", not small, small)
            a.screenshot(path=str(SHOTS / f"{screen}-{width}.png"))
    a.set_viewport_size({"width": 360, "height": 740})
    a.goto(base + "/#library")
    a.wait_for_selector("#libMine .stream-row")
    a.locator("#libMine [data-act=lib-share]").first.click()
    a.wait_for_selector("#shareDialog[open]")
    a.wait_for_timeout(300)
    box = a.locator("#shareDialog").bounding_box()
    check("share dialog fits at 360", box["x"] > 0 and box["x"] + box["width"] < 360, box)
    a.screenshot(path=str(SHOTS / "share-360.png"))

    check("no /api/ask request anywhere", not asks, asks[:2])
    # Data set while a slow write is in flight still reaches the server, with nothing else happening.
    c.goto(base + "/#library")
    c.reload()
    c.wait_for_selector("#libShared .stream-row")
    slow_key = c.locator("#libShared [data-act=start]").first.get_attribute("data-lesson")
    c.goto(f"{base}/lesson/{slow_key}", wait_until="networkidle")
    frame = next(f for f in c.frames if "/s/" in f.url)
    held = []
    c.route("**/api/doc/**", lambda r: held.append(r) if r.request.method == "PUT" and not held else r.continue_())
    frame.evaluate("LearnBridge.call('doc.set', {data: {step: 1}})")
    c.wait_for_timeout(2500)
    check("first write is in flight", len(held) == 1, len(held))
    frame.evaluate("LearnBridge.call('doc.set', {data: {step: 2}})")
    c.wait_for_timeout(2500)  # the timer for step 2 fires while step 1 is still being written
    held[0].continue_()
    c.wait_for_timeout(3000)
    saved = c.evaluate("async key => (await (await fetch('/api/doc/' + encodeURIComponent(key))).json()).data", slow_key)
    check("save made during a slow write is not stranded", saved == {"step": 2}, saved)
    c.unroute("**/api/doc/**")

    # Cuong, who joined by link, takes the package back out of the library.
    c.goto(base + "/#library")
    c.reload()
    c.wait_for_selector("#libShared .stream-row")
    c.click("#libShared [data-act=lib-leave]")
    c.wait_for_selector("#libSharedEmpty:not([hidden])")
    check("leaving removes it from the library", c.locator("#libShared .stream-row").count() == 0)
    check("no page errors or CSP blocks", not errs, errs[:4])


if __name__ == "__main__":
    sys.exit(main())
