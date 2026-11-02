# Nền tảng, phần 2: thư viện, tải lên, share, góp ý. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mỗi tài khoản tải được zip của mình lên, share bằng email hoặc link, người được share học như bài thường và gửi được góp ý. Hết phần này app không còn đọc `manifest.json`.

**Architecture:** Danh sách bài chuyển vào SQLite, có migration theo `PRAGMA user_version`. Module `app/catalog.py` giữ package, phiên bản và quyền. Mọi route bài học hỏi quyền từ đó. File nằm ở `PACKAGES_DIR/<package_id>/<version>/`, con trỏ phiên bản nằm trong database. Đường `/content/` cũ, `lesson-shim.js` và `input` tự do của `/api/ask` bị gỡ.

**Tech Stack:** Python 3.12, FastAPI, SQLite WAL, JavaScript thuần, Playwright. Không thêm dependency.

**Spec:** `docs/design/02-nen-tang-nhieu-tac-gia.md`, các mục 3, 6, 7, 8, 11, 12, 13. Kết quả phần 1: `docs/design/02a-ket-qua-sandbox.md`.

## Global Constraints

- Không commit nội dung bài, audio, `.env`, tên miền, tên VM, email thật, tên khách hàng.
- Không thêm dependency. Upload là body thô `application/zip`, không dùng multipart.
- Zip tối đa 90 MB (`bundle.MAX_ZIP`). Hạn mức mỗi người 1 GB tính trên dung lượng đã giải nén. Góp ý tối đa 2.000 ký tự.
- Id trong bảng tiến độ luôn có tiền tố package do server cấp: `p<12 hex>.<id trong zip>`, khớp `^p[0-9a-f]{12}\.[a-z0-9-]+$`. Dữ liệu bài trong `package_lessons.data` và trang bài vẫn dùng id trần, vì zip không biết tiền tố. Server ghép tiền tố tại ranh giới bằng `catalog.progress_id(package_id, bare_id)`, ở `/quiz-answer`, góp ý, `_record_wrong` và `add_card`.
- Server không tin file trong zip chưa qua `check_package`. `LINK_SECRET` bắt buộc: thiếu thì app không khởi động.
- Người không có quyền nhận 404 giống như bài không tồn tại, ở mọi route bài học, gồm `PUT /api/listen` và `POST /api/ask`. Riêng `/s/` giữ 403 như phần 1.
- Văn bản của tác giả và góp ý chỉ hiển thị bằng `textContent`.
- Chưa có màn hình duyệt ô Hỏi, nên `/api/ask` từ chối mọi package có `ask_status` khác `approved`. Mặc định là `none`. Không có gì bị mất, vì bản thật chưa có khóa AI nên ô Hỏi vẫn đang tắt. Phần 3 duyệt bài 1, 2 qua `/admin`.
- Mobile: 360 px không cuộn ngang, nút tối thiểu 44 px.
- Giới hạn tần suất giữ trong bộ nhớ của worker duy nhất, theo kiểu `ask_recent` đang có.
- Lệnh Python trên Windows đặt `PYTHONUTF8=1`.

## Review Focus

1. Tài khoản mới chưa có bài nào, và bài không có audio: trang đầu hiện hướng dẫn, không crash; buổi học bỏ bước Nghe. Test ở Task 6.
2. Mất mạng giữa lúc tải lên từ điện thoại, hoặc client khai sai `Content-Length`: file tạm bị xóa, bài đang chạy không đổi, app báo lỗi và cho thử lại. Test ở Task 2.
3. Người học đang mở bài thì tác giả cập nhật hoặc bỏ quyền: cập nhật thì file tiếp theo lấy từ bản mới, dữ liệu không mất; bỏ quyền thì app báo mất quyền, không tiếp tục báo "đã lưu". Test ở Task 3 và Task 6.
4. Mở link share khi chưa đăng nhập, kèm tài khoản còn phải đổi mật khẩu tạm: sau khi đăng nhập và đổi mật khẩu vẫn vào được bài. Test ở Task 6.
5. Tác giả xóa thẻ rồi tải bản mới, và thêm thẻ mới: thẻ cũ không còn đến hạn, tiến độ thẻ giữ id còn nguyên, thẻ mới xuất hiện với người đã bắt đầu bài. Test ở Task 2.

---

### Task 1: Migration và danh mục trong database

**Files:**
- Create: `app/catalog.py`, `tests/test_catalog.py`
- Modify: `app/db.py`, `app/main.py`, `app/sandbox.py`, `app/cli.py`, `app/contract.py`, `app/bundle.py`, `tests/test_server.py`, `tests/test_sandbox.py`, `tests/test_contract.py`, `tests/test_bundle.py`, `web/static/app.js`, `web/static/lesson-host.js`
- Delete: `web/static/lesson-shim.js`, `sample/manifest.json`, `sample/demo1/`. Giữ `scripts/package_content.py` vì `scripts/convert_legacy.py` import từ đó.

