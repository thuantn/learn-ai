# Nền tảng, phần 1: contract và cách ly trang bài. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Có contract bài học kiểm tra được bằng máy, chuyển bài 1, 2 sang contract, và chứng minh trang bài chạy được trong sandbox trên trình duyệt thật. Kết thúc bằng quyết định đi tiếp hay dùng hostname riêng.

**Architecture:** Module `app/contract.py` dùng chung cho máy tác giả và server. Route mới `/s/<token>/...` phục vụ trang bài trong iframe sandbox, trang chủ `/lesson/<id>` chứa iframe và giao tiếp qua `MessageChannel`. Toàn bộ chạy song song với `/content/` hiện có, nên app đang chạy không đổi hành vi.

**Tech Stack:** Python 3.12, FastAPI, thư viện chuẩn, `mutagen`, Playwright cho kiểm thử trình duyệt, JavaScript thuần.

**Spec:** `docs/design/02-nen-tang-nhieu-tac-gia.md`

## Lộ trình

Mục 14 của spec có 8 bước, và bước 2 có thể đổi kiến trúc của các bước sau, nên kế hoạch tách làm ba phần. Phần sau chỉ viết khi phần trước xong.

| Phần | Bước trong spec | Nội dung |
|---|---|---|
| 1, tài liệu này | 1, 2 | Contract, bộ kiểm tra, chuyển bài cũ, sandbox, cầu nối, quyết định đi tiếp |
| 2 | 3, 4, 5 | Danh sách bài trong database, migration, tải lên, thư viện, share, góp ý. Bản mẫu UI do Gemini làm trước |
| 3 | 6, 7, 8 | `/admin`, duyệt ô Hỏi, nhà cung cấp AI, skill hai mức, review bảo mật |

Phần gọi AI thật và công tắc Internet ở phần 3 chờ có khóa.

## Global Constraints

- Không commit nội dung bài, audio, `.env`, tên miền, tên VM, email, tên khách hàng. `tests/` và `sample/` chỉ dùng nội dung tự viết.
- App đang chạy không đổi hành vi: `/`, `/content/`, `/api/*` hiện có giữ nguyên, 26 test trong `tests/test_server.py` vẫn đạt.
- `app/contract.py` chỉ dùng thư viện chuẩn và `mutagen`.
- Contract v1: `summary` 3–8 ý; `cards` 5–30 thẻ; `quiz` có thể rỗng; `tracks` tối đa `short`, `long`; zip tối đa 90 MB.
- Đuôi file được nhận: html, js, css, json, svg, png, jpg, webp, woff2, mp3, cộng `md` cho `content.md`.
- Id chỉ gồm chữ thường, số, dấu gạch ngang: `^[a-z0-9][a-z0-9-]*$`. Tên tệp thêm được dấu chấm và gạch dưới: `^[a-z0-9][a-z0-9._-]*$`.
- Mức Đầy đủ (`--profile full`): `quiz` đúng 8 câu, có cả `short` và `long`, có `content.md`, trang có chuỗi `Khởi động` và `Đi sâu`.
- Token hết hạn sau 6 giờ, không chứa email. Mỗi request `/s/` kiểm tra lại quyền.
- Trình duyệt bắt buộc: Chrome, Safari iPhone, Chrome Android. Firefox là thêm.
- Trang bài không có email người học, chỉ có mã riêng. Trang không gọi AI.
- Lệnh chạy Python trên Windows đặt `PYTHONUTF8=1`.

## Review Focus

