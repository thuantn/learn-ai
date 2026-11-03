"""Real-browser checks for the lesson page on a phone: its own menu, and how much of the screen is left for reading.
  python tests/e2e_lesson_phone.py [--browser chrome|webkit] [--package DIR]
--package uploads a real package folder instead of the page below and opens its lesson (menu links #s1, #s2...).
"""
import argparse
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

from e2e_platform import NEW_PW, ROOT, check, free_port, login_first, make_zip, new_page, upload, FAILS

SHOTS = pathlib.Path(tempfile.gettempdir()) / "learn-ai-phone-shots"
PAGE = """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="/static/lesson-bridge.js"></script>
<style>html{scroll-padding-top:64px}body{margin:0}nav.top{position:sticky;top:0;background:#222;padding:12px;display:flex;gap:12px}
nav.top a{color:#fff}section{min-height:900px;padding:12px;color:#ddd}</style></head><body>
<nav class="top" id="toc"><a href="#s0">Mở đầu</a><a href="#s1">Một</a><a href="#s2">Hai</a><a href="#none">Lạc</a><a href="#">Đầu</a></nav>
<section id="s0">Mở đầu</section><section id="s1">Một</section><section id="s2">Hai</section><section id="s3">Ba</section>
</body></html>"""


def zip_dir(root, dest):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(pathlib.Path(root).rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(root).as_posix())
    return dest


def page_zip(work):
    plain = make_zip(work / "plain.zip", "menu", "Bài có menu với tên dài để thử chỗ hiển thị")
    root = work / "unz"
    with zipfile.ZipFile(plain) as z:
        z.extractall(root)
    (root / "lessons" / "sample" / "page" / "index.html").write_text(PAGE, "utf-8")
    return zip_dir(root, work / "menu.zip")


def frame_of(pg):
    return next(f for f in pg.frames if "/s/" in f.url)


def bar_shown(pg):
    box = pg.locator("#lessonTopBar").bounding_box()
    return box is not None and box["y"] + box["height"] > 1 and pg.locator("#lessonTopBar").is_visible()


def scroll(pg, y):
    frame_of(pg).evaluate("y => window.scrollTo(0, y)", y)
    pg.wait_for_timeout(500)


def notice(pg, present):
    """Polls by hand: wait_for_function evaluates a string, which the page's CSP refuses."""
    for _ in range(80):
        if bool(pg.locator("#lessonNotice").inner_text()) == present:
            return True
        pg.wait_for_timeout(100)
    return False


def alive(pg):
    return pg.locator("iframe.lesson-iframe").count() == 1 and not pg.locator("#lessonCover").is_visible()