**Interfaces:**
- Produces:
  - `db.init()` chạy `MIGRATIONS: list[str]` theo `PRAGMA user_version`.
  - `catalog.install_version(owner: str, unpacked: Path) -> dict` trả `{"id", "version", "created": bool}`.
  - `catalog.removed_ids(owner: str, unpacked: Path) -> list[str]`.
  - `catalog.lesson_for(c, user: str, key: str) -> dict | None`, chỉ trả khi user có quyền.
  - `catalog.lessons_for(c, user: str) -> list[dict]`.
  - `catalog.has_access(c, user: str, package_id: str) -> bool`.
  - `catalog.lesson_dir(c, key: str) -> Path | None`.
  - `catalog.progress_id(package_id: str, bare_id: str) -> str`.
  - `catalog.delete_package(package_id: str) -> None`.
  - `catalog.purge_rows(c, package_id: str) -> None`, xóa tiến độ của mọi người trong package.
  - `catalog.sweep() -> None`, chỉ gọi lúc app khởi động.

Dạng `dict` của bài: `id` (chính là key), `doc` (bằng `id`), `package_id`, `package_title`, `author`, `mine`, `ord`, `title`, `summary`, `cards`, `quiz`, `tracks`, `ask_status`. Giữ tên `id` và `doc` để code hiện có ít phải đổi. `cards[].id` và `quiz[].id` là id trần. `tracks` là `{key: {file, label, duration}}`, với `duration` đo lúc cài.

- [ ] **Step 1: Viết test thất bại trong `tests/test_catalog.py`**

```python
def test_migration_keeps_rows_from_old_database(tmp_path, monkeypatch): ...
    # Tạo DB bằng schema cũ (user_version 0) có một user và một card_state.
    # db.init(): user và card_state còn nguyên, user_version == len(MIGRATIONS), chạy lại không lỗi.
def test_failed_migration_leaves_version_and_schema_unchanged(...): ...
    # Một migration lỗi ở câu giữa: version không đổi, cột đã ALTER không còn, sửa xong chạy lại được.
def test_backup_failure_stops_migration(...): ...
def test_premigration_backup_survives_first_backup_loop(...): ...
    # File sao lưu trước migration chứa schema cũ, sau khi db.backup() chạy ngay trong cùng giây vẫn còn.
def test_install_gives_server_ids(ctx):
    # Cài sample/package cho "an": key dạng ^p[0-9a-f]{12}\.[a-z0-9-]+$, card id có cùng tiền tố.
def test_same_slug_other_owner_is_separate_package(ctx):
    # "an" và "binh" cùng cài một zip: 2 package id khác nhau, không dùng chung thẻ.
def test_only_owner_and_shared_can_read(ctx):
    # lesson_for của người lạ trả None; sau khi thêm package_access thì có; revoked_at khác NULL thì None.
def test_update_swaps_pointer_and_removes_old_files(ctx): ...
def test_sweep_removes_only_orphan_package_dirs(ctx):
    # Thư mục p<12 hex> không có dòng trong DB, và thư mục phiên bản khác bản hiện tại, bị xóa; thư mục tên khác giữ nguyên.
def test_retry_after_crash_with_leftover_version_dir(ctx):
    # Có sẵn <id>/<version+1> sót lại: lần cài sau không lồng thư mục, dùng số phiên bản kế tiếp.
def test_two_packages_same_bare_ids_do_not_collide(ctx):
    # Hai package cùng id thẻ và quiz: làm sai "q1" ở mỗi package tạo hai thẻ riêng, mỗi thẻ đúng nội dung của nó.
def test_corrected_quiz_shows_new_text_on_wrong_card(ctx):
    # Tác giả sửa câu quiz, giữ id: thẻ sai hiện nội dung mới; xóa câu đó: thẻ không còn đến hạn.
def test_due_cards_not_starved_by_inaccessible_rows(ctx):
    # 250 thẻ đến hạn của bài đã mất quyền, 5 thẻ của bài còn quyền: /api/cards/due trả đủ 5.
def test_update_resets_ask_when_ai_content_changes(ctx):
    # ask_status approved: đổi thẻ, tóm tắt, quiz hoặc content.md thì về none; chỉ đổi trang hoặc audio thì giữ.
```

- [ ] **Step 2: Chạy, xác nhận thất bại**

Run: `pytest tests/test_catalog.py -q`. Expected: FAIL vì chưa có `app.catalog`.

- [ ] **Step 3: Đổi `db.py` sang migration**