1. Iframe tự điều hướng ra ngoài bằng `location.href`: phải bị chặn, hoặc app gỡ khung và báo. Test ở Task 6.
2. Zip tạo trên Windows, tên dùng `\`, JSON có BOM và xuống dòng CRLF, đuôi viết hoa `.MP3`: tên sai bị báo rõ, BOM và CRLF được chấp nhận, `.MP3` bị báo cần đổi tên. Test ở Task 1, 2.
3. Để tab mở quá 6 giờ, kể cả điện thoại ngủ, rồi bấm phát audio: app hiện thông báo và nút tải lại, không im lặng. Test ở Task 6, dùng `LINK_TTL_SECONDS` ngắn.
4. Bấm link trong bài, gồm link `http://` có thật trong bài 2: `https` hỏi trước khi mở, `http` báo không mở được và hiện địa chỉ để tự chép. Test ở Task 5.
5. Bài 1, 2 ghi `localStorage` trong origin mờ: mọi lời gọi đều có `try/catch`, trang vẫn chạy, đáp án lưu qua cầu nối. Vị trí nghe và tốc độ của audio trong trang không còn nhớ; bước Nghe của app vẫn nhớ. Test ở Task 6.

---

### Task 1: Bộ kiểm tra contract

**Files:**
- Create: `app/contract.py`, `tests/test_contract.py`
- Modify: `requirements.in`, `requirements.txt`

**Interfaces:**
- Produces: `Problem(path: str, code: str, message: str, severity: str = "error")` dạng dataclass; `check_package(root: Path, profile: str = "basic") -> list[Problem]`; `errors(problems) -> list[Problem]`, đạt khi danh sách này rỗng. `page_inline`, `page_external` là `warning`, vẫn đóng gói được; `read_json_file(path: Path) -> object` đọc `utf-8-sig`; `audio_seconds(path: Path) -> int`.

- [ ] **Step 1: Thêm `mutagen` vào `requirements.in`, chạy `pip-compile --generate-hashes --no-header --no-emit-index-url --strip-extras`, cài vào `.venv`.**

- [ ] **Step 2: Viết test thất bại**

Fixture `good_package(tmp_path)` tạo một package hợp lệ: 3 ý, 5 thẻ, trang HTML ngắn. Mọi test là một biến thể của fixture đó.

```python
def test_good_package_passes(good_package):
    assert check_package(good_package) == []

def test_warning_does_not_block(good_package): ...                   # có onclick: errors(...) == [], severity "warning"

@pytest.mark.parametrize("change, code", [
    (lambda l: l.update(summary=["a", "b"]), "summary_count"),
    (lambda l: l.update(summary=["x"] * 9), "summary_count"),
    (lambda l: l["cards"].pop(), "cards_count"),
    (lambda l: l["cards"].append(dict(l["cards"][0])), "duplicate_id"),
    (lambda l: l["cards"][0].update(id="Bad_ID"), "bad_id"),
    (lambda l: l["cards"][0].update(q=""), "empty_text"),
    (lambda l: l.update(quiz=[{"id": "q1", "q": "?", "options": ["a"], "answer": 3, "why": ""}]), "quiz_answer"),
    (lambda l: l.update(tracks={"medium": {"file": "a.mp3", "label": "x"}}), "track_key"),
    (lambda l: l.update(tracks={"short": {"file": "none.mp3", "label": "x"}}), "track_missing"),
])
def test_lesson_rules(good_package, change, code): ...  # đổi lesson.json, assert code có trong kết quả

def test_contract_version_unknown_is_refused(good_package): ...      # code "contract_version"
def test_lesson_listed_but_folder_missing(good_package): ...         # code "lesson_missing"
def test_disallowed_extension_and_upper_case(good_package): ...      # evil.php, A.MP3: code "file_type"
def test_page_inline_handler_warns_as_broken(good_package): ...      # <a onclick=...>: code "page_inline"
def test_page_inline_script_warns_as_broken(good_package): ...       # <script>x</script>: code "page_inline"
def test_page_external_resource(good_package): ...                   # <script src="https://x">: code "page_external"
def test_links_to_other_sites_are_allowed(good_package): ...         # <a href="https://x"> hợp lệ
def test_bom_and_crlf_json_is_accepted(good_package): ...
def test_full_profile_requires_more(good_package):
    codes = {p.code for p in check_package(good_package, "full")}
    assert {"full_quiz", "full_tracks", "full_content", "full_sections"} <= codes
def test_audio_seconds_reads_mp3(): ...                               # tests/fixtures/tone.mp3, 1 giây, tạo bằng ffmpeg từ sóng sine
def test_static_paths_are_not_external(good_package): ...             # <script src="/static/lesson-bridge.js"> hợp lệ
```

