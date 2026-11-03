"""A lesson page that is busy right after its first bridge call must not lose that call or its saved progress.
  python tests/e2e_bridge.py [--browser chrome|webkit] [--rounds N]

The page asks for its document, then blocks for 800 ms, so the bridge's hello timer fires before the first port
arrives. Each round adds one to a counter kept with doc.set and reloads. A lost doc.get used to time out, and the
page saving over a document it could not read set the counter back.
"""
import argparse
import pathlib
import shutil
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright

from e2e_sandbox import BASE, ROOT, add_user, install, login, make_env, start_app, stop_app, wait_frame

PAGE = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><title>Trang bận</title>
<script src="/static/lesson-bridge.js"></script></head>
<body><p id="out">chưa</p><script src="busy.js"></script></body></html>
"""
# Never saves unless the read worked: the page must not write over a document it has not seen.
SCRIPT = """"use strict";
(async function () {
  const out = document.getElementById("out");
  const read = LearnBridge.call("doc.get");
  const t0 = performance.now();
  while (performance.now() - t0 < 800);
  try {
    const d = await read;
    const n = ((d && d.n) || 0) + 1;
    await LearnBridge.call("doc.set", { data: { n: n } });
    out.textContent = "ok " + n;
  } catch (e) {
    out.textContent = "fail " + (e && e.code);
  }
})();
"""


def busy_package(dest):
    shutil.copytree(ROOT / "sample" / "package", dest)
    page = dest / "lessons" / "sample" / "page"
    (page / "index.html").write_text(PAGE, encoding="utf-8")
    (page / "busy.js").write_text(SCRIPT, encoding="utf-8")
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", default="webkit", choices=["chrome", "webkit"])
    ap.add_argument("--rounds", type=int, default=8)
    args = ap.parse_args()
    work = pathlib.Path(tempfile.mkdtemp(prefix="learn-bridge-"))
    env = make_env(work / "data", work / "packages")
    srv = None
    seen = []
    try:
        temp = add_user(env)
        srv = start_app(env)
        package_id = install(env, busy_package(work / "pkg"), work / "data")
        with sync_playwright() as p:
            br = p.webkit.launch() if args.browser == "webkit" else p.chromium.launch(channel="chrome")
            page = br.new_context(viewport={"width": 1280, "height": 900}).new_page()
            puts = []
            page.on("response", lambda r: puts.append(r.status) if "/api/doc/" in r.url and r.request.method == "PUT" else None)
            login(page, temp)
            page.goto(f"{BASE}/lesson/{package_id}.sample")
            for i in range(args.rounds):
                frame = wait_frame(page)
                end = time.time() + 20
                text = ""
                while time.time() < end:
                    text = frame.locator("#out").inner_text()
                    if text != "chưa":
                        break
                    page.wait_for_timeout(100)
                seen.append(text)
                if not text.startswith("ok"):
                    break
                # doc.set is written after a 2 s debounce; wait for that PUT before reloading.
                end = time.time() + 15
                while len(puts) <= i and time.time() < end:
                    page.wait_for_timeout(100)
                page.reload()
            br.close()
    finally:
        stop_app(srv)
        shutil.rmtree(work, ignore_errors=True)
    want = [f"ok {i + 1}" for i in range(args.rounds)]
    print(args.browser, seen)
    if seen != want:
        print("FAIL: expected", want)
        sys.exit(1)
    print("PASS")


if __name__ == "__main__":
    main()
