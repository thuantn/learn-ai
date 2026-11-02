# Nền tảng, phần 3: trang quản trị, duyệt ô Hỏi, nhà cung cấp AI, skill. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin duyệt được ô Hỏi theo package, nhập được nhà cung cấp AI và khóa ngay trong app, gỡ được package vi phạm; tác giả có skill và bộ công cụ để tự tạo bài; các điểm còn lại của review bảo mật phần 2 được đóng.

**Architecture:** Thêm trang `/admin` và nhóm route `/api/admin/*`, chỉ admin thấy, người khác nhận đúng 404 của route không tồn tại. Module mới `app/ai.py` giữ danh sách nhà cung cấp, cấu hình đang dùng và lời gọi AI. Khóa mã hóa AES-GCM bằng khóa chủ trong `.env`. Skill nằm trong repo, app đóng gói nó cùng bộ kiểm tra thành một zip tải được.

**Tech Stack:** Python 3.12, FastAPI, SQLite WAL, JavaScript thuần, Playwright. Thêm đúng một dependency: `cryptography`, cho AES-GCM. Không tự viết mã hóa.

**Spec:** `docs/design/02-nen-tang-nhieu-tac-gia.md`, các mục 9, 10, 11, 13, 14. Kết quả trước: `docs/design/02a-ket-qua-sandbox.md`.

**Phản biện:** agy và một Claude subagent, cả hai yêu cầu sửa; bản này đã gộp các điểm đúng. OpenCode hết tiền nên không tham gia vòng này.

## Global Constraints

- Không commit nội dung bài, audio, `.env`, tên miền, tên VM, email thật, tên khách hàng. Quét cả lịch sử chưa push trước khi đẩy lên.
- Mọi route admin đi qua `APIRouter(dependencies=[Depends(require_admin)])`, đọc `users.is_admin` từ database cho từng request. Người không phải admin nhận `HTTPException(404)`, trùng status và body của route không tồn tại.
- Khóa AI chỉ ghi, không đọc lại. Không xuất hiện trong response, log, `admin_log`, bản sao lưu dạng rõ. Response chỉ có 4 ký tự cuối.
- Admin không nhập được địa chỉ API. Code production không có đường nào đổi địa chỉ của nhà cung cấp admin chọn. Test vá `ai.PROVIDERS` hoặc `urlopen`.
- Không tự chuyển nhà cung cấp khi lỗi. Lời gọi AI không theo redirect, để khóa không đi sang host khác.
- Không gọi AI thật cho tới khi chủ dự án cấp khóa.
- Internet chưa làm. Màn hình duyệt ghi một dòng: "Chưa có tùy chọn Internet, cần kiểm tra ZDR với khóa thật". Khi đó mới thêm cột và code.
- Migration theo `MIGRATIONS` trong `app/db.py`, chạy trong transaction, sao lưu trước.

## Quyết định của người viết kế hoạch

- `admin.js` nằm ở `/static/`, ai cũng tải được. File không chứa bí mật, cửa kiểm soát là server. Không dựng route riêng cho nó.
- Admin xem nội dung để duyệt và xử lý vi phạm ở dạng văn bản (toàn văn, tóm tắt, thẻ, quiz), không mở trang bài của người khác. Muốn xem trang thì nhờ tác giả share. Chủ dự án đổi được.
- `off` và `reject` cùng ghi `rejected`, không thêm trạng thái.
- Hạn mức đổi bằng CLI (`set-quota`), trang admin chỉ hiển thị dung lượng.
- `--profile full` không còn bắt buộc audio, vì spec mục 10 nói audio không bắt buộc.

## Review Focus