- [ ] **Step 3: Chạy test, kỳ vọng FAIL**

Run: `PYTHONUTF8=1 .venv/Scripts/python -m pytest -q tests/test_contract.py`
Expected: lỗi `ModuleNotFoundError: app.contract`.

- [ ] **Step 4: Viết `app/contract.py`.** Thông báo lỗi bằng tiếng Việt, nói rõ cần sửa gì. Quét HTML bằng `html.parser`, không dùng regex. Script, CSS có đường dẫn bắt đầu bằng `/static/` là hợp lệ. Module không import gì từ `app.main` hay `app.db`, để chép được sang máy tác giả.

- [ ] **Step 5: Chạy lại, kỳ vọng PASS.**

- [ ] **Step 6: Commit** `feat: lesson contract checker`.

### Task 2: Đóng gói và giải nén an toàn

**Files:**
- Create: `app/bundle.py`, `scripts/learnpkg.py`, `tests/test_bundle.py`

**Interfaces:**
- Consumes: `check_package`.
- Produces: `pack(root: Path, out: Path) -> None`; `safe_extract(zip_path: Path, dest: Path) -> list[Problem]`, lỗi thì không để lại file trong `dest`. Hằng số `MAX_ZIP = 90 * 1024 * 1024`, `MAX_UNPACKED = 400 * 1024 * 1024`, `MAX_FILES = 2000`, `MAX_RATIO = 100` trừ file mp3. CLI: `learnpkg.py validate DIR [--profile full]`, `learnpkg.py pack DIR OUT.zip`; lỗi thì in danh sách và thoát mã 1.

- [ ] **Step 1: Viết test thất bại**

```python
def test_round_trip(good_package, tmp_path): ...       # pack rồi safe_extract, check_package == []
@pytest.mark.parametrize("name", ["../x.html", "/etc/x", "C:/x", "a\\b.html", "lessons/../../x"])
def test_bad_names(tmp_path, name): ...                # code "zip_path", dest rỗng
def test_duplicate_names(tmp_path): ...                # code "zip_duplicate"
def test_symlink_entry(tmp_path): ...                  # external_attr có S_IFLNK, code "zip_symlink"
def test_bomb_ratio(tmp_path): ...                     # 200 MB số 0 nén lại, code "zip_size"
def test_too_many_files(tmp_path): ...                 # code "zip_size"
def test_not_a_zip(tmp_path): ...                      # code "zip_bad"
def test_pack_refuses_invalid_package(good_package, tmp_path): ...
def test_pack_uses_forward_slashes(good_package, tmp_path): ...
```

- [ ] **Step 2: Chạy test, kỳ vọng FAIL** với `ModuleNotFoundError: app.bundle`.

- [ ] **Step 3: Viết `app/bundle.py` và `scripts/learnpkg.py`.** `safe_extract` kiểm tra toàn bộ danh sách trước khi ghi file đầu tiên, và đếm byte thực khi giải nén, không tin kích thước khai trong zip.

- [ ] **Step 4: Chạy lại, kỳ vọng PASS.**

- [ ] **Step 5: Commit** `feat: pack and safely unpack lesson packages`.

### Task 3: Cầu nối phía trang bài và chuyển bài cũ

**Files:**
- Create: `web/static/lesson-bridge.js`, `web/static/lesson-fonts.css`, `scripts/convert_legacy.py`, `tests/test_convert.py`
- Modify: `scripts/package_content.py` (`build_page` nhận `head_tag`, `footer_tag`, mặc định giữ hành vi cũ; bỏ `duration` khỏi đường mới), `sample/` thêm bài mẫu theo contract ở `sample/package/`