def run(br, base, temp, zipped, real):
    errs = []
    pg = new_page(br, errs, 390, 844)
    login_first(pg, base, "an@example.com", temp)
    pg.wait_for_selector("#screen-home.active")
    pg.goto(base + "/#library")
    pg.wait_for_selector("#screen-library.active")
    upload(pg, zipped)
    pg.wait_for_selector("#upConfirm:not([hidden])")
    pg.check("#upAttest")
    pg.click("#upCommit")
    pg.wait_for_selector("#libMine .stream-row")
    key = pg.locator("#libMine [data-act=start]").first.get_attribute("data-lesson")
    pg.goto(f"{base}/lesson/{key}", wait_until="networkidle")
    pg.wait_for_selector("iframe.lesson-iframe")
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(SHOTS / "top.png"))
    frame = frame_of(pg)

    # The menu must move within the page, and must never trip the guard against a page leaving.
    link = frame.locator("nav.top a[href^='#s']").nth(2)
    target = link.get_attribute("href")[1:]
    link.click()
    pg.wait_for_timeout(900)
    check("menu link keeps the lesson open", alive(pg), pg.locator("#lessonCoverText").inner_text())
    if not alive(pg):
        return errs
    frame = frame_of(pg)
    top = frame.evaluate("id => document.getElementById(id).getBoundingClientRect().top", target)
    check("menu link reaches its section", -2 <= top <= 90, top)
    pg.screenshot(path=str(SHOTS / "after-menu.png"))
    if not real:
        for href in ("#none", "#"):
            frame.locator(f"nav.top a[href='{href}']").click()
            pg.wait_for_timeout(500)
            check(f"odd link {href} keeps the lesson open", alive(pg))
        frame = frame_of(pg)

    # Reading: both menus leave the screen. Going back up: both return.
    scroll(pg, 0)
    check("bar shown at the top of the lesson", bar_shown(pg))
    bar_h = pg.locator("#lessonTopBar").bounding_box()["height"]
    check("bar is slim on a phone", bar_h <= 48, bar_h)
    scroll(pg, 100)
    scroll(pg, 800)
    check("bar leaves while reading down", not bar_shown(pg))
    menu = frame.evaluate("document.querySelector('nav.top').getBoundingClientRect().bottom")
    check("lesson menu leaves while reading down", menu <= 0, menu)
    box = pg.locator("iframe.lesson-iframe").bounding_box()
    check("reading uses the whole screen", box["y"] <= 1 and box["height"] >= 840, box)
    check("the host page itself does not scroll", pg.evaluate("document.documentElement.scrollHeight <= innerHeight + 1"))
    check("handle offered while the bar is away", pg.locator("#lessonBarShow").is_visible())
    pg.screenshot(path=str(SHOTS / "reading.png"))
    scroll(pg, 600)
    check("bar returns when scrolling up", bar_shown(pg))
    menu = frame.evaluate("document.querySelector('nav.top').getBoundingClientRect().top")
    check("lesson menu returns when scrolling up", menu >= -1, menu)
    check("handle gone with the bar back", not pg.locator("#lessonBarShow").is_visible())
    scroll(pg, 1000)

    # At the very end the frame grows when the bar leaves, and the browser pulls the scroll back. It must not flicker.
    frame.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    pg.wait_for_timeout(300)
    states = []
    for _ in range(10):
        states.append(bar_shown(pg))
        pg.wait_for_timeout(100)
    check("no flicker at the end of the page", len(set(states)) == 1, states)
    scroll(pg, 0)

    # A page can ask the bar to leave for ever. It must not cost the learner the way out.
    frame.evaluate("setInterval(() => LearnBridge.call('bar.set', {hidden: true}), 100)")
    pg.wait_for_timeout(400)
    check("a page can only hide the bar on a phone", not bar_shown(pg))
    pg.click("#lessonBarShow")
    pg.wait_for_timeout(500)
    check("handle holds the bar against a hostile page", bar_shown(pg))
    pg.click("a.lesson-back")
    pg.wait_for_url(base + "/**")
    check("way out still works", "/lesson/" not in pg.url, pg.url)
    # WebKit reports a request cut off by leaving as a page error, so let the home screen finish first.
    pg.wait_for_load_state("networkidle")

    # A problem to report brings the bar back and keeps it there.
    pg.goto(f"{base}/lesson/{key}", wait_until="networkidle")
    pg.wait_for_timeout(600)
    frame = frame_of(pg)
    frame.evaluate("LearnBridge.call('bar.set', {hidden: true})")
    pg.wait_for_timeout(300)
    pg.route("**/api/doc/**", lambda r: r.abort() if r.request.method == "PUT" else r.continue_())
    frame.evaluate("LearnBridge.call('doc.set', {data: {step: 1}})")
    check("save problem shows a notice", notice(pg, True))
    check("save problem shows the bar", bar_shown(pg))
    frame.evaluate("LearnBridge.call('bar.set', {hidden: true})")
    pg.wait_for_timeout(300)
    check("bar stays while there is a notice", bar_shown(pg))
    pg.unroute("**/api/doc/**")
    check("notice clears once saved", notice(pg, False))

    # A narrow screen with every button in the bar still fits.
    pg.set_viewport_size({"width": 360, "height": 740})
    pg.evaluate("document.getElementById('lessonQuizWrongBtn').hidden = false; document.getElementById('lessonAskBtn').hidden = false")
    pg.wait_for_timeout(200)
    over = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    bar = pg.locator("#lessonTopBar").bounding_box()
    right = pg.evaluate("Math.max(...[...document.querySelectorAll('#lessonTopBar button:not([hidden])')].map(b => b.getBoundingClientRect().right))")
    check("bar fits 360 with every button", over <= 0 and right <= 360 and bar["height"] <= 48, (over, right, bar))
    small = pg.evaluate("[...document.querySelectorAll('#lessonTopBar a, #lessonTopBar button:not([hidden])')].filter(e => e.getBoundingClientRect().height < 40).map(e => e.textContent)")
    check("bar buttons stay easy to tap", not small, small)
    pg.screenshot(path=str(SHOTS / "bar-360.png"))

    # A wide screen has room: nothing leaves, even when asked.
    pg.set_viewport_size({"width": 1280, "height": 800})
    pg.wait_for_timeout(300)
    frame.evaluate("LearnBridge.call('bar.set', {hidden: true})")
    frame.evaluate("window.scrollTo(0, 500)")
    pg.wait_for_timeout(400)
    frame.evaluate("window.scrollTo(0, 1500)")
    pg.wait_for_timeout(400)
    check("wide screen keeps the bar", bar_shown(pg))
    pg.screenshot(path=str(SHOTS / "wide.png"))
    return errs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=["chrome", "webkit"], default="chrome")
    parser.add_argument("--package")
    args = parser.parse_args()
    SHOTS.mkdir(exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="learn-phone-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, DATA_DIR=str(work / "data"), PACKAGES_DIR=str(work / "packages"), COOKIE_SECURE="0",
               PUBLIC_ORIGIN=base, LINK_SECRET="e2e-secret-e2e-secret-e2e-secret-e2e", PYTHONUTF8="1")
    env.pop("AI_API_KEY", None)
    out = subprocess.run([sys.executable, "-m", "app.cli", "add-user", "an@example.com"], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
    temp = out.stdout.rsplit(": ", 1)[1].strip()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/healthz", timeout=1)
                break
            except OSError:
                time.sleep(0.25)
        zipped = zip_dir(args.package, work / "real.zip") if args.package else page_zip(work)
        with sync_playwright() as p:
            br = p.webkit.launch() if args.browser == "webkit" else p.chromium.launch(channel="chrome")
            errs = run(br, base, temp, zipped, bool(args.package))
            check("no page errors or CSP blocks", not errs, errs[:4])
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