1. Tác giả tải bản mới đúng lúc admin duyệt: duyệt là một câu `UPDATE ... WHERE id=? AND ask_hash=? AND ask_status='pending'`, rowcount 0 thì 409. Route xem đọc hash trước nội dung.
2. Admin tắt trong lúc tác giả cập nhật chỉ đổi trang: `install_version` tính trạng thái bằng `CASE` trong chính câu UPDATE, không ghi đè bằng giá trị đọc từ trước.
3. `KEY_ENCRYPTION_KEY` sai, hỏng định dạng hoặc thiếu: ô Hỏi báo chưa bật, các trang khác vẫn chạy, admin nhập lại khóa được.
4. Admin gỡ package đang có người học: lần bấm tiếp theo báo mất quyền, kể cả khi đó là bấm gửi trong ô Hỏi.
5. Mở link `#join=` đã tắt hoặc người bị thu hồi mở link: không lộ tên package.

---

### Task 1: Đóng các điểm còn lại của review phần 2

**Files:** `app/main.py`, `app/catalog.py`, `app/contract.py`, `app/uploads.py`, `web/static/library.js`, `web/static/app.js`, `web/static/lesson-host.js`, `tests/test_share.py`, `tests/test_catalog.py` (sửa kỳ vọng ở dòng 494), `tests/test_uploads.py`, `tests/test_contract.py`, `tests/test_server.py`, `tests/e2e_platform.py`.

**Produces:** `POST /api/packages/{id}/leave`; `POST /api/join` nhận thêm `preview: true`, trả `{title, author}` và không thêm quyền.

- [ ] **Step 1: Test đỏ:**
  - `test_leave_removes_from_shared_and_blocks_rejoin`: `binh` được share rồi `leave`; `shared` rỗng; `/lesson/<key>` 404; `join` bằng link 403. Chủ sở hữu `leave` nhận 404.
  - `test_join_preview_grants_nothing`: preview trả tên và tác giả, `shared` vẫn rỗng. Token sai hoặc link đã tắt 404 mã `link`; người bị thu hồi 403. Cả hai đều không có tên.
  - `test_ask_hash_includes_lesson_title`.
  - `test_update_ask_status_transitions`: `approved` + nội dung khác thành `pending`; `rejected` + khác thành `none`; `pending` + khác giữ `pending`; chỉ đổi trang giữ nguyên.
  - `test_install_does_not_overwrite_admin_decision`: `approved`, đổi cột sang `rejected` giữa lúc `copytree` chạy (vá `shutil.copytree`), bản mới chỉ đổi trang, kết quả vẫn `rejected`.
  - `test_package_count_cap`: có 30 package thì package mới nhận 413 ở cả `prepare` và commit; cập nhật package đã có vẫn qua.
  - `test_metadata_cap`: `lesson.json` + `content.md` của một package trên 16 MB bị từ chối, mã `meta_size`.
  - `test_app_csp_scripts_only_from_static` trong `tests/test_server.py`: với `PUBLIC_ORIGIN` có đặt, `script-src` là `<origin>/static/`.
- [ ] **Step 2: Sửa code.** `leave` đặt `revoked_at`. `_read_unpacked` đưa tiêu đề bài vào `ask_parts`. `install_version` tính `ask_status` bằng `CASE WHEN ask_hash=:new THEN ask_status WHEN ask_status='approved' THEN 'pending' WHEN ask_status='rejected' THEN 'none' ELSE ask_status END`. CSP chỉ đổi ở app, không đụng `sandbox.py`.
- [ ] **Step 3: Giao diện.** `joinFromLink` gọi preview trước, hỏi bằng `window.confirm` "Thêm bài <tên> của <tác giả>?", đồng ý mới join. Thư viện có "Bỏ khỏi thư viện" ở bài được share. Dung lượng 0 byte hiện "0 MB" (`library.js:22`).
- [ ] **Step 4: Ô Hỏi trong trang bài.** Ở `lesson-host.js`: `ask.open` khi bài chưa bật thì host hiện thông báo tự tắt sau vài giây, "Bài này chưa bật ô Hỏi", dùng phần tử riêng vì `setNotice("")` xóa notice. Giới hạn `ask.open` 3 lần mỗi 10 giây như `openLink`, vẫn gửi `reply`. Không ghi đè `askInput` đang có chữ. `sendAsk` gọi `lostAccess()` khi 404.
- [ ] **Step 5: `tests/e2e_platform.py` nghe thêm console error** để bắt được lỗi CSP, bỏ qua đúng các lỗi đã biết của Cloudflare (không có ở máy). Thêm kiểm tra hộp xác nhận, bỏ khỏi thư viện.
- [ ] **Step 6: Toàn bộ unit test và ba bộ e2e, commit.**

