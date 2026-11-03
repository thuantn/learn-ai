"""Real-browser checks for practice test list, detail, upload, share, and security.
  python tests/e2e_practice.py [--browser chrome|webkit]
"""
import argparse
import base64
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

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from tests.practice_fixtures import make_item, make_test, one_file
except ImportError:
    from practice_fixtures import make_item, make_test, one_file

NEW_PW = "ngựa vàng chạy qua cầu mây"
FAILS = []
SHOTS = pathlib.Path(tempfile.gettempdir()) / "learn-ai-practice-shots"
XSS = "<img src=x onerror=window.__xss=1>"


def check(name, ok, info=""):
    print("OK  " if ok else "FAIL", name, "" if ok else str(info)[:200], flush=True)
    if not ok:
        FAILS.append(name)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def new_page(br, errs, width=1280, height=900):
    ctx = br.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce")
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append("js: " + str(e)[:160]))
    pg.on("console", lambda m: errs.append("csp: " + m.text[:160]) if m.type == "error" and "Content Security Policy" in m.text else None)
    pg.on("dialog", lambda d: d.accept())
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


def call(pg, method, url, body=None):
    return pg.evaluate("""async ([method, url, body]) => {
        const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
        return { status: r.status, text: await r.text() };
    }""", [method, url, body])


def poll(fn, timeout=10, step=0.2):
    start = time.time()
    while time.time() - start < timeout:
        try:
            res = fn()
            if res:
                return res
        except Exception:
            pass
        time.sleep(step)
    return fn()


def open_upload(pg):
    pg.locator("#screen-library [data-act=lib-upload]").first.click()
    pg.wait_for_selector("#uploadDialog[open]")


def all_tests(pg):
    return json.loads(call(pg, "GET", "/api/tests")["text"])["tests"]


def find_test(pg, title):
    return poll(lambda: next((t for t in all_tests(pg) if t["title"] == title), None))