`SCHEMA` hiện tại thành `MIGRATIONS[0]`, vẫn dùng `IF NOT EXISTS` để DB cũ không lỗi. Mỗi migration chạy bằng `executescript(f"BEGIN; {sql}; PRAGMA user_version={n}; COMMIT;")`, và `ROLLBACK` khi lỗi, vì `executescript` tự commit nếu không có `BEGIN` trong script. Nếu DB đã có bảng `users` và có `BACKUP_DIR`, sao lưu trước khi chạy vào file `premigrate-v<n>-<thời gian>.db`. Tên này không bị quy tắc giữ 14 bản của `backup()` xóa và không bị `backup_loop` ghi đè. Sao lưu lỗi thì dừng, không migrate. `MIGRATIONS[1]`:

```sql
ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN quota_bytes INTEGER;
CREATE TABLE packages(
  id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  slug TEXT NOT NULL, title TEXT NOT NULL, topic TEXT NOT NULL, description TEXT NOT NULL,
  version INTEGER NOT NULL, size_bytes INTEGER NOT NULL, link_nonce TEXT,
  ask_status TEXT NOT NULL DEFAULT 'none', ask_hash TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
  UNIQUE(owner, slug));
CREATE TABLE package_lessons(
  key TEXT PRIMARY KEY, package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  ord INTEGER NOT NULL, data TEXT NOT NULL);
CREATE INDEX package_lessons_pkg ON package_lessons(package_id);
CREATE TABLE package_access(
  package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  via TEXT NOT NULL, granted_at REAL NOT NULL, revoked_at REAL, PRIMARY KEY(package_id, user));
CREATE INDEX package_access_user ON package_access(user);
CREATE TABLE feedback(
  id INTEGER PRIMARY KEY, package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  lesson TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL,
  author TEXT REFERENCES users(name) ON DELETE SET NULL, body TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX feedback_pkg ON feedback(package_id, created_at);
```

Sửa `cli.py`: `INSERT INTO users` phải ghi rõ tên cột.

- [ ] **Step 4: Viết `app/catalog.py`**

`install_version` đọc `package.json` và `lesson.json` từ thư mục đã kiểm tra, đo `duration` bằng `contract.audio_seconds`. Số phiên bản mới lớn hơn cả `packages.version` và mọi thư mục số đang có, để thư mục sót lại sau khi app chết không gây lồng thư mục. Chuyển thư mục vào `PACKAGES_DIR/<id>/<version>`. Trong một transaction: thay `package_lessons`; cập nhật `version`, `title`, `topic`, `description`, `size_bytes`, `updated_at`; tính `ask_hash` là SHA-256 của `content.md`, tóm tắt, thẻ, quiz, và đặt `ask_status='none'` nếu hash đổi; với mỗi người có `lesson_progress` của bài, thêm thẻ mới vào `card_state` bằng `ON CONFLICT DO NOTHING`. Commit xong mới xóa thư mục bản cũ bằng `rmtree(ignore_errors=True)`; phần còn sót do `sweep` dọn. Lỗi trước commit thì xóa thư mục bản mới.

`purge_rows` xóa theo tiền tố `<id>.` bằng `substr(col,1,14)=?` trên đúng cột của từng bảng: `card_state.lesson`, `wrong_card.lesson`, `review_log.card_id`, `lesson_progress.lesson`, `listen_pos.episode`, `user_doc.name`. `delete_package` gọi `purge_rows` rồi xóa dòng package trong cùng transaction, sau commit xóa thư mục.

`sweep` chỉ đụng tên khớp `^p[0-9a-f]{12}$`, xóa package không có dòng và thư mục phiên bản khác bản hiện tại. Chỉ chạy trong `lifespan`, cùng việc tạo `PACKAGES_DIR`, `.staging` và dọn `.staging`. CLI không gọi `sweep`, vì tiến trình CLI có thể xóa nhầm thư mục của package web đang cài dở.

**Siết `contract.py`,** vì từ đây server tin kết quả kiểm tra. Thêm lỗi và test cho từng trường hợp: `lessons` rỗng hoặc quá 50 bài; `topic`, `description` không phải chuỗi; `title` quá 200 ký tự, `topic` quá 80, `description` quá 1.000, mỗi đoạn văn bản trong tóm tắt, thẻ, quiz quá 4.000; `options` không phải chuỗi không rỗng; `why` không phải chuỗi; `label` của track thiếu hoặc rỗng; file mp3 không đọc được hoặc thời lượng bằng 0, báo là `Problem`, không để văng lỗi. `read_json_file` từ chối file trên 1 MB trước khi đọc; `index.html` trên 5 MB báo lỗi trước khi đọc. `safe_extract` từ chối mỗi file không phải mp3 trên 32 MB, và entry tên `.`. Hai chỗ `f"...{exc}"` trong `safe_extract` đổi thành câu cố định và ghi `exc` vào log, để không lộ đường dẫn server. Bài 1, 2 và `sample/package` phải vẫn đạt.

- [ ] **Step 5: Đổi `main.py`, `sandbox.py`**

Bỏ `load_content`, `LESSONS`, `BY_ID`, `BY_DOC`, `FILES`, `/content/`. `known_lesson` bị xóa, mọi route dùng `lesson_for`. `lifespan` dừng nếu thiếu `LINK_SECRET`.