### Task 2: `app/ai.py`, khóa mã hóa, nhà cung cấp

**Files:** Create `app/ai.py`, `tests/test_ai.py`. Modify `app/db.py` (migration 3), `app/main.py` (bỏ `call_ai`, thay các chỗ đọc `AI_API_KEY`), `tests/test_server.py` (dòng 394, 428, 430 đang vá `main.call_ai`, `main.urllib`), fixture `sys.modules` trong `tests/test_catalog.py`, `tests/test_server.py`, `tests/test_sandbox.py`, `requirements.in`, `requirements.txt`, `.github/workflows/ci.yml`.

**Produces:**
- `ai.PROVIDERS`: `openrouter` (`https://openrouter.ai/api/v1`, `zdr: True`, model mặc định `deepseek/deepseek-v4.1-flash`) và `opencode` (`https://opencode.ai/inference/go/openai/v1`, `zdr: False`, model mặc định chọn lúc viết từ danh sách còn hiệu lực).
- `ai.current() -> dict | None`: `{provider, model, key, base, zdr, source}`. Không có cấu hình hoặc giải mã lỗi thì `None`. Nơi cần biết bật hay chưa dùng `ai.current() is not None`, đọc một lần mỗi request.
- `ai.status() -> dict`: `{provider, model, last4, source, zdr, problem}`, không có khóa. `problem` là `master_key_missing`, `master_key_bad` hoặc `key_unreadable`.
- `ai.save(provider, model, key, actor)`: `key=None` hoặc rỗng chỉ hợp lệ khi có dòng cũ và cùng nhà cung cấp, nếu không thì `ValueError("key_required")`. Khóa bỏ khoảng trắng hai đầu, ASCII in được, 8–512 ký tự. Model khớp `^[A-Za-z0-9._:/-]{1,100}\Z`. Mỗi lần lưu dùng nonce mới, AAD là `provider`.
- `ai.call(messages, max_tokens=1500) -> str`. `ai.test() -> {ok, code}` với `code` thuộc `ok`, `auth`, `zdr_no_endpoint`, `unreachable`, `no_config`; không trả nội dung lỗi của nhà cung cấp.

`AI_BASE_URL` đang dùng cho môi trường test với khóa `.env` được giữ, chỉ áp dụng khi `source == "env"`.

**Migration 3:**
```sql
CREATE TABLE ai_settings(id INTEGER PRIMARY KEY CHECK(id=1), provider TEXT NOT NULL, model TEXT NOT NULL,
  key_blob BLOB NOT NULL, key_last4 TEXT NOT NULL, updated_by TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE admin_log(id INTEGER PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '', at REAL NOT NULL);
```

- [ ] **Step 1: Test đỏ:**
  - `test_key_is_encrypted_at_rest`: đọc thô database và WAL không có chuỗi khóa; `last4` đúng.
  - `test_bad_master_key_keeps_app_running`: với một package đã `approved`, lần lượt khóa chủ sai, hỏng base64, sai độ dài, thiếu: `current()` là `None`, `status()["problem"]` đúng, `/api/lessons` và `/frame` 200, `/api/ask` 503. Đặt lại khóa chủ đúng hoặc nhập khóa mới thì chạy lại.
  - `test_missing_master_key_refuses_save`.
  - `test_env_key_is_the_fallback`.
  - `test_key_required_when_provider_changes`; `test_key_and_model_validated`; `test_unknown_provider_refused`.
  - `test_no_fallback_between_providers`.
  - `test_zdr_flag_sent_only_for_zdr_providers`: vá `urlopen`, đọc body.
  - `test_no_redirect_follow`: nhà cung cấp giả trả 302 sang host khác thì không có request thứ hai.
  - `test_ai_test_maps_errors`: 401 thành `auth`, 404 thành `zdr_no_endpoint`.
  - `test_key_never_leaks`: `admin_log`, `caplog`, `capsys` và response không có khóa.