**Interfaces:**
- Consumes: `check_package`, cấu hình và các hàm `build_page`, `read_quiz`, `duration` của `scripts/package_content.py`.
- Produces: `window.LearnBridge` có `call(op, args) -> Promise`, `askApp(text)`; `window.claude.use` chỉ trả `user` và `db`, `sample` trả `null`. `convert_legacy.py CONFIG.json OUT_DIR [--allow-draft]` ghi một package ra `OUT_DIR`; `--allow-draft` nhận `app/cards.draft.json` khi chưa có `cards.json`.

Giao thức, dùng chung cho Task 3 và Task 5: trang gửi `parent.postMessage({type: "learn-hello"}, "*")`. Trang chủ nhận và trả `{type: "learn-port"}` kèm `MessagePort`. Sau đó mọi thông điệp đi qua cổng: yêu cầu `{id, op, args}`, trả lời `{id, ok: true, data}` hoặc `{id, ok: false, code, message}`. Các `op`: `doc.get`, `doc.set`, `learner.id`, `quiz.answer` (`{id, option}`, server chấm), `ask.open` (`{text}`), `link.open` (`{url}`), `media.error`. Trang không gửi tên doc; trang chủ tự biết bài nào đang mở.

Bridge tự chặn mọi click trên `a[href]` trừ link `#...`, gọi `link.open`, và báo `media.error` khi `<audio>` lỗi.

**Bài cũ.** `ask`, `openPanel`, `EXPLAIN` nằm trong IIFE nên không gán đè từ ngoài được. `convert_legacy.py` có danh sách `LEGACY_PATCHES` sửa trực tiếp trong mã trang; mỗi mẫu phải khớp đúng một lần, không khớp thì dừng và báo lỗi:

| Tìm | Thay |
|---|---|
| `async function ask(q){` | thêm `LearnBridge.askApp(q\|\|"");return;` ở đầu thân hàm |
| `function openPanel(prefill){` | thêm `LearnBridge.askApp(prefill\|\|"");return;` ở đầu thân hàm |
| `pendingExplain={sec,prompt:EXPLAIN[sec]};` | `LearnBridge.askApp("Tự giải thích lại phần "+secName(sec)+". "+EXPLAIN[sec]+"\n\nPhần của tôi: ");return;` |

Điểm tự giải thích hiện trong ô Hỏi của app, không còn ghi lại trong trang. Bài cũ vẫn lưu đáp án bằng `store.quiz["q"+i]` qua `doc.set`, server chấm bằng `record_wrong_answers`. Bài mới dùng `quiz.answer`. Id `bai02-q0` trong `lesson.json` khớp vị trí `q0`.

- [ ] **Step 1: Viết test thất bại.** Dùng trang tự viết tối giản có `const QS=[...\n];`, `<head>`, `<footer>`, script CDN, một IIFE chứa đủ ba mẫu vá, thẻ `<audio src="audio/a.mp3">`.

```python
def test_converted_package_is_valid(tmp_path): ...   # check_package(out) == []
def test_quiz_ids_are_stable_by_position(tmp_path): ...  # "demo-q0", "demo-q1"
def test_page_uses_bridge_not_shim(tmp_path): ...    # có lesson-bridge.js đầu <head>, lesson-fonts.css; không có lesson-shim.js; không còn link href="/"
def test_legacy_patch_missing_stops(tmp_path): ...   # trang thiếu mẫu vá => SystemExit nêu tên mẫu
def test_scripts_are_relative_files(tmp_path): ...   # page/page.1.js tồn tại, không còn <script> inline
def test_content_md_has_text_not_script(tmp_path): ...  # có đoạn văn, không có mã JS
def test_replace_removes_names(tmp_path): ...
```

- [ ] **Step 2: Chạy test, kỳ vọng FAIL.**