Thẻ: `card_front` và `/api/cards/due` không đọc văn bản từ `wrong_card` nữa, mà lấy từ câu quiz hiện tại, để tác giả sửa câu là người học thấy bản đúng; `wrong_card` chỉ còn đánh dấu thẻ này sinh từ câu sai. Thẻ hợp lệ là thẻ của bài user còn quyền và id trần còn trong `cards` hoặc `quiz` của bản hiện tại. `/api/cards/due` đọc các dòng đến hạn của user không `LIMIT`, lọc trong Python, dừng ở 200 thẻ hợp lệ. Số dòng mỗi user nhỏ, nên việc này không tốn. Mỗi thẻ trả thêm `target_type` và `target_id` trần cho nút Báo sai. `due_total` và `next_due` tính trên đúng tập đó. `/api/cards/{id}/review` từ chối thẻ không hợp lệ. `/api/ask` bỏ nhánh `input` và `clean_input`, thêm kiểm tra `ask_status == "approved"`, trả 503 `disabled` nếu chưa duyệt.

Thêm `GET /audio/{key}/{track}`: cần phiên đăng nhập và quyền, chỉ phục vụ file ghi trong `tracks`, `Content-Type: audio/mpeg`, `nosniff`, hỗ trợ `Range`. `/api/lessons` trả `page: "/lesson/<key>"`, `tracks[].url: "/audio/<key>/<track>"`, `package_id`, `package_title`, `author`, `mine`, và `ask` là true khi có khóa AI và `ask_status == "approved"`. `/api/me` bỏ cờ `ai`. Trong `app.js`, mọi chỗ dùng `state.me.ai` đổi sang `ask` của bài đang mở, và link bài cùng audio đọc từ `page`, `tracks[].url` của API, không ghép đường dẫn tay. Sau task này trang đầu vẫn mở được bài và phát được audio; màn hình mới để Task 6.

`sandbox.can_read(c, user_id, lesson)` tra `users.rowid` ra tên rồi gọi `lesson_for`. `/s/` lấy thư mục từ `catalog.lesson_dir`. `learner_code(user_id, package_id)` bỏ `_package_slug`. Thêm `author`, `package_title`, `ask` vào response của `/frame`. Trong `lesson-host.js`: sửa regex dòng 6 thành `^/lesson/(p[0-9a-f]{12}\.[a-z0-9-]+)$`, hiện tên tác giả trên thanh đầu trang, ẩn nút Hỏi khi `ask` là false.

Ghi `# ponytail:` tại `make_token`: rowid có thể dùng lại sau khi xóa user có rowid lớn nhất, token cũ sống tối đa 6 giờ, chấp nhận vì người nhận vẫn phải có quyền; thêm cột id riêng nếu xóa tài khoản thành chuyện thường xuyên.

- [ ] **Step 6: Thêm lệnh CLI**

`python -m app.cli import-package ZIP OWNER`: chạy đúng đường của Task 2 (`safe_extract`, `check_package`, `install_version`), in id package. Task này cài từ thư mục đã giải nén qua hàm dùng chung sẽ viết ở Task 2; tạm thời nhận thư mục và mở rộng nhận zip ở Task 2.

- [ ] **Step 7: Sửa fixture test**

`ctx` trong `tests/test_server.py` và `tests/test_sandbox.py` cài `sample/package` cho user qua catalog. Giữ nguyên ý nghĩa của từng test cũ: chỉ đổi id và cách chuẩn bị. Chỉ ba chỗ được đổi assert: nhánh `input` của `/api/ask` đổi thành khẳng định bị từ chối; bài lạ ở `/api/listen` và `/api/ask` đổi từ 400 thành 404; test `/content/` đổi thành khẳng định route đó trả 404. Test ô Hỏi cần đặt `ask_status='approved'` trong bước chuẩn bị. Thêm test: người lạ nhận 404 ở `/api/doc`, `/api/lessons/<key>/start`, `/finish`, `/frame`, `/quiz-answer`, `/audio`, `/lesson/<key>`, `/api/listen`, `/api/ask`.

- [ ] **Step 8: Chạy toàn bộ test, xác nhận đạt, commit**

Run: `pytest -q tests/test_catalog.py tests/test_contract.py tests/test_bundle.py tests/test_convert.py tests/test_server.py tests/test_sandbox.py`. Expected: tất cả PASS.

Commit: `Store packages and lessons in the database`.

### Task 2: Tải lên hai bước

**Files:**
- Create: `app/uploads.py`, `tests/test_uploads.py`
- Modify: `app/main.py`, `app/cli.py`, `app/bundle.py`