- [ ] **Step 2: Viết code.** Xử lý `binascii.Error`, `ValueError`, `InvalidTag`. Giữ cách xử lý lỗi `urllib` trong `ask`. Opener không có redirect handler.
- [ ] **Step 3: Dependency.** Sinh `requirements.txt` cho Linux, Python 3.12, giữ nguyên các pin cũ. Diff chỉ được thêm `cryptography`. `pip-audit` sạch. CI thêm `docker build .`.
- [ ] **Step 4: Chạy test, commit.**

### Task 3: API quản trị

**Files:** Create `app/web_util.py` (chuyển `bad`, `read_json`, `page` ra đây để tránh import vòng), `app/admin.py`, `tests/test_admin.py`. Modify `app/main.py`, `app/catalog.py`, `app/cli.py`.

**Produces:** `cli set-admin EMAIL on|off`, `cli set-quota EMAIL GB`; `/api/me` thêm `admin`; `/api/packages` phần `mine` thêm `ask_status`, `has_content`; `POST /api/packages/{id}/ask-request`; các route admin:
- `GET /admin`, trả `web/admin.html`.
- `GET /api/admin/overview`: `{pending, packages, abuse, users, log, ai}`. Danh sách có `LIMIT`, không nạp toàn văn.
- `GET /api/admin/packages/{id}/review`: đọc `ask_hash` trước, rồi `{title, author, ask_status, ask_hash, zdr, lessons: [{title, summary, cards, quiz, content}]}`.
- `POST /api/admin/packages/{id}/ask`: `{decision: approve|reject|off, ask_hash?}`. Chỉ `approve` cần hash.
- `DELETE /api/admin/packages/{id}`: `{reason}`. Ghi log kèm tên và chủ sở hữu trước khi xóa.
- `PUT /api/admin/ai`: `{provider, model, key?}`. `POST /api/admin/ai/test` chạy bằng `asyncio.to_thread`.

- [ ] **Step 1: Test đỏ:**
  - `test_non_admin_gets_404_everywhere`: duyệt mọi route của router admin (lấy từ router, route thêm sau tự được kiểm tra) bằng tài khoản thường đã đổi mật khẩu: status và body trùng route không tồn tại. Chưa đăng nhập: 401 hoặc chuyển về login. Admin còn `must_change`: 403 `must_change`.
  - `test_ask_request_flow`: tác giả xin thành `pending`; người được share xin 404; không có `content.md` 400 `no_content`.
  - `test_approve_needs_current_hash`: đổi `ask_hash` giữa lúc xem và duyệt thì 409, trạng thái không đổi. `approve` một package đã mất `content.md` thì 400.
  - `test_approve_then_ask_reaches_ai`, `test_off_stops_ask_at_once`, `test_off_works_without_hash`.
  - `test_admin_delete_removes_files_and_logs`.
  - `test_abuse_reports_reach_admin`.
  - `test_admin_flag_read_each_request`.
  - `test_prompt_keeps_author_text_in_the_data_block`: `content.md` và tiêu đề chứa lệnh giả và dấu đóng khối đoán trước đều nằm trong khối dữ liệu; phần chỉ dẫn không chứa tiêu đề; có quiz; tổng prompt có trần.