def run(br, base, temp, work):
    errs = []
    an = new_page(br, errs)
    binh = new_page(br, errs)
    login_first(an, base, "an@example.com", temp["an@example.com"])
    an.wait_for_url(base + "/**")
    login_first(binh, base, "binh@example.com", temp["binh@example.com"])
    binh.wait_for_url(base + "/**")

    # 1. dán JSON có bọc khối code
    # hộp dán nhận ```json ...``` kèm câu dẫn, tới bước xác nhận; question có khối code bên trong vẫn nguyên sau khi cài
    code_snippet = "```python\nprint('inside-code-block')\n```"
    item1 = make_item(id="q1", question=f"Xem đoạn mã sau:\n{code_snippet}\nKết quả là gì?")
    pkg1 = one_file({"t1": make_test(title="Đề Dán Code", items=[item1])}, slug="de-dan-code")
    raw1 = json.dumps(pkg1)
    pasted1 = f"Dưới đây là nội dung JSON đề thi:\n```json\n{raw1}\n```\nChúc bạn làm bài tốt!"

    an.goto(base + "/#library")
    an.wait_for_selector("#screen-library.active")
    open_upload(an)
    an.fill("#upJsonText", pasted1)
    an.click("[data-act=up-paste-send]")
    an.wait_for_selector("#upConfirm:not([hidden])")
    an.check("#upAttest")
    an.click("#upCommit")
    an.wait_for_selector("#uploadDialog", state="hidden")
    an.wait_for_selector("#libMine .stream-row")

    dan_code = find_test(an, "Đề Dán Code")
    att = call(an, "POST", f"/api/tests/{dan_code['key']}/attempts", {"mode": "practice", "restart": False})
    att_data = json.loads(att["text"])
    q_text = att_data["items"][0]["question"] if "items" in att_data and att_data["items"] else ""
    check("dán JSON có bọc khối code", code_snippet in q_text, q_text)

    # 2. dán chữ hỏng báo lỗi
    # alert hiện, hộp không đóng, console không có lỗi
    open_upload(an)
    an.fill("#upJsonText", "Tôi là AI, không thể tạo JSON { broken syntax ...")
    an.click("[data-act=up-paste-send]")
    an.wait_for_selector("#upPickError:not([hidden])")
    err_box = an.locator("#upPickError")
    dialog_open = an.locator("#uploadDialog").is_visible()
    check("dán chữ hỏng báo lỗi", err_box.is_visible() and dialog_open and "JSON" in err_box.inner_text(), err_box.inner_text())
    an.click("[data-act=up-close]")
    an.wait_for_selector("#uploadDialog", state="hidden")

    # 3. 3 file cùng slug thành 3 bộ
    f1 = work / "p1.json"
    f2 = work / "p2.json"
    f3 = work / "p3.json"
    f1.write_text(json.dumps(one_file({"t1": make_test(title="Bộ một")}, slug="slug-ba")), "utf-8")
    f2.write_text(json.dumps(one_file({"t2": make_test(title="Bộ hai")}, slug="slug-ba")), "utf-8")
    f3.write_text(json.dumps(one_file({"t3": make_test(title="Bộ ba")}, slug="slug-ba")), "utf-8")
    open_upload(an)
    an.set_input_files("#upFile", [str(f1), str(f2), str(f3)])
    an.wait_for_selector("#upConfirm:not([hidden])")
    meta_text = an.inner_text("#upMeta")
    check("3 file cùng slug thành 3 bộ", "3 đề" in meta_text, meta_text)
    an.check("#upAttest")
    an.click("#upCommit")
    an.wait_for_selector("#uploadDialog", state="hidden")
    row_ba = an.locator("#libMine .stream-row:has-text('3 đề')")
    row_ba.wait_for()
    pkg_ba = poll(lambda: next((p for p in json.loads(call(an, "GET", "/api/packages")["text"])["mine"] if len(p["tests"]) == 3), None))
    ba_key = pkg_ba["tests"][0]["key"]

    # 4. khác slug bị từ chối
    fa = work / "pa.json"
    fb = work / "pb.json"
    fa.write_text(json.dumps(one_file({"t1": make_test(title="Bộ A")}, slug="slug-a")), "utf-8")
    fb.write_text(json.dumps(one_file({"t2": make_test(title="Bộ B")}, slug="slug-b")), "utf-8")
    open_upload(an)
    an.set_input_files("#upFile", [str(fa), str(fb)])
    an.wait_for_selector("#upPickError:not([hidden])")
    diff_slug_err = an.inner_text("#upPickError")
    check("khác slug bị từ chối", "slug" in diff_slug_err.lower(), diff_slug_err)
    an.click("[data-act=up-close]")
    an.wait_for_selector("#uploadDialog", state="hidden")

    # 5. nút Học ẩn với package chỉ có đề
    has_test_btn = row_ba.locator("[data-act=lib-tests]").is_visible()
    has_learn_btn = row_ba.locator("[data-act=start]").count() > 0 and row_ba.locator("[data-act=start]").is_visible()
    check("nút Học ẩn với package chỉ có đề", has_test_btn and not has_learn_btn)

    # 6. share link vào thẳng danh sách đề
    # người thứ hai mở #join=..., xác nhận, thấy bộ đề
    row_ba.locator("[data-act=lib-share]").click()
    an.wait_for_selector("#shareDialog[open]")
    if an.locator("#shareLinkOff").is_visible():
        an.click("#shareLinkOff [data-act=share-new]")
    an.wait_for_selector("#shareLinkOn:not([hidden])")
    link_val = an.input_value("#shareLink")
    token = link_val.split("#join=")[1]
    an.click("[data-act=share-close]")
    an.wait_for_selector("#shareDialog", state="hidden")

    binh.goto(f"{base}/#join={token}")
    poll(lambda: binh.locator("#screen-tests.active").is_visible())
    poll(lambda: binh.locator("#testsList .stream-row").count() == 3)
    tests_count = binh.locator("#testsList .stream-row").count()
    binh_hash = binh.evaluate("location.hash")
    check("share link vào thẳng danh sách đề", pkg_ba["id"] in binh_hash and tests_count == 3, f"hash={binh_hash}, count={tests_count}")

    # 7. trang đầu có mục Bộ đề
    an.goto(base + "/#home")
    an.wait_for_selector("#screen-home.active")
    an.wait_for_selector("#homeTestsHeading:not([hidden])")
    home_title = an.inner_text("#home-title")
    home_tests_count = an.locator("#homeTestList .stream-row").count()
    check("trang đầu có mục Bộ đề", "Chưa có bài học nào" not in home_title and home_tests_count > 0, f"title={home_title}, count={home_tests_count}")

    # 8. không tràn ngang ở 360 px
    an.set_viewport_size({"width": 360, "height": 740})
    widths = []
    for name, path in (("home", "/#home"), ("library", "/#library"), ("tests", "/#tests"), ("detail", "/#test=" + ba_key)):
        an.goto(base + path)
        an.wait_for_timeout(200)
        widths.append(an.evaluate("document.documentElement.scrollWidth"))
        an.screenshot(path=str(SHOTS / f"practice-360-{name}.png"), full_page=True)
    an.goto(base + "/#library")
    an.wait_for_selector("#screen-library.active")
    open_upload(an)
    widths.append(an.evaluate("document.documentElement.scrollWidth"))
    an.screenshot(path=str(SHOTS / "practice-360-upload.png"))
    an.keyboard.press("Escape")
    check("không tràn ngang ở 360 px", all(w <= 360 for w in widths), f"widths={widths}")
    an.set_viewport_size({"width": 1280, "height": 900})

    # 9. đề độc không chạy
    # tiêu đề và question có XSS, <style>*{display:none}</style>, <svg onload=...>; __xss undefined, nút vẫn hiện
    evil_title = f"Đề Độc {XSS}"
    evil_desc = f"Mô tả độc {XSS} <style>*{{display:none !important}}</style><svg onload=window.__xss=1>"
    evil_q = f"Câu hỏi độc {XSS} <style>*{{display:none !important}}</style><svg onload=window.__xss=1>"
    evil_item = make_item(id="q1", question=evil_q, explanation=f"Lời giải {XSS}")
    evil_pkg = one_file({"t1": make_test(title=evil_title, description=evil_desc, items=[evil_item])}, slug="de-doc")

    an.goto(base + "/#library")
    an.wait_for_selector("#screen-library.active")
    open_upload(an)
    an.fill("#upJsonText", json.dumps(evil_pkg))
    an.click("[data-act=up-paste-send]")
    an.wait_for_selector("#upConfirm:not([hidden])")
    an.check("#upAttest")
    an.click("#upCommit")
    an.wait_for_selector("#uploadDialog", state="hidden")

    evil_test = poll(lambda: next((t for t in all_tests(an) if "Đề Độc" in t["title"]), None))
    an.goto(base + "/#test=" + evil_test["key"])
    an.wait_for_selector("#screen-test-detail.active")
    an.wait_for_selector("#testDetailActions button")
    xss_val = an.evaluate("window.__xss")
    btn_vis = an.locator("#testDetailActions button").first.is_visible()
    check("đề độc không chạy", xss_val is None and btn_vis, f"xss={xss_val}, btn_vis={btn_vis}")
    an.screenshot(path=str(SHOTS / "practice-detail.png"))

    check("no page errors or CSP violations", not errs, errs[:4])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=["chrome", "webkit"], default="chrome")
    args = parser.parse_args()
    SHOTS.mkdir(exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="learn-practice-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(
        os.environ,
        DATA_DIR=str(work / "data"),
        PACKAGES_DIR=str(work / "packages"),
        COOKIE_SECURE="0",
        PUBLIC_ORIGIN=base,
        LINK_SECRET="e2e-secret-e2e-secret-e2e-secret-e2e",
        PYTHONUTF8="1",
        KEY_ENCRYPTION_KEY=base64.urlsafe_b64encode(b"e" * 32).decode(),
    )
    env.pop("AI_API_KEY", None)

    def add_user(name):
        out = subprocess.run(
            [sys.executable, "-m", "app.cli", "add-user", name],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8"
        )
        return out.stdout.rsplit(": ", 1)[1].strip()

    temp = {n: add_user(n) for n in ("an@example.com", "binh@example.com")}
    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env
    )
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
