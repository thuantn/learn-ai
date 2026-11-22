"""On a touch phone every text field must use at least 16px text, or iOS zooms the page when it is tapped.
On a mouse screen the fields keep their own size.
  python tests/e2e_touch_inputs.py [--browser chrome|webkit]
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

from e2e_platform import NEW_PW, ROOT, check, free_port, FAILS

SIZES = """()=>[...document.querySelectorAll('input,textarea,select')]
  .filter(e=>!['checkbox','radio','range','file','hidden'].includes(e.type))
  .map(e=>[(e.id||e.className||e.tagName), parseFloat(getComputedStyle(e).fontSize)])"""


def small(pg):
    return [x for x in pg.evaluate(SIZES) if x[1] < 16]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=["chrome", "webkit"], default="chrome")
    args = parser.parse_args()
    work = pathlib.Path(tempfile.mkdtemp(prefix="learn-touch-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, DATA_DIR=str(work / "data"), PACKAGES_DIR=str(work / "packages"), COOKIE_SECURE="0",
               PUBLIC_ORIGIN=base, LINK_SECRET="e2e-secret-e2e-secret-e2e-secret-e2e", PYTHONUTF8="1")
    env.pop("AI_API_KEY", None)
    out = subprocess.run([sys.executable, "-m", "app.cli", "add-user", "an@example.com"], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
    temp = out.stdout.rsplit(": ", 1)[1].strip()
    subprocess.run([sys.executable, "-m", "app.cli", "set-admin", "an@example.com", "on"], cwd=ROOT, env=env, capture_output=True)
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
            # Mouse screen first: the rule must not touch it.
            pc = br.new_context(viewport={"width": 1280, "height": 900}).new_page()
            pc.goto(base + "/login")
            check("mouse screen: login field keeps its own size", pc.evaluate("parseFloat(getComputedStyle(document.querySelector('#loginUser')).fontSize)") < 16)
            phone = br.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=args.browser == "chrome").new_page()
            phone.goto(base + "/login")
            coarse = phone.evaluate("matchMedia('(pointer: coarse)').matches")
            print("coarse pointer:", coarse, flush=True)
            check("phone: login fields 16px or more", coarse and not small(phone), small(phone))
            phone.fill("#loginUser", "an@example.com"); phone.fill("#loginPass", temp); phone.click("#submitBtn")
            phone.wait_for_url("**/change-password*")
            check("phone: password fields 16px or more", not small(phone), small(phone))
            phone.fill("#pass1", NEW_PW); phone.fill("#pass2", NEW_PW); phone.click("#submitBtn")
            phone.wait_for_selector("#screen-home.active")
            fields = phone.evaluate(SIZES)
            check("phone: app has the ask fields", sum(1 for f in fields if "ask" in str(f[0]).lower()) >= 2, fields)
            check("phone: every app field 16px or more", not small(phone), small(phone))
            phone.goto(base + "/admin"); phone.wait_for_load_state("networkidle")
            check("phone: every admin field 16px or more", not small(phone), small(phone))
            br.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)
        shutil.rmtree(work, ignore_errors=True)
    print("FAILS:", len(FAILS), FAILS[:10], flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