**Interfaces:**
- Consumes: `catalog.install_version`, `catalog.removed_ids`, `bundle.safe_extract`, `contract.check_package`.
- Produces:
  - `POST /api/uploads`, body zip. Trả `{upload_id, title, slug, lessons, is_update, removed, warnings, size}`, hoặc 400 `{code:"invalid", problems:[{path, message}]}`, hoặc 413, 429, 507.
  - `POST /api/uploads/{id}/commit`, JSON `{attest: true, confirm_removed: [...]}`. Trả `{package_id, version}`.
  - `DELETE /api/uploads/{id}`.
  - `uploads.prepare(zip_path: Path, owner: str) -> dict`, dùng chung cho app và CLI.

- [ ] **Step 1: Viết test thất bại**

```python
def test_too_large_refused_before_reading(ctx): # Content-Length > MAX_ZIP -> 413, không có file trong .staging
def test_lying_length_is_counted_while_streaming(ctx): # stream dài hơn MAX_ZIP -> 413, file tạm bị xóa
def test_interrupted_upload_leaves_nothing(ctx): # generator raise giữa chừng -> .staging trống
def test_bad_zips_report_problems_and_keep_running_version(ctx):
    # parametrize: ../, tuyệt đối, tên trùng, symlink, bom nén, đuôi lạ, file không phải zip, thiếu package.json
    # 400 code invalid; problems không chứa đường dẫn server (PACKAGES_DIR); bản đang chạy còn nguyên
def test_stalled_upload_frees_its_slot(ctx, monkeypatch): # không có byte mới quá thời hạn -> file tạm bị xóa, người khác tải lên được
def test_problem_messages_never_contain_server_paths(ctx): # zip có cả "a" và "a/b", và entry ".": 400, không có PACKAGES_DIR trong JSON
def test_bad_contract_values_never_reach_commit(ctx):
    # parametrize: thiếu topic, track thiếu label, mp3 giả, lessons rỗng, option không phải chuỗi -> 400 ở bước tải lên, không phải 500
def test_shared_learner_list_survives_any_accepted_package(ctx): # package đạt kiểm tra, share cho B: /api/lessons của B trả 200
def test_commit_needs_attest(ctx): # 400 khi thiếu attest
def test_commit_only_by_uploader(ctx): # người khác nhận 404
def test_removed_ids_need_confirm(ctx):
    # bản mới bỏ một thẻ: response liệt kê thẻ đó; commit thiếu confirm_removed -> 409; đủ -> 200
def test_kept_ids_keep_progress_removed_stop_due_new_appear(ctx):
    # người học đã review thẻ A: giữ due; thẻ B bị bỏ không còn trong /api/cards/due; thẻ C mới xuất hiện
def test_quota_counts_unpacked_size(ctx): # quota_bytes nhỏ -> 413, bản cũ còn; bản cập nhật tính phần chênh lệch
def test_svg_with_script_cannot_run(ctx): # /s/.../page/x.svg có CSP "sandbox; default-src 'none'" và nosniff
def test_html_outside_iframe_refused(ctx): # thiếu Sec-Fetch-Dest: iframe -> 403
def test_upload_slots_limited(ctx): # cùng người 2 upload đang chạy -> 429; quá 4 toàn app -> 429
def test_new_upload_replaces_users_previous_staged(ctx): # cùng user: bản tạm cũ bị xóa
def test_expired_stage_cleaned(ctx): # bản tạm quá 1 giờ: commit -> 404, thư mục biến mất
def test_low_disk_refused(ctx, monkeypatch): # disk_usage.free < 2 GB -> 507
```

- [ ] **Step 2: Chạy, xác nhận thất bại**

Run: `pytest tests/test_uploads.py -q`. Expected: FAIL.

- [ ] **Step 3: Viết `app/uploads.py` và route**

Route `POST /api/uploads` được miễn giới hạn `read_json`, đọc `request.stream()` ghi vào `PACKAGES_DIR/.staging/<token>.zip`, đếm byte khi nhận, xóa file ở `finally` nếu không xong. `prepare` chạy qua `asyncio.to_thread`. Trạng thái tạm là dict trong bộ nhớ theo `upload_id`, `{user, dir, created, size}`, mỗi user một bản, hết hạn sau 1 giờ. Upload mới và commit gặp bản hết hạn chỉ dọn các mục hết hạn trong dict và bản cũ của chính user đó, không quét thư mục, nên không đụng tới upload đang chạy hay lệnh CLI. Mỗi người 1 upload đang chạy, toàn app tối đa 4, kiểm tra bằng bộ đếm, không xếp hàng, giải phóng ở `finally`. Mỗi lần đọc chunk có `asyncio.wait_for` 60 giây, tổng thời gian tối đa 30 phút. Từ chối khi `shutil.disk_usage(PACKAGES_DIR).free` dưới 2 GB.

Quota: tổng `size_bytes` của user, trừ package cùng slug đang được thay, cộng kích thước mới, không vượt `quota_bytes` hoặc 1 GB. Kiểm tra cả lúc `prepare` và lúc commit.

