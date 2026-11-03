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
    from tests.practice_fixtures import make_item, make_test, one_file, SENTINELS
except ImportError:
    from practice_fixtures import make_item, make_test, one_file, SENTINELS
import sqlite3

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
    # the link state loads after the dialog opens
    poll(lambda: an.locator("#shareLinkOff").is_visible() or an.locator("#shareLinkOn").is_visible())
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

    # ---------- Task 7 Checks ----------
    q1 = make_item("q1", domain="An ninh", options=("A", "B", "C", "D"), correct=("A",))
    q2 = make_item("q2", type="multi", domain="Phát triển", options=("A", "B", "C", "D"), correct=("A", "B"))
    q3 = make_item("q3", domain="Vận hành", options=("A", "B", "C", "D"), correct=("C",))
    t_exam = make_test(title="Đề Thi Thử T7", items=[q1, q2, q3])
    t_timed = make_test(title="Đề Có Giờ", items=[make_item("qt1"), make_item("qt2")], time_limit_minutes=1)
    pkg_t7 = one_file({"exam": t_exam, "timed": t_timed}, slug="de-t7")

    an.goto(base + "/#library")
    an.wait_for_selector("#screen-library.active")
    open_upload(an)
    an.fill("#upJsonText", json.dumps(pkg_t7))
    an.click("[data-act=up-paste-send]")
    an.wait_for_selector("#upConfirm:not([hidden])")
    an.check("#upAttest")
    an.click("#upCommit")
    an.wait_for_selector("#uploadDialog", state="hidden")

    t7_test = find_test(an, "Đề Thi Thử T7")
    exam_key = t7_test["key"]
    timed_test = find_test(an, "Đề Có Giờ")
    timed_key = timed_test["key"]

    # 1. Thi thử không có đáp án trong trang
    an.goto(f"{base}/#test={exam_key}")
    an.wait_for_selector("#screen-test-detail.active")
    an.click("#testDetailActions [data-act=attempt-start][data-mode=exam]")
    an.wait_for_selector("#screen-test-run.active")
    an.wait_for_selector(".test-option-btn")
    exam_aid = an.evaluate("location.hash").split("#attempt=")[1]

    exam_responses = []
    def on_resp(r):
        if "/api/" in r.url:
            try:
                exam_responses.append(r.text())
            except Exception:
                pass
    an.on("response", on_resp)

    an.locator(".test-option-btn").first.click()
    poll(lambda: "Đã lưu" in an.inner_text("#testSave"))
    page_content = an.content()
    leaked_in_page = [s for s in SENTINELS if s in page_content]
    leaked_in_resp = [s for s in SENTINELS if any(s in r for r in exam_responses)]
    an.remove_listener("response", on_resp)
    check("Thi thử không có đáp án trong trang", not leaked_in_page and not leaked_in_resp, f"page={leaked_in_page}, resp={leaked_in_resp}")

    # 2. tải lại vẫn đúng câu và thứ tự
    q_before = an.inner_text("#testQuestionBox .test-q-text")
    opts_before = an.locator(".test-option-btn .test-opt-text").all_inner_texts()
    an.reload()
    an.wait_for_selector("#screen-test-run.active")
    an.wait_for_selector(".test-option-btn")
    q_after = an.inner_text("#testQuestionBox .test-q-text")
    opts_after = an.locator(".test-option-btn .test-opt-text").all_inner_texts()
    check("tải lại vẫn đúng câu và thứ tự", q_before == q_after and opts_before == opts_after and len(opts_before) > 0)

    # 3. hai máy: máy cũ thấy câu máy kia lưu
    ctx2 = br.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    pg2 = ctx2.new_page()
    pg2.on("pageerror", lambda e: errs.append("js: " + str(e)[:160]))
    pg2.on("console", lambda m: errs.append("csp: " + m.text[:160]) if m.type == "error" and "Content Security Policy" in m.text else None)
    pg2.on("dialog", lambda d: d.accept())
    pg2.goto(base + "/login")
    pg2.fill("#loginUser", "an@example.com")
    pg2.fill("#loginPass", NEW_PW)
    pg2.click("#submitBtn")
    pg2.wait_for_selector("#screen-home.active")

    pg2.goto(f"{base}/#attempt={exam_aid}")
    pg2.wait_for_selector("#screen-test-run.active")
    pg2.wait_for_selector(".test-option-btn")

    an.click("#btnTestNext")
    an.wait_for_timeout(200)
    an.locator(".test-option-btn").first.click()
    poll(lambda: "Đã lưu" in an.inner_text("#testSave"))

    pg2.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    pg2.wait_for_timeout(500)
    pg2.click("#btnTestNext")
    pg2.wait_for_timeout(200)
    is_sel = pg2.locator(".test-option-btn").first.evaluate("el => el.classList.contains('is-selected')")
    check("hai máy: máy cũ thấy câu máy kia lưu", is_sel)
    ctx2.close()

    # 4. Kiểm tra chấm đúng lựa chọn đang hiện
    an.goto(f"{base}/#test={exam_key}")
    an.wait_for_selector("#screen-test-detail.active")
    an.click("#testDetailActions [data-act=attempt-start][data-mode=practice]")
    an.wait_for_selector("#screen-test-run.active")
    an.wait_for_selector(".test-option-btn")
    prac_aid = an.evaluate("location.hash").split("#attempt=")[1]

    single_idx = an.evaluate("() => _currentAttempt.items.findIndex(it => it.type === 'single')")
    an.click(f"#testGrid [data-act=test-jump][data-idx='{single_idx}']")
    an.wait_for_timeout(100)

    def delay_put(route):
        time.sleep(0.5)
        route.continue_()
    an.route("**/api/attempts/*/items/*", delay_put)

    an.locator(".test-option-btn").nth(0).click()
    an.locator(".test-option-btn").nth(1).click()
    an.click("#btnTestCheck")
    an.unroute("**/api/attempts/*/items/*")
    an.wait_for_selector("#testQuestionBox .test-checked-banner")

    opt1_sel = an.locator(".test-option-btn").nth(1).evaluate("el => el.classList.contains('is-selected')")
    opt0_sel = an.locator(".test-option-btn").nth(0).evaluate("el => el.classList.contains('is-selected')")
    # the server graded the option shown second, not the first click that was still in flight
    graded = json.loads(call(an, "GET", f"/api/attempts/{prac_aid}")["text"])["items"][single_idx]
    shown_second = graded["options"][1]["id"]
    check("Kiểm tra chấm đúng lựa chọn đang hiện",
          opt1_sel and not opt0_sel and graded["checked"] and graded["chosen"] == [shown_second]
          and graded["is_correct"] == (graded["correct"] == [shown_second]),
          f"chosen={graded['chosen']}, shown_second={shown_second}")

    # 5. mất mạng hiện Chưa lưu và chặn nộp
    multi_idx = an.evaluate("() => _currentAttempt.items.findIndex(it => it.type === 'multi')")
    an.click(f"#testGrid [data-act=test-jump][data-idx='{multi_idx}']")
    an.wait_for_timeout(100)

    an.context.set_offline(True)
    an.locator(".test-option-btn").first.click()
    poll(lambda: "Chưa lưu" in an.inner_text("#testSave"), timeout=8)
    an.click("#btnTestSubmit")
    an.wait_for_timeout(400)
    blocked = an.evaluate("location.hash").startswith("#attempt=") and not an.locator("#testSubmitDialog[open]").count()
    # back online, a newer choice made before the retry fires must win over the failed one
    an.context.set_offline(False)
    an.locator(".test-option-btn").nth(1).click()
    an.wait_for_timeout(4000)
    poll(lambda: "Đã lưu" in an.inner_text("#testSave"), timeout=8)
    multi_now = json.loads(call(an, "GET", f"/api/attempts/{prac_aid}")["text"])["items"][multi_idx]
    shown = [o["id"] for o in multi_now["options"]]
    check("lựa chọn mới không bị lần gửi lại cũ ghi đè", sorted(multi_now["chosen"]) == sorted(shown[:2]),
          f"chosen={multi_now['chosen']}, expected={shown[:2]}")
    an.click("#btnTestSubmit")
    an.wait_for_selector("#testSubmitDialog[open]")
    an.click("#btnConfirmSubmit")
    poll(lambda: an.evaluate("location.hash").startswith("#result="), timeout=8)
    check("mất mạng hiện Chưa lưu và chặn nộp", blocked and an.evaluate("location.hash").startswith("#result="))

    # 6. hết giờ tự nộp
    an.goto(f"{base}/#test={timed_key}")
    an.wait_for_selector("#screen-test-detail.active")
    an.click("#testDetailActions [data-act=attempt-start][data-mode=exam]")
    an.wait_for_selector("#screen-test-run.active")
    timed_aid = an.evaluate("location.hash").split("#attempt=")[1]

    db_file = work / "data" / "learn.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("UPDATE test_attempt SET started_at = started_at - 120 WHERE id = ?", (timed_aid,))
    an.reload()
    poll(lambda: an.evaluate("location.hash").startswith("#result="), timeout=10)
    check("hết giờ tự nộp", an.evaluate("location.hash").startswith("#result="))

    # 7. đóng máy rồi mở lại thấy kết quả
    an.goto(f"{base}/#attempt={timed_aid}")
    poll(lambda: an.evaluate("location.hash").startswith("#result="), timeout=10)
    check("đóng máy rồi mở lại thấy kết quả", an.evaluate("location.hash").startswith("#result="))

    # 8. Tạm dừng che đề
    r_new = call(an, "POST", f"/api/tests/{exam_key}/attempts", {"mode": "practice", "restart": True})
    new_aid = json.loads(r_new["text"])["id"]
    an.goto(f"{base}/#attempt={new_aid}")
    an.wait_for_selector("#screen-test-run.active")
    an.wait_for_selector(".test-option-btn")
    q_open_text = an.inner_text("#testQuestionBox")
    an.click("#btnTestPause")
    an.wait_for_selector("#testPausedPane:not([hidden])")
    q_paused_empty = an.inner_text("#testQuestionBox") == ""
    an.screenshot(path=str(SHOTS / "practice-paused-1280.png"))
    an.click("#testPausedPane [data-act=test-pause]")
    an.wait_for_selector("#testPausedPane", state="hidden")
    check("Tạm dừng che đề", q_open_text != "" and q_paused_empty)

    # 9. Luyện tập hiện đúng sai và why
    s_idx = an.evaluate("() => _currentAttempt.items.findIndex(it => it.type === 'single')")
    an.click(f"#testGrid [data-act=test-jump][data-idx='{s_idx}']")
    an.wait_for_timeout(100)
    an.locator(".test-option-btn").first.click()
    an.click("#btnTestCheck")
    an.wait_for_selector("#testQuestionBox .test-checked-banner")
    box_text = an.inner_text("#testQuestionBox")
    check("Luyện tập hiện đúng sai và why", SENTINELS[1] in box_text, box_text[:100])

    # 10. chọn nhiều cần đủ số
    m_idx = an.evaluate("() => _currentAttempt.items.findIndex(it => it.type === 'multi')")
    an.click(f"#testGrid [data-act=test-jump][data-idx='{m_idx}']")
    an.wait_for_timeout(100)
    an.locator(".test-option-btn").first.click()
    an.click("#btnTestCheck")
    an.wait_for_timeout(300)
    no_banner = an.locator("#testQuestionBox .test-checked-banner").count() == 0
    an.locator(".test-option-btn").nth(1).click()
    an.click("#btnTestCheck")
    an.wait_for_selector("#testQuestionBox .test-checked-banner")
    check("chọn nhiều cần đủ số", no_banner and an.locator("#testQuestionBox .test-checked-banner").is_visible())

    # 11. kết quả có bảng lĩnh vực, lọc câu sai
    an.click("#btnTestSubmit")
    an.wait_for_selector("#testSubmitDialog[open]")
    an.click("#btnConfirmSubmit")
    poll(lambda: an.evaluate("location.hash").startswith("#result="), timeout=10)
    an.screenshot(path=str(SHOTS / "practice-result-1280.png"))
    dom_rows = an.locator("#testResultDomainTable tbody tr").count()
    res_aid = an.evaluate("location.hash").split("#result=")[1]
    res_items = json.loads(call(an, "GET", f"/api/attempts/{res_aid}")["text"])["items"]
    n_wrong = sum(1 for it in res_items if not it["is_correct"])
    an.click("[data-act=result-filter][data-filter=wrong]")
    wrong_cards = an.locator("#testResultItemsList .test-result-card")
    all_wrong = all("Sai" in card.inner_text() for card in wrong_cards.all())
    check("kết quả có bảng lĩnh vực, lọc câu sai",
          dom_rows == 3 and n_wrong > 0 and wrong_cards.count() == n_wrong and all_wrong,
          f"rows={dom_rows}, wrong={n_wrong}, cards={wrong_cards.count()}")

    # 12. Ôn câu sai chỉ có câu sai
    an.locator("[data-act=attempt-start][data-mode=review]").first.click()
    poll(lambda: an.evaluate("location.hash").startswith("#attempt="), timeout=10)
    an.wait_for_selector("#screen-test-run.active")
    rev_aid = an.evaluate("location.hash").split("#attempt=")[1]
    mode_pill = an.inner_text("#testRunModePill")
    rev_ids = {it["id"] for it in json.loads(call(an, "GET", f"/api/attempts/{rev_aid}")["text"])["items"]}
    with sqlite3.connect(work / "data" / "learn.db") as conn:
        pool_ids = {r[0] for r in conn.execute("SELECT item FROM test_pool WHERE user=? AND test_key=?", ("an@example.com", exam_key))}
    check("Ôn câu sai chỉ có câu sai", "Ôn câu sai" in mode_pill and rev_ids and rev_ids == pool_ids,
          f"pill={mode_pill}, review={sorted(rev_ids)}, pool={sorted(pool_ids)}")

    # 13. nút lựa chọn cao ít nhất 44 px ở 360 px
    an.set_viewport_size({"width": 360, "height": 740})
    an.wait_for_timeout(200)
    opt_btn = an.locator(".test-option-btn").first
    opt_h = opt_btn.bounding_box()["height"]
    check("nút lựa chọn cao ít nhất 44 px ở 360 px", opt_h >= 44, f"height={opt_h}")

    # 14. không tràn ngang ở 360 px khi làm bài và ở kết quả
    w_run_360 = an.evaluate("document.documentElement.scrollWidth")
    an.screenshot(path=str(SHOTS / "practice-run-360.png"))
    an.click("#btnTestPause")
    an.wait_for_timeout(200)
    an.screenshot(path=str(SHOTS / "practice-paused-360.png"))
    an.click("#testPausedPane [data-act=test-pause]")
    an.wait_for_timeout(200)
    an.goto(f"{base}/#result={prac_aid}")
    an.wait_for_selector("#screen-test-result.active")
    w_res_360 = an.evaluate("document.documentElement.scrollWidth")
    an.screenshot(path=str(SHOTS / "practice-result-360.png"))
    an.set_viewport_size({"width": 1280, "height": 900})
    check("không tràn ngang ở 360 px khi làm bài và ở kết quả", w_run_360 <= 360 and w_res_360 <= 360, f"run={w_run_360}, res={w_res_360}")

    # 15. dock nghe không che nút khi làm bài
    an.goto(f"{base}/#attempt={rev_aid}")
    an.wait_for_selector("#screen-test-run.active")
    an.screenshot(path=str(SHOTS / "practice-run-1280.png"))
    dock_vis = an.locator(".studio-dock").is_visible()
    capsule_vis = an.locator(".mobile-floating-capsule").is_visible()
    check("dock nghe không che nút khi làm bài", not dock_vis and not capsule_vis)

    # 16. cỡ chữ còn sau khi tải lại
    an.click("[data-act=test-font-inc]")
    saved_font = an.evaluate("() => localStorage.getItem('learn.test-font')")
    an.reload()
    an.wait_for_selector("#screen-test-run.active")
    applied_font = an.locator("#screen-test-run").get_attribute("data-test-font")
    check("cỡ chữ còn sau khi tải lại", saved_font == applied_font and applied_font != "2", f"saved={saved_font}, applied={applied_font}")

    # 17. nút giọng đọc hoặc lý do ẩn đều hiện đúng
    btn_speech = an.locator("#btnTestSpeech")
    note_speech = an.locator("#testSpeechNote")
    check("nút giọng đọc hoặc lý do ẩn đều hiện đúng", btn_speech.is_visible() or note_speech.is_visible())

    # 18. rời màn làm bài bằng Back dọn sạch
    in_test_before = an.evaluate("document.body.classList.contains('in-test')")
    submits = []
    an.on("request", lambda r: submits.append(r.url) if r.url.endswith("/submit") else None)
    an.go_back()  # the entry before is the result page opened in check 14
    an.wait_for_selector("#screen-test-result.active")
    an.wait_for_timeout(1500)
    in_test_after = an.evaluate("document.body.classList.contains('in-test')")
    dock_visible = an.locator(".studio-dock").is_visible()
    rev_state = json.loads(call(an, "GET", f"/api/attempts/{rev_aid}")["text"])["status"]
    check("rời màn làm bài bằng Back dọn sạch",
          in_test_before and not in_test_after and dock_visible and not submits and rev_state != "submitted",
          f"in_test_after={in_test_after}, dock={dock_visible}, submits={submits}, status={rev_state}")

    # 19. console sạch
    check("console sạch", not errs, errs[:4])


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