- [ ] **Step 3: Viết `lesson-bridge.js`, `lesson-fonts.css`, `convert_legacy.py`.** `lesson-fonts.css` chứa các `@font-face` của `app.css`. `lesson.json` lấy `summary`, `cards`, `tracks` từ `app/`, `quiz` từ `read_quiz`. `content.md` lấy văn bản hiển thị bằng `html.parser`, bỏ `script`, `style`, `nav`. Audio đặt ở `audio/` theo contract, trang tham chiếu `../audio/`. Tên audio giữ nguyên, tên `page.N.js` hợp lệ theo quy tắc tên tệp.

- [ ] **Step 4: Chạy lại, kỳ vọng PASS.**

- [ ] **Step 5: Chuyển bài thật, ngoài repo**

Run: `PYTHONUTF8=1 .venv/Scripts/python scripts/convert_legacy.py <cấu hình bài> <thư mục ngoài repo> --allow-draft && .venv/Scripts/python scripts/learnpkg.py validate <thư mục ngoài repo> --profile full`
Expected: bài 1, 2 đạt cả mức Đầy đủ; kiểm tra lại không còn tên riêng trong package.

- [ ] **Step 6: Commit** `feat: lesson bridge and legacy conversion`.

### Task 4: Route phục vụ trang trong sandbox

**Files:**
- Create: `app/sandbox.py`, `tests/test_sandbox.py`
- Modify: `app/main.py:27-37` (thêm `frame-src`), `app/main.py:110-117` (`guard` bỏ `X-Frame-Options` với `/s/`), `app/main.py:120-134` (miễn phiên cho `/s/`), `app/main.py:531-556` (header cho `serve_listed`, CORS và CORP cho `/static/`), `compose.yml` (mount `./packages:/packages:ro`, `PACKAGES_DIR=/packages`), `README.md`, `.github/workflows/ci.yml` (chạy `tests/test_*.py`)

**Interfaces:**
- Consumes: `app.db.connect`.
- Produces: `make_token(user_id: int, lesson: str, now: float) -> str`; `read_token(token: str, now: float) -> tuple[int, str] | None`; `user_id` là `users.rowid`; `page_headers(path: str) -> dict`; route `GET /s/{token}/{rel:path}`; `can_read(user_id: int, lesson: str) -> bool` hiện chỉ kiểm tra tài khoản còn tồn tại, phần 2 thay bằng bảng quyền; `POST /api/lessons/{id}/frame` trả `{url, expires, doc, title, learner}`, `learner` là mã HMAC theo người dùng và package, không lộ email; `POST /api/lessons/{id}/quiz-answer` nhận `{id, option}`, dùng chung logic với `record_wrong_answers`.

Giá trị đã chốt:

```
CSP cho .html:   sandbox allow-scripts; default-src 'none'; script-src {O}; style-src {O} 'unsafe-inline';
                 img-src {O} data:; font-src {O} data:; media-src {O}; connect-src 'none'; form-action 'none';
                 base-uri 'none'; object-src 'none'; frame-ancestors {O}
CSP file khác:   sandbox; default-src 'none'
Cả hai:          X-Content-Type-Options: nosniff; Cross-Origin-Resource-Policy: cross-origin;
                 không có X-Frame-Options
Cache:           .html no-store; file khác private, max-age=300
Font:            thêm Access-Control-Allow-Origin: *
```

`{O}` là `PUBLIC_ORIGIN`. Header `Cross-Origin-Resource-Policy: same-origin` hiện đặt ở `HEADERS` sẽ chặn file khỏi iframe origin mờ, nên `/s/` và toàn bộ `/static/` phải đặt `cross-origin`; `/static/` vốn công khai nên không mất gì. Vì `guard` dùng `setdefault`, route tự đặt `Cross-Origin-Resource-Policy` trước, còn `X-Frame-Options` phải được `guard` bỏ qua với `/s/`. Thiếu `LINK_SECRET` thì `/s/` trả 404 và app vẫn chạy như cũ.