- [ ] **Step 2: Viết code.** Duyệt theo Review Focus 1.
- [ ] **Step 3: Nối ô Hỏi.** `lesson_context` đặt mọi trường của tác giả (tiêu đề, toàn văn, tóm tắt, thẻ, quiz) vào khối có dấu phân cách sinh bằng `secrets.token_hex` cho từng request, nói rõ đó là dữ liệu chứ không phải lệnh, và câu hỏi ngoài bài thì trả lời là bài không đề cập. Tổng khối tối đa 80.000 ký tự. Test chỉ chứng minh prompt đúng khuôn; mô hình thật có nghe theo không chỉ biết được khi có khóa.
- [ ] **Step 4: Chạy test, commit.**

### Task 4: Trang `/admin` và nút xin ô Hỏi

**Files:** Create `web/admin.html`, `web/static/admin.js`, `tests/e2e_admin.py`. Modify `web/static/library.js`, `web/static/app.css`, `web/app.html`.

Cùng màu, font, nút, nền của app; bảng thu thành hàng trên điện thoại. Bốn phần: Duyệt ô Hỏi (đọc toàn văn trong hộp thoại rồi mới có nút Duyệt; cảnh báo khi nhà cung cấp không xác nhận ZDR; một dòng về Internet), Nhà cung cấp AI (chọn, model, ô khóa `type=password`, 4 ký tự cuối, nút Thử kết nối, báo lỗi theo `code`), Báo vi phạm và Package (gỡ có xác nhận và lý do; dung lượng, hạn mức), Nhật ký. Mọi chuỗi dùng `textContent`.

Thư viện: thẻ package của tôi có trạng thái ô Hỏi và nút "Xin bật ô Hỏi" khi `none` hoặc `rejected` và có `content.md`. Liên kết tới `/admin` chỉ hiện với admin.

- [ ] **Step 1: `tests/e2e_admin.py`.** Khởi động server qua launcher nhỏ vá `ai.PROVIDERS` trỏ về `FakeAI` chép trong file test, không thêm biến môi trường mới vào code production. Kịch bản: tài khoản thường mở `/admin` nhận 404 như route lạ; tác giả xin, admin đọc, duyệt; người học hỏi được; admin tắt, ô Hỏi biến mất ở lần tải sau; tải bản mới có nội dung khác, package về danh sách chờ; nhập khóa thử, màn hình chỉ còn 4 ký tự cuối, tải lại vẫn thế; gỡ package; không cuộn ngang ở 360, 390, 1024, 1440 px; vùng bấm tối thiểu 44 px; không có lỗi trang và console; chụp ảnh.
- [ ] **Step 2: Viết trang, chạy Chrome và WebKit, xem ảnh, commit.** Gửi ảnh cho chủ dự án trong báo cáo cuối (spec mục 11).

### Task 5: Skill `creating-learn-packages` và bộ công cụ

**Files:** Create `skills/creating-learn-packages/SKILL.md`, `skills/creating-learn-packages/template/`, `tests/test_toolkit.py`. Modify `app/main.py`, `app/contract.py` (bỏ `full_tracks`), `Dockerfile`, `.dockerignore`, `web/static/library.js`, `web/app.html`, `docs/lesson-format.md`.

Theo `superpowers:writing-skills`: có baseline trước khi viết skill.