`Problem.path` từ `safe_extract` có thể chứa đường dẫn server. Sửa `bundle.safe_extract` dùng tên `upload.zip` thay vì `str(zip_path)`. `prepare` là lớp chặn cuối: thay thư mục giải nén và `PACKAGES_DIR` trong cả `path` và `message` trước khi trả. Tối đa 50 lỗi trong response.

Commit: kiểm tra `attest`, tính lại `removed_ids` và so với `confirm_removed`, kiểm tra quota; các lỗi này giữ nguyên bản tạm để gửi lại được, 409 và 400 không làm mất file đã tải. Qua hết thì đánh dấu `committing` trong dict để bấm hai lần chỉ cài một lần, rồi `install_version`. Thành công mới xóa khỏi dict; lỗi thì bỏ dấu `committing`.

- [ ] **Step 4: Mở rộng `import-package` nhận zip qua `uploads.prepare`**

- [ ] **Step 5: Chạy test, xác nhận đạt, commit**

Run: `pytest -q tests/test_uploads.py tests/test_catalog.py tests/test_server.py tests/test_sandbox.py tests/test_bundle.py`. Expected: PASS.

Commit: `Two-step package upload with quota and removal confirmation`.

### Task 3: Thư viện và share

**Files:**
- Create: `tests/test_share.py`
- Modify: `app/catalog.py`, `app/main.py`, `app/sandbox.py`

**Interfaces:**
- Produces:
  - `GET /api/packages` trả `{mine:[{id,title,topic,description,version,size_bytes,lessons,people,link_on,feedback}], shared:[{id,title,topic,description,author,lessons}], used, quota}`.
  - Chỉ chủ sở hữu, người khác nhận 404: `GET /api/packages/{id}/people`; `POST /api/packages/{id}/share` `{email}`; `POST /api/packages/{id}/unshare` `{email}`; `GET /api/packages/{id}/link` trả `{url|null}`; `POST .../link` bật hoặc tạo link mới; `DELETE .../link` tắt.
  - `POST /api/join` `{token}` trả `{package_id, first_lesson}`.
  - `DELETE /api/packages/{id}`.

**Link share, khác với mục 7 của spec:** spec đề xuất lưu băm chuỗi ngẫu nhiên. Cách đó làm chủ sở hữu không xem lại được link, muốn copy lần nữa phải tạo link mới và làm hỏng link đã gửi. Thay bằng: database lưu `link_nonce` ngẫu nhiên 256 bit, link là `/#join=<package_id>.<base64url(HMAC-SHA256(LINK_SECRET, "join|" + package_id + "|" + nonce))>`, so bằng `hmac.compare_digest`. Lộ riêng database không đủ dựng lại link, copy lại được nhiều lần, tạo link mới thì đổi nonce nên link cũ hết tác dụng. Token ở fragment nên không vào log server, không vào `Referer`, và bot xem trước link không thể kích hoạt. Đổi `LINK_SECRET` làm mọi link hết tác dụng, ghi vào `operations.md`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_share_by_email_gives_access_and_listing(ctx): ...
def test_share_unknown_email_reports_clearly(ctx): # 404 code no_account, không tạo dòng
def test_only_owner_can_share_list_link_or_delete(ctx): # người được share và người lạ nhận 404 ở share, unshare, people, cả ba route link, delete, feedback
def test_revoke_cuts_access_immediately_keeps_progress(ctx):
    # sau unshare: /frame, /s/ token cũ (403), /api/doc, /audio, /api/cards/due đều mất; bảng tiến độ còn dòng; share lại thì có lại tiến độ
def test_revoked_user_cannot_rejoin_by_link(ctx): # POST /api/join -> 403
def test_link_join_adds_to_shared_list(ctx): ...
def test_old_link_dies_after_new_link_or_off(ctx): ...
def test_forged_token_and_rate_limit(ctx): # token sai -> 404; quá 10 lần/phút -> 429
def test_owner_joining_own_link_is_noop(ctx): ...
def test_delete_package_removes_files_and_access(ctx): # token cũ 403/404, thư mục biến mất
def test_remove_user_removes_their_packages(ctx, capsys): # cli remove-user -> thư mục biến mất, tiến độ của người học khác trên package đó cũng hết
def test_share_email_case_insensitive(ctx): # " An@X.com " khớp tài khoản an@x.com
def test_package_listing_never_leaks_between_users(ctx): ...
def test_update_while_page_open_serves_new_files_same_doc(ctx):
    # token cấp trước khi cập nhật vẫn đọc được file của bản mới, doc giữ nguyên