`PACKAGES_DIR` là thư mục gốc của một package, đặt riêng ngoài `CONTENT_DIR` vì `package_content.py` xóa thư mục đó khi chạy lại. Chỉ phục vụ `page/` và `audio/`; `lesson.json` chứa đáp án và `content.md` không tải được. Token gắn với id bài nên `rel` tính từ `PACKAGES_DIR/lessons/<id>/`: trang là `/s/<token>/page/index.html`, audio là `/s/<token>/audio/a.mp3`. Id bài trùng với `BY_ID` hiện có, và tên `doc` lấy từ đó; phần 2 thay bằng database.

- [ ] **Step 1: Viết test thất bại**

```python
def frame_get(c, url, **kw):
    return c.get(url, headers={"Sec-Fetch-Dest": "iframe"}, **kw)

def test_html_only_in_iframe(ctx): ...           # thiếu header hoặc "document" => 403; "iframe" => 200
def test_html_headers(ctx): ...                  # CSP đúng từng phần, có sandbox allow-scripts, không X-Frame-Options
def test_other_files_cannot_run(ctx): ...        # .svg: CSP "sandbox; default-src 'none'"
def test_font_has_cors(ctx): ...
def test_token_tampered_or_expired(ctx): ...     # 403, kể cả đổi một ký tự, now + 6h + 1
def test_token_has_no_email(ctx, capsys): ...       # giải mã phần đầu token không thấy tên đăng nhập
def test_answers_and_content_not_served(ctx): ...   # lesson.json, content.md => 404
def test_quiz_answer_graded_by_server(ctx, capsys): ...  # chọn sai tạo thẻ, chọn đúng không, id lạ 400
def test_token_for_other_lesson_refused(ctx): ...
def test_removed_user_loses_access_at_once(ctx, capsys): ...  # token còn hạn, xóa user => 403
def test_traversal_and_symlink(ctx): ...         # %2e%2e, ..%2f, symlink => 404
def test_no_cookie_needed_and_none_set(ctx): ...
def test_audio_range_206_in_sandbox(ctx): ...    # Range: bytes=0-9 => 206, Accept-Ranges
def test_frame_endpoint_needs_session(ctx): ...  # 401 khi chưa đăng nhập
def test_frame_learner_hides_user(ctx, capsys): ...
def test_disabled_without_secret(ctx, monkeypatch): ...
def test_app_csp_frames_only_lesson_path(ctx): ...  # CSP trang app có frame-src {O}/s/
```

- [ ] **Step 2: Chạy test, kỳ vọng FAIL.**

- [ ] **Step 3: Viết `app/sandbox.py`, sửa `app/main.py`.** Token là `base64url(user_id|lesson|exp).base64url(HMAC-SHA256)`, hạn lấy từ `LINK_TTL_SECONDS`, mặc định 21600, so bằng `hmac.compare_digest`. Trong `_guarded`, `/s/` đi cùng nhánh `PUBLIC_PATHS`; route tự kiểm tra token và `can_read`. Mở file dùng lại `serve_listed` nhưng truyền thêm header.

- [ ] **Step 4: Chạy `tests/test_sandbox.py` và `tests/test_server.py`, kỳ vọng tất cả PASS.**

- [ ] **Step 5: Commit** `feat: serve lesson pages from a sandbox route`.

### Task 5: Trang chủ của bài và phía app của cầu nối

**Files:**
- Create: `web/lesson.html`, `web/static/lesson-host.js`
- Modify: `app/main.py` (route `GET /lesson/{id}`), `web/static/app.js`, `web/app.html` (nạp `answer.js`), `web/static/app.css`, `tests/test_sandbox.py`

**Interfaces:**
- Consumes: `POST /api/lessons/{id}/frame`, `POST /api/lessons/{id}/quiz-answer`, `GET|PUT /api/doc/{name}`, `POST /api/ask` dạng `{lesson, question}`, `renderAnswer` trong `app.js` (tách ra `web/static/answer.js` để dùng chung), giao thức ở Task 3.