- [ ] **Step 1: Baseline.** Agent mới, không có skill, được yêu cầu tạo package mức Cơ bản về một chủ đề công khai. Ghi lại chỗ sai, kiểm tra bằng `learnpkg.py validate`.
- [ ] **Step 2: Viết skill** theo năm chặng ở mục 10 của spec, hai mức Cơ bản và Đầy đủ, có điểm dừng để tác giả duyệt, nhắc không đưa dữ liệu khách hàng, không tự tải lên. Thấy file đã có thì làm tiếp từ chặng dở. Ghi rõ cần `pip install mutagen`. Mô tả chỉ nêu điều kiện dùng. Khung mẫu hiển thị được khi mở file trên máy, không có `LearnBridge` thì vẫn đọc được bài.
- [ ] **Step 3: Thử lại.** Agent mới có skill làm cùng đề; package đạt `validate`, nhập được và chạy trong sandbox. Lặp cho mức Đầy đủ với `--profile full`. Bài do người thật tạo vẫn là việc của chủ dự án, không tính là đã xong.
- [ ] **Step 4: Tải về.** `GET /api/toolkit.zip` cho người đã đăng nhập, dựng từ danh sách file cố định: skill, `docs/lesson-format.md`, `app/__init__.py`, `app/contract.py`, `app/bundle.py`, `scripts/learnpkg.py`. Không dùng `rglob` trên thư mục gốc; bỏ `__pycache__`, file ẩn, symlink. `.dockerignore` thêm `!skills`, `!scripts/learnpkg.py`, `!docs/lesson-format.md`; `Dockerfile` có `COPY` đúng các file đó. `docs/lesson-format.md` bỏ link tới tài liệu không có trong zip. `3_deploy.py` xóa thêm `skills` trước khi giải nén.
- [ ] **Step 5: Test.** `tests/test_toolkit.py`: giải nén ra thư mục trống, `validate` chạy với package mẫu; danh sách file đúng tuyệt đối. Hộp thoại Tải lên có link tải. Commit.

### Task 6: Chuyển bản thật và thử tấn công

**Files:** `docs/operations.md` (`KEY_ENCRYPTION_KEY`, khôi phục: mất khóa chủ thì admin nhập lại khóa AI), `README.md`, spec và bản đầy đủ tên, `.github/workflows/ci.yml`. Ngoài repo: `3_deploy.py`, `LESSONS_LEARNED.md`.

- [ ] **Step 1: Tài liệu, CI thêm test mới. Reviewer mới đọc phần bảo mật của nhánh, sửa lỗi tìm được.**
- [ ] **Step 2: Quét tên riêng trên cả cây và lịch sử chưa push, merge, CI xanh.**
- [ ] **Step 3: Deploy.** `3_deploy.py` sinh `KEY_ENCRYPTION_KEY` một lần, thêm vào danh sách giữ lại; deploy hai lần liên tiếp, kiểm tra khóa chủ không đổi (so hash, không in). Import `AESGCM` trong container read-only. Cấp admin cho chủ dự án bằng `set-admin`. Package đã duyệt sẽ về chờ duyệt ở lần cập nhật sau vì công thức hash đổi; hiện chưa có package nào được duyệt.
- [ ] **Step 4: Kiểm tra từ Internet bằng tài khoản thử:** `reload()` thư viện và so đúng tên package, luồng xin và duyệt, gỡ package; tải toolkit từ site thật rồi `validate`; tiến độ thật của chủ dự án còn nguyên; app khác trên VM vẫn chạy.
- [ ] **Step 5: Thử tấn công bản chạy thật** bằng tài khoản thử và `sample/evil`: mục 13 của spec, cộng tài khoản thường gọi mọi route admin. Báo kết quả từng mục; các mục ô Hỏi cần mô hình thật ghi là chưa chạy. Xóa tài khoản thử.
- [ ] **Step 6: Cập nhật `LESSONS_LEARNED.md`, xóa worktree và nhánh, kiểm tra đã xóa thật.**

## Không làm trong phần này

- Gọi AI thật, tìm kiếm Internet, thử chèn lệnh với mô hình thật: chờ khóa từ chủ dự án. **Việc thử chèn lệnh là điều kiện trước khi cấp tài khoản cho team nếu ô Hỏi được bật.**
- Cấp tài khoản cho team: chờ thử trên điện thoại thật, chính sách công ty, và chủ dự án quyết định.
- Script tạo nháp `content.md` từ trang bài: spec chỉ nói "có thể". Skill hướng dẫn soạn tay.
- Vô hiệu hóa token khung khi đăng xuất: token sống tối đa 6 giờ, thu hồi và xóa vẫn có hiệu lực ngay. Chấp nhận.