```

- [ ] **Step 2: Chạy, xác nhận thất bại**

- [ ] **Step 3: Viết route và hàm catalog**

Share chuẩn hóa email bằng `strip().lower()`, giới hạn 30 lần mỗi phút mỗi người, để không dò email hàng loạt. Tự share cho mình báo lỗi. `unshare` đặt `revoked_at`, không xóa dòng; `share` lại xóa `revoked_at`. `join` từ chối dòng có `revoked_at`. `cli remove-user` lấy danh sách package của user, gọi `purge_rows` cho từng cái trong cùng transaction với lệnh xóa user, rồi sau khi transaction commit, tức ngoài khối `with` ở `cli.py:23`, xóa các thư mục đó.

- [ ] **Step 4: Chạy test, xác nhận đạt, commit**

Commit: `Library, sharing by email or link, revocation`.

### Task 4: Góp ý

**Files:**
- Create: `tests/test_feedback.py`
- Modify: `app/main.py`

**Interfaces:**
- Produces:
  - `POST /api/lessons/{key}/feedback` `{kind: "comment"|"wrong"|"abuse", target_type: "lesson"|"card"|"quiz", target_id, text}`.
  - `GET /api/packages/{id}/feedback`, chủ sở hữu, trả 200 dòng mới nhất `{id, lesson_title, target_type, target_id, target_text, kind, author, body, created_at}`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_learner_sends_owner_reads_with_email(ctx): ...
def test_stranger_cannot_send_or_read(ctx): # đều 404
def test_length_and_kind_validated(ctx): # rỗng, 2001 ký tự, kind lạ, target không có trong bài -> 400
def test_rate_limit_counts_from_database(ctx): # quá 20 lần/giờ mỗi người -> 429, kể cả sau khi khởi động lại
def test_html_stored_as_plain_text(ctx): # "<img src=x>" trả về nguyên văn trong JSON
def test_author_removed_keeps_feedback(ctx, capsys): # author thành null, góp ý còn
```

- [ ] **Step 2: Chạy, xác nhận thất bại**

- [ ] **Step 3: Viết route**

`target_id` là id trần. Với `target_type` khác `lesson`, id phải tồn tại trong đúng `cards` hoặc `quiz` của bài. Báo cáo loại `abuse` hiện chỉ tới tác giả, kèm email người báo, vì màn hình admin nằm ở phần 3. Chấp nhận được khi app còn chỉ cho chủ dự án, và không được cấp cho team trước khi xong phần 3. Việc nâng hạn mức cũng thuộc phần 3. `target_text` lấy từ bài hiện tại, null nếu thẻ đã bị xóa. Đếm giới hạn bằng `SELECT count(*)` trên `feedback`.

- [ ] **Step 4: Chạy test, xác nhận đạt, commit**

Commit: `Feedback on lessons, cards and quiz questions`.

### Task 5: Bản mẫu giao diện bằng Gemini

Bước này không sửa repo. Chạy `agy` ở chế độ chỉ đọc, trong thư mục trống ngoài repo, đưa cho nó `web/static/app.css`, `web/app.html` và mô tả bốn màn hình: Thư viện, Tải lên (chọn file, đang tải, lỗi, xác nhận), Share (email, copy link, danh sách người), Góp ý (form và danh sách của tác giả). Đầu ra là một file HTML tĩnh dùng đúng biến CSS hiện có.

- [ ] **Step 1: Xin 2 phương án, chụp ở 390 và 1440 px, xem cả hai nền sáng và tối.**
- [ ] **Step 2: Chọn một phương án, ghi lý do. Chủ dự án đã giao quyền quyết định, ảnh gửi lại trong báo cáo cuối để chủ dự án đổi nếu muốn.**

### Task 6: Giao diện và kiểm tra trình duyệt

**Files:**
- Create: `web/static/library.js`, `tests/e2e_platform.py`
- Modify: `web/app.html`, `web/static/app.js`, `web/static/app.css`, `web/lesson.html`, `web/static/lesson-host.js`, `web/static/auth-page.js`, `tests/e2e_browser.py`, `tests/e2e_sandbox.py`

**Interfaces:**
- Consumes: các route của Task 2, 3, 4.
- Produces: màn hình `screen-library`, các `<dialog>` `uploadDialog`, `shareDialog`, `feedbackDialog`. `library.js` chứa toàn bộ phần mới, `app.js` chỉ thêm móc nối.

- [ ] **Step 1: Viết `tests/e2e_platform.py`, chạy server thật với thư mục tạm, Chrome thật, hai tài khoản**