Hành vi:
- Thanh trên có "Về app", tên bài, và dòng "Trang bài không bao giờ hỏi mật khẩu của bạn". Tên tác giả thêm ở phần 2, khi có chủ sở hữu trong database.
- Chỉ nhận `learn-hello` khi `event.source === iframe.contentWindow`. Tạo `MessageChannel` mới mỗi lần trang gửi hello.
- Giới hạn: mỗi thông điệp tối đa 2 MB, `op` lạ bị từ chối. `doc.set` được gộp, chỉ ghi bản mới nhất, tối đa mỗi 2 giây một lần, ghi nốt khi rời trang, để không mất đáp án cuối.
- `ask.open` mở ô Hỏi của trang chủ với câu điền sẵn; chỉ gửi khi người học bấm. Chưa bật AI thì hiện đúng thông báo chưa bật.
- `link.open`: `https` hiện hộp xác nhận có địa chỉ; `http` và giao thức khác chỉ hiện địa chỉ để tự chép.
- Iframe tải lần thứ hai ngoài lần do app chủ động: gỡ khung, hiện "Trang bài vừa cố chuyển sang địa chỉ khác nên đã bị đóng", kèm nút mở lại.
- Khi nhận `media.error`, hoặc khi `visibilitychange` thấy đã qua `expires`: hiện thông báo phiên xem bài hết hạn và nút tải lại; tiến độ đã lưu không mất.

- [ ] **Step 1: Thêm test server thất bại:** `/lesson/{id}` cần phiên, id lạ trả 404, trang không có `on*`, và cập nhật `test_no_html_handlers_in_app_pages` để gồm `lesson.html`.

- [ ] **Step 2: Chạy test, kỳ vọng FAIL.**

- [ ] **Step 3: Viết host và route.**

- [ ] **Step 4: Chạy test, kỳ vọng PASS.** Giao diện được kiểm ở Task 6.

- [ ] **Step 5: Commit** `feat: lesson host page and bridge`.

### Task 6: Thử tấn công và thử bài thật trong trình duyệt

**Files:**
- Create: `tests/e2e_sandbox.py`, `sample/evil/` (package hợp lệ chứa script tấn công)

**Interfaces:**
- Consumes: mọi route ở trên. Script nhận `PACKAGES_DIR` và `--browser chrome|firefox|webkit`; báo `OK` hoặc `FAIL` theo từng mục, kết thúc in tổng số lỗi và thư mục ảnh.

- [ ] **Step 1: Viết `sample/evil/`.** Mỗi kiểu tấn công ghi kết quả vào `document.title` để script đọc. Máy chủ giả ở cổng khác đóng vai bên ngoài và ghi mọi request nhận được.

| Kiểu tấn công | Kỳ vọng |
|---|---|
| Đọc `document.cookie`, `localStorage` | Rỗng hoặc lỗi |
| `fetch`, XHR, `sendBeacon` tới `/api/me` và máy ngoài | Bị chặn, máy ngoài không nhận gì |
| `<img>`, `<script>`, CSS `url()`, `<form>` tới máy ngoài | Bị chặn |
| `window.open`, `top.location`, `parent.location` | Bị chặn |
| `location.href` tự điều hướng | Máy ngoài không nhận gì, hoặc khung bị gỡ. **Ghi rõ kết quả nào** |
| Gửi `learn-hello` nhiều lần, thông điệp sai kiểu, cổng cũ | Không làm hỏng trang chủ |
| `doc.set` lặp vô hạn | Được gộp, app vẫn phản hồi |
| `doc.get` xin tên doc khác | Bị bỏ qua, chỉ nhận doc của bài đang mở |
| `LINK_TTL_SECONDS=5`, chờ hết hạn rồi phát audio | Hiện thông báo hết hạn và nút tải lại |
| `ask.open` | Chỉ điền sẵn, không có request `/api/ask` khi chưa bấm |
| `RTCPeerConnection` tới STUN giả | **Ghi lại kết quả** theo từng trình duyệt. Rủi ro đã được chấp nhận |
| Mở thẳng đường dẫn `/s/...` trong tab | 403 |
| Mở thẳng file `.svg` có script | Script không chạy |

- [ ] **Step 2: Thêm phần bài thật.** Với bài 1, 2 trong package đã chuyển, trên `/lesson/{id}`: công thức MathJax hiện, font tải được, máy tính tương tác cho kết quả, làm sai một câu quiz thì thẻ từ câu sai xuất hiện ở `/#flashcard`, audio phát và tua tới phút 10, bấm "Tự giải thích lại" điền sẵn vào ô Hỏi, link `http://` hiện địa chỉ, không có lỗi JavaScript. Chụp ảnh ở 390 px và 1440 px.

- [ ] **Step 3: Chạy trên máy**

Run: `PYTHONUTF8=1 .venv/Scripts/python tests/e2e_sandbox.py <thư mục package> --browser chrome`, rồi lặp lại với `webkit` và `firefox`. Playwright chỉ cài ở máy dev, không vào `requirements.txt`.
Expected: `FAILS: 0` với các mục bắt buộc, kết quả ghi lại cho hai mục "Ghi". Xem ảnh, không chỉ tin kết quả.

- [ ] **Step 4: Commit** `test: attack and real-lesson checks for the sandbox`.

### Task 7: Thử trên điện thoại thật và quyết định

**Files:**
- Create: `docs/design/02a-ket-qua-sandbox.md`
- Modify: `docs/design/02-nen-tang-nhieu-tac-gia.md` nếu quyết định đổi thiết kế

**Interfaces:**
- Consumes: bản deploy có `LINK_SECRET` và `packages/`. Trang chính vẫn dùng `/content/`, chỉ `/lesson/<id>` là đường mới.

- [ ] **Step 1: Deploy.** Thêm `LINK_SECRET` ngẫu nhiên vào `.env` trên VM và chép package đã chuyển vào `packages/`. Kiểm tra site công khai, `/content/` vẫn chạy, các app khác trên VM vẫn healthy.

- [ ] **Step 2: Chủ dự án thử trên iPhone Safari và Android Chrome bằng 4G**, tại `/lesson/bai02`: công thức, máy tính, quiz, audio có tua và khóa màn hình, link, ô Hỏi điền sẵn. Mở thẳng đường dẫn `/s/` phải bị từ chối. Playwright WebKit không thay thế được bước này.

- [ ] **Step 3: Ghi kết quả vào `02a-ket-qua-sandbox.md`:** bảng trình duyệt và mục thử, kết quả hai mục "Ghi" ở Task 6, rủi ro còn lại thực tế.

- [ ] **Step 4: Quyết định theo tiêu chí**

| Kết quả | Quyết định |
|---|---|
| Mọi mục bắt buộc đạt trên 3 trình duyệt bắt buộc | Đi tiếp phần 2 với thiết kế hiện tại |
| Chủ dự án chưa thử được điện thoại, còn Chrome và WebKit đạt | Đi tiếp, ghi rõ điểm này còn mở; phần đọc bài vẫn ở `/content/` cho tới khi có kết quả |
| Safari không áp dụng CSP `sandbox` hoặc `Sec-Fetch-Dest`, hoặc audio không tua được | Chuyển sang hostname riêng cho `/s/`, sửa spec, chạy lại Task 6, 7 |
| `location.href` lọt dữ liệu ra ngoài ở trình duyệt nào đó | Gỡ khung vẫn hoạt động thì ghi vào rủi ro còn lại và đi tiếp. Không gỡ được thì báo chủ dự án quyết định |

- [ ] **Step 5: Commit** `docs: sandbox results and decision`, rồi viết kế hoạch phần 2.