Các luồng và điều kiện đạt:
- Tài khoản mới: trang đầu có hướng dẫn và nút Tải lên, các màn hình Ôn lại, Nghe, Flashcard không crash, không có lỗi console.
- Tải zip lên, thấy tóm tắt và ô xác nhận, nút Xác nhận khóa khi chưa tích; xác nhận xong bài hiện ở Thư viện và Trang đầu.
- Zip lỗi hiện danh sách lỗi dễ đọc, không đổi bài đang chạy.
- Bài không có audio: buổi học đi từ Ôn lại sang Flashcard, không có bước Nghe. Bài chỉ có một track: nút chọn track không crash, phát được.
- Share bằng email cho B, email chưa có tài khoản báo lỗi; B thấy bài trong "Được share", mở được, thấy tên tác giả.
- Copy link, mở ở tài khoản C chưa đăng nhập còn mật khẩu tạm: đăng nhập, đổi mật khẩu, tự vào bài.
- A bỏ quyền của B trong lúc B đang mở bài: lần ghi tài liệu tiếp theo, hoặc câu quiz tiếp theo, gỡ khung và báo mất quyền, không thử lại nữa.
- Bài chưa được duyệt ô Hỏi: không có nút Hỏi ở app lẫn trang bài, và không có request `/api/ask` nào.
- B gửi góp ý, biết trước rằng tác giả thấy email; A thấy góp ý ở Thư viện. Góp ý chứa `<img src=x onerror=...>` hiển thị nguyên văn, không chạy.
- Báo sai trên flashcard, và trên câu quiz vừa trả lời trong trang bài.
- Tên package chứa HTML không chạy ở trang đầu, thư viện, thanh đầu trang bài.
- Ở 360, 390, 1024, 1440 px: không cuộn ngang, nút thật sự bấm được, nút tối thiểu 44 px; có ảnh chụp.

- [ ] **Step 2: Chạy, xác nhận thất bại**

- [ ] **Step 3: Viết giao diện theo bản mẫu đã chọn**

`auth-page.js` giữ `location.hash` khi chuyển trang, chỉ khi khớp `^#join=[\w.-]+$`. `app.js` lúc khởi động thấy `#join=` thì gọi `/api/join` trước `refresh()`, xóa hash bằng `history.replaceState`, rồi mở bài. `renderLesson`, `refresh`, `loadTrack` và các chỗ giả định `state.lesson` phải chịu được danh sách bài rỗng và `tracks` thiếu `long`. Tải lên dùng `XMLHttpRequest` để có tiến độ. `lesson-host.js` thêm nút Góp ý, và nút "Báo sai câu này" hiện sau khi `quiz.answer` trả về; trong `flushDoc` và `quiz.answer`, phản hồi 403 hoặc 404 thì xóa `docPending`, dừng hẹn giờ, gỡ khung và báo mất quyền; các lỗi khác vẫn thử lại như cũ.

- [ ] **Step 4: Sửa `tests/e2e_browser.py`, `tests/e2e_sandbox.py` theo id mới, chạy lại cả ba trên Chrome và WebKit, xem ảnh**

- [ ] **Step 5: Commit**

Commit: `Library, upload, share and feedback screens`.

### Task 7: Chuyển bản thật

**Files:**
- Modify: `compose.yml`, `.github/workflows/ci.yml`, `docs/operations.md`, `README.md`, `docs/lesson-format.md`, `docs/design/02-nen-tang-nhieu-tac-gia.md`
- Ngoài repo: `3_deploy.py`, `LESSONS_LEARNED.md`

- [ ] **Step 1: Sửa `compose.yml`:** bỏ mount `content`, `./packages:/packages` có quyền ghi, bỏ `CONTENT_DIR`. CI thêm các file test mới.

- [ ] **Step 2: Sửa tài liệu:** trạng thái spec thành đang xây, ghi khác biệt về link share vào mục 7, cập nhật `operations.md`. Bản đầy đủ tên ngoài repo sửa theo.

- [ ] **Step 3: Quét repo tìm tên riêng, merge `main`, CI xanh.**

- [ ] **Step 4: Deploy theo thứ tự**

1. Sao lưu database, kiểm tra file sao lưu mở được.
2. Dừng app, xóa `packages/package.json` và `packages/lessons/` cũ.
3. Khởi động bản mới, migration chạy.
4. `import-package` zip bài 1, 2 với chủ sở hữu là chủ dự án.
5. Nếu id thẻ và id bài trong zip khớp id cũ, chạy một lần ngoài repo lệnh đổi tiền tố cho `card_state.card_id` và `.lesson`, `review_log.card_id`, `wrong_card.card_id` và `.lesson`, `lesson_progress.lesson`, `listen_pos.episode`, để không mất 12 lượt ôn đã có. `user_doc.name` cũ là tên `doc` trong manifest, khác id bài (ví dụ `lesson2` và `bai02`), nên phải đổi theo bảng `doc` sang key, không chỉ thêm tiền tố. Không khớp thì giữ dòng cũ, vì chúng không hiện ra, và báo chủ dự án.
6. Xóa `content/` trên VM sau khi kiểm tra xong.

- [ ] **Step 5: Kiểm tra từ Internet bằng hai tài khoản thử:** tải lên, share, học, thu hồi, góp ý; rồi xóa tài khoản thử và xác nhận thư mục package biến mất. App khác trên VM vẫn healthy.

- [ ] **Step 6: Cập nhật `LESSONS_LEARNED.md`, xóa worktree và nhánh, kiểm tra đã xóa thật.**
