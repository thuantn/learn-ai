# Bộ đề luyện thi: kế hoạch xây

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tác giả đưa bộ đề trắc nghiệm lên package; người được share làm Thi thử hoặc Luyện tập trên máy tính và điện thoại, xem kết quả theo lĩnh vực, ôn đúng các câu đã sai.

**Architecture:** Đề nằm trong database dưới dạng các bản không đổi. Logic lượt làm nằm trong `app/practice.py`, route trong `app/practice_api.py`. Đáp án chỉ rời server qua một hàm DTO duy nhất, theo luật của từng lượt. Trang làm bài là giao diện của app (`web/static/practice.js`), chữ của tác giả qua bộ lọc chặt.

**Tech Stack:** FastAPI, SQLite WAL, JS thuần, marked và DOMPurify đã vendor, Web Speech, pytest, Playwright.

**Spec:** `docs/design/03-bo-de-luyen-thi.md`

## Global Constraints

- CSP giữ nguyên: script chỉ từ `/static/`, không CDN, không `<script>` inline, không thuộc tính `on*`.
- Giới hạn: tối đa 20 bộ đề mỗi package; 1–200 câu mỗi bộ; 2–8 lựa chọn, id A–H; 5 MB mỗi file đề; 16 MB tổng đề mỗi package; `why` và `best_practice` tối đa 1.000 ký tự; `question` và `explanation` tối đa 4.000 ký tự.
- Giờ: hạn có 5 giây trừ hao. Ôn câu sai: ra khi đúng 2 lần cách nhau ít nhất 12 giờ. Thống kê: ngưỡng 3 người.
- Giao diện tiếng Việt, kiểm tra ở 360 px và màn hình rộng, trên Chrome và WebKit; nút lựa chọn cao ít nhất 44 px.
- Ô Hỏi giữ ZDR. Không bao giờ gửi cả bộ đề cho AI.
- Repo sạch như public: không đề thật, tên miền, tên VM, email, tên khách hàng. Fixture phải là câu tự chế. Quét cả lịch sử chưa push trước khi đẩy.
- Mỗi test file mới phải thêm vào danh sách file ở dòng `pytest` của `.github/workflows/ci.yml`, vì CI liệt kê từng file.
- Khi giao cho model: đường dẫn tuyệt đối, đúng phạm vi file, cấm lệnh git, worktree riêng ở `Downloads\Claude_Workspace\learn-ai-worktrees\<tên>` tạo từ tip hiện tại. Người điều phối tự chạy lại test và đọc diff trước khi commit. Chỉ commit trong `if pytest ...`.

## Review Focus

1. Chữ JSON dán từ AI có bọc ```` ```json ````, có BOM hoặc có câu dẫn phía trước: vẫn nhận nếu phần JSON rõ ràng, nếu không thì báo lỗi dễ hiểu, không crash hộp Tải lên (Task 6).
2. Lựa chọn hiện theo vị trí mới, nên AI hay lời giải nhắc "đáp án B" sẽ sai với người làm: prompt cho AI phải đưa lựa chọn theo nội dung và dặn không dùng chữ cái (Task 5).
3. Hai máy cùng mở một lượt: máy cũ trở lại tab phải thấy câu do máy kia lưu, nhưng không ghi đè câu mình chưa lưu xong (Task 7).
4. Mất mạng lúc đang làm hoặc lúc hết giờ: hiện "Chưa lưu", chặn nộp tới khi lưu xong; server chốt bằng các câu đã lưu (Task 3, Task 7).
5. Tải bản mới xóa hoặc đổi đáp án một câu khi có lượt dở và câu trong mục ôn: lượt dở nộp được trên bản cũ, mục ôn không bị bản cũ làm sai (Task 4).

---

## File Structure

| File | Trách nhiệm |
|---|---|
| `app/contract.py` | Sửa: kiểm tra bộ đề, tách file `.json`. Chỉ dùng thư viện chuẩn vì chạy trong skill |
| `app/db.py` | Sửa: migration 5 |
| `app/catalog.py` | Sửa: cài bộ đề, bản đề, dọn bản cũ, `removed_ids` |
| `app/uploads.py` | Sửa: nhận `.json` |
| `app/admin.py` | Sửa: `has_content`, trang duyệt |
| `app/practice.py` | Mới: xáo, chấm, đồng hồ, DTO, lượt làm, mục ôn, thống kê. Không biết FastAPI |
| `app/practice_api.py` | Mới: route của bộ đề |
| `app/main.py` | Sửa: gắn router, tải lên, góp ý, Hỏi về câu |
| `web/static/practice.js` | Mới: danh sách đề, làm bài, kết quả, ôn, Hỏi về câu |
| `web/static/library.js`, `app.js`, `feedback.js`, `admin.js`, `answer.js`, `app.css`, `web/app.html` | Sửa |
| `web/static/test-prompt.txt` | Mới: đoạn hướng dẫn cho Gemini, ChatGPT |
| `docs/practice-test-format.md` | Mới: định dạng, cũng được đóng vào skill |
| `tests/practice_fixtures.py` | Mới: tạo đề mẫu tự chế |
| `tests/test_test_format.py`, `test_test_install.py`, `test_practice.py`, `test_practice_pool.py`, `test_practice_extras.py`, `e2e_practice.py` | Mới |

---

### Task 1: Định dạng và bộ kiểm tra

**Files:** Sửa `app/contract.py`, `scripts/learnpkg.py`. Test: `tests/test_test_format.py`, `tests/practice_fixtures.py`.

**Interfaces:**
- Produces: `contract.MAX_TEST_JSON = 5*1024*1024`, `contract.MAX_TESTS_TOTAL = 16*1024*1024`, `contract.MAX_TESTS = 20`, `contract.read_json_file(path, limit=MAX_JSON)`, `contract.read_test_file(path)` (đọc với giới hạn `MAX_TEST_JSON`; mọi chỗ đọc file đề đều dùng hàm này), `contract.unpack_test_file(src, dest) -> list[Problem]`. `check_package` kiểm tra thêm `tests`.
- Produces (fixtures): `make_item(id="q1", type="single", correct=("A",), domain="Chung", options=("A","B","C","D"), **extra) -> dict`; `make_test(n=3, title="Đề", **extra) -> dict`; `write_package(root, tests: dict[str, dict], slug="de", lessons=()) -> Path`; `one_file(tests: dict[str, dict], slug="de") -> dict`.

- [ ] **Step 1: Viết test hỏng**

```python
def codes(root): return {p.code for p in contract.check_package(root) if p.severity == "error"}
def warns(root): return {p.code for p in contract.check_package(root) if p.severity == "warning"}

def test_test_only_package_is_valid(tmp_path):
    assert codes(write_package(tmp_path / "p", {"t1": make_test()})) == set()

def test_package_needs_a_lesson_or_a_test(tmp_path):
    assert "package_empty" in codes(write_package(tmp_path / "p", {}))

@pytest.mark.parametrize("change,code", [
    (dict(type="single", correct=["A", "B"]), "test_correct"),
    (dict(type="multi", correct=["A"]), "test_correct"),
    (dict(correct=["Z"]), "test_correct"),
    (dict(id="Bad Id"), "bad_id"),
    (dict(question=""), "empty_text"),
    (dict(question="x" * 4001), "text_too_long"),
    (dict(explanation=""), "empty_text"),
    (dict(docs=["http://a.vn"]), "bad_link"),
    (dict(docs=["javascript:alert(1)"]), "bad_link"),
    (dict(docs=["https://a.vn/" + str(i) for i in range(6)]), "test_docs"),
    (dict(question="xem [đây](javascript:alert(1))"), "bad_link"),
    (dict(explanation="![x](http://a.vn/a.png)"), "bad_link"),
    (dict(question="có​chữ vô hình"), "invisible_text"),
    (dict(options=[{"id": "A", "text": "x"}]), "test_options"),
    (dict(options=[{"id": "A", "text": "x"}, {"id": "A", "text": "y"}]), "test_options"),
    (dict(options=["x", "y"]), "test_options"),
    (dict(options=[{"id": "A", "text": 1}, {"id": "B", "text": "y"}]), "test_options"),
    (dict(options=[{"id": "A", "text": "x", "why": "y" * 1001}, {"id": "B", "text": "y"}]), "text_too_long"),
    (dict(correct="A"), "test_correct"),
    (dict(correct=[["A"]]), "test_correct"),
    (dict(type="essay"), "test_type"),
    (dict(domain=5), "bad_type"),
    (dict(domain="x" * 101), "text_too_long"),
    (dict(best_practice="x" * 1001), "text_too_long"),
    (dict(docs="https://a.vn"), "test_docs"),
    (dict(shuffle="no"), "bad_type"),
])

@pytest.mark.parametrize("change,code", [
    (dict(time_limit_minutes="105"), "test_time"),
    (dict(time_limit_minutes=True), "test_time"),
    (dict(time_limit_minutes=601), "test_time"),
    (dict(pass_percent="78"), "test_pass"),
    (dict(pass_percent=0), "test_pass"),
    (dict(pass_percent=101), "test_pass"),
    (dict(lang="fr"), "test_lang"),
    (dict(title=""), "empty_text"),
    (dict(items="x"), "test_items"),
    (dict(items=[1]), "test_items"),
])
def test_bad_tests(tmp_path, change, code):
    assert code in codes(write_package(tmp_path / "p", {"t1": {**make_test(), **change}}))
def test_bad_items(tmp_path, change, code):
    assert code in codes(write_package(tmp_path / "p", {"t1": make_test(items=[{**make_item(), **change}])}))

def test_duplicate_item_and_test_ids(tmp_path):
    t = make_test(items=[make_item("q1"), make_item("q1")])
    assert "duplicate_id" in codes(write_package(tmp_path / "p", {"t1": t}))
    # Hai bộ đề được dùng chung id câu.
    assert codes(write_package(tmp_path / "q", {"t1": make_test(), "t2": make_test()})) == set()

def test_test_id_must_differ_from_lesson_id(tmp_path):
    assert "duplicate_id" in codes(write_package(tmp_path / "p", {"bai": make_test()}, lessons=["bai"]))

def test_limits(tmp_path):
    assert "test_count" in codes(write_package(tmp_path / "a", {f"t{i}": make_test(1) for i in range(21)}))
    assert "test_items" in codes(write_package(tmp_path / "b", {"t1": make_test(201)}))
    assert "test_size" in codes(write_package(tmp_path / "c", {"t1": make_test(1, description="x" * (5 * 1024 * 1024))}))

def test_letter_reference_warns_unless_kept_in_order(tmp_path):
    mention = make_item(question="Cả A và B đều đúng?")
    assert "test_letters" in warns(write_package(tmp_path / "a", {"t1": make_test(items=[mention])}))
    assert "test_letters" not in warns(write_package(tmp_path / "b", {"t1": make_test(items=[{**mention, "shuffle": False}])}))
    above = make_item(explanation="Tất cả đáp án trên đều đúng.")
    assert "test_letters" in warns(write_package(tmp_path / "c", {"t1": make_test(items=[above])}))

def test_many_domains_warn(tmp_path):
    items = [make_item(f"q{i}", domain=f"L{i}") for i in range(13)]
    assert "test_domains" in warns(write_package(tmp_path / "p", {"t1": make_test(items=items)}))

def test_one_file_unpacks_to_a_package(tmp_path):
    src = tmp_path / "de.json"
    src.write_text(json.dumps(one_file({"t1": make_test()})), encoding="utf-8-sig")
    assert contract.unpack_test_file(src, tmp_path / "out") == []
    assert (tmp_path / "out/tests/t1.json").is_file()
    package = json.loads((tmp_path / "out/package.json").read_text("utf-8"))
    assert package["tests"] == ["t1"] and package["lessons"] == [] and package["contract_version"] == "v1"
    assert codes(tmp_path / "out") == set()

@pytest.mark.parametrize("body", ["[]", "{", '{"slug":"de","title":"x","tests":[{"id":"../x"}]}', '{"slug":"de","title":"x","tests":"x"}'])
def test_one_file_bad_input_writes_nothing_outside(tmp_path, body):
    src = tmp_path / "de.json"
    src.write_text(body, encoding="utf-8")
    assert contract.unpack_test_file(src, tmp_path / "out")
    assert not (tmp_path / "x.json").exists()

def test_one_file_with_duplicate_test_ids_is_refused(tmp_path):
    body = one_file({"t1": make_test()})
    body["tests"] = body["tests"] * 2
    src = tmp_path / "de.json"
    src.write_text(json.dumps(body), encoding="utf-8")
    assert "duplicate_id" in {p.code for p in contract.unpack_test_file(src, tmp_path / "out")}

def test_a_test_file_over_one_megabyte_is_fine(tmp_path):
    items = [make_item(f"q{i}", explanation="x" * 3000) for i in range(190)]
    root = write_package(tmp_path / "p", {"t1": make_test(items=items)})
    assert (root / "tests/t1.json").stat().st_size > 1024 * 1024
    assert codes(root) == set()

def test_learnpkg_validates_a_json_file(tmp_path, capsys):
    src = tmp_path / "de.json"
    src.write_text(json.dumps(one_file({"t1": make_test()})), encoding="utf-8")
    assert learnpkg.main(["validate", str(src)]) == 0
```

Bản sao trong `make_item`: `question`, `options` với `text` và `why`, `explanation` luôn có giá trị hợp lệ.

- [ ] **Step 2: Chạy, thấy hỏng** — `python -m pytest tests/test_test_format.py -q`. Mong đợi: lỗi import hoặc FAIL.

- [ ] **Step 3: Viết code trong `app/contract.py`**

`check_package`: `lessons` và `tests` đều mặc định rỗng; cả hai rỗng là lỗi `package_empty` thay cho `lessons_count` khi không có đề; `lessons` vẫn tối đa 50, `tests` tối đa 20 (`test_count`). Thêm `_check_test(root, test_id) -> list[Problem]`, đường dẫn lỗi là `tests/<id>.json`, thông báo ghi `Câu <id>:`. Link trong Markdown lấy bằng `re.findall(r"\]\(\s*<?([^)\s>]+)", text)`, phải bắt đầu bằng `https://`. Từ tên lựa chọn:

```python
LETTER_RE = re.compile(
    r"(?i:đáp án|lựa chọn|phương án|option|answer|choice)\s+[A-H]\b"
    r"|\b(?i:cả|both)\s+[A-H]\s+(?i:và|and)\s+[A-H]\b"
    r"|(?i:tất cả|cả|không có).{0,20}(?i:đáp án|lựa chọn|phương án)\s+(?i:trên|nào)"
    r"|(?i:all|none) of the (?i:above|options)"
)
```

Lĩnh vực đếm theo `casefold()` sau khi `strip()`. `unpack_test_file` chỉ ghi file sau khi mọi id đã qua `ID_RE` và không trùng. Bộ kiểm tra phải chịu được mọi kiểu dữ liệu sai mà không ném exception, vì `prepare` không bọc `try`: số nguyên phải là `int` và không phải `bool`, chữ phải là `str`, phần tử phải là `dict`.

Sửa `scripts/learnpkg.py`: nếu `args.dir` là file `.json` thì tách vào `tempfile.TemporaryDirectory()` rồi `check_package`.

- [ ] **Step 4: Chạy lại** — `python -m pytest tests/test_test_format.py tests/test_contract.py -q`. Mong đợi: PASS. Nếu test cũ nào khẳng định `lessons_count` cho package rỗng thì sửa sang `package_empty`.

- [ ] **Step 5: Thêm test vào CI rồi commit** — `feat: check practice tests in the package contract`.

---

### Task 2: Cài bộ đề và tải `.json`

**Files:** Sửa `app/db.py`, `app/catalog.py`, `app/uploads.py`, `app/admin.py`, `app/main.py` (route tải lên, `/api/packages`, `/api/join`). Test: `tests/test_test_install.py`.

**Interfaces:**
- Consumes: Task 1.
- Produces: bảng ở migration 5 dưới đây. `catalog.test_row(c, user, key) -> sqlite3.Row | None` (có kiểm tra quyền, gồm `package_id`, `owner`, `ask_status`, `revision_id`); `catalog.revision_data(c, revision_id) -> dict`; `catalog.answer_hash(item) -> str`. Mọi item trong `test_revision.data` đã có `domain` đã trim, mặc định `"Khác"`, và `shuffle` boolean; bộ đề có `lang`, `time_limit_minutes`, `pass_percent`.

Migration 5, thêm vào cuối `MIGRATIONS`. Mọi bảng treo vào `packages` hoặc `users` bằng cascade, nên xóa package hay xóa chủ tài khoản đều sạch:

```sql
CREATE TABLE test_revision(
  id INTEGER PRIMARY KEY, package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  test_key TEXT NOT NULL, content_hash TEXT NOT NULL, data TEXT NOT NULL, created_at REAL NOT NULL,
  UNIQUE(test_key, content_hash));
CREATE TABLE package_tests(
  key TEXT PRIMARY KEY, package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  ord INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, item_count INTEGER NOT NULL,
  time_limit_minutes INTEGER NOT NULL, pass_percent INTEGER NOT NULL,
  revision_id INTEGER NOT NULL REFERENCES test_revision(id) ON DELETE CASCADE);
CREATE INDEX package_tests_pkg ON package_tests(package_id);
CREATE TABLE test_attempt(
  id TEXT PRIMARY KEY, user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  test_key TEXT NOT NULL, revision_id INTEGER NOT NULL REFERENCES test_revision(id) ON DELETE CASCADE,
  mode TEXT NOT NULL CHECK(mode IN ('exam', 'practice', 'review')), layout TEXT NOT NULL,
  started_at REAL NOT NULL, paused_total REAL NOT NULL DEFAULT 0, pause_count INTEGER NOT NULL DEFAULT 0, paused_at REAL,
  submitted_at REAL, score INTEGER, total INTEGER);
CREATE UNIQUE INDEX test_attempt_open ON test_attempt(user, test_key, mode) WHERE submitted_at IS NULL;
CREATE INDEX test_attempt_user ON test_attempt(user, test_key, started_at);
CREATE TABLE test_answer(
  attempt TEXT NOT NULL REFERENCES test_attempt(id) ON DELETE CASCADE, item TEXT NOT NULL,
  chosen TEXT NOT NULL DEFAULT '[]', flagged INTEGER NOT NULL DEFAULT 0,
  answer_hash TEXT, correct INTEGER, graded_at REAL, PRIMARY KEY(attempt, item));
CREATE TABLE test_first_answer(
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  test_key TEXT NOT NULL, item TEXT NOT NULL, answer_hash TEXT NOT NULL, chosen TEXT NOT NULL, correct INTEGER NOT NULL, at REAL NOT NULL,
  PRIMARY KEY(user, test_key, item, answer_hash));
CREATE INDEX test_first_item ON test_first_answer(test_key, item, answer_hash);
CREATE TABLE test_pool(
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  test_key TEXT NOT NULL, item TEXT NOT NULL, answer_hash TEXT NOT NULL, streak INTEGER NOT NULL DEFAULT 0,
  last_correct_at REAL, added_at REAL NOT NULL, PRIMARY KEY(user, test_key, item));
```

Một dòng `test_answer` vừa là câu đang chọn vừa là kết quả chấm (`correct` là NULL tới khi chấm), vì mỗi câu của một lượt chỉ chấm một lần. Lưu từng câu là một UPSERT chỉ cập nhật đúng cột được gửi (`chosen` hoặc `flagged`), không đụng `correct`, `answer_hash`, `graded_at`, nên "lần lưu sau cùng thắng theo từng câu" không cần đọc rồi ghi.

`test_first_answer` là nguồn duy nhất của thống kê: khi chấm một câu có chọn, ở lượt không phải `review`, `INSERT ... ON CONFLICT DO NOTHING`. Làm lại hay hủy lượt xóa `test_attempt` và `test_answer`, nhưng không làm mất lần trả lời đầu. Sửa mục 12 của thiết kế cho khớp, và ghi rõ việc xóa theo là nhờ cascade, không cần thêm vào `purge_rows`.

- [ ] **Step 1: Viết test hỏng**

```python
def test_install_stores_tests_without_answers_in_summary(ctx, capsys, tmp_path): ...
    # package_tests có title, item_count, pass_percent mặc định 70, time_limit_minutes mặc định 0.
    # package_tests không có cột nào chứa "correct"; dữ liệu đầy đủ ở test_revision.

def test_same_content_keeps_the_revision_and_changed_content_adds_one(ctx, capsys, tmp_path): ...
    # Cài cùng đề hai lần: 1 dòng test_revision. Đổi chữ: 2 dòng khi có lượt dùng bản cũ, 1 dòng khi không có.

def test_a_two_megabyte_test_uploads_and_commits(ctx, capsys, tmp_path): ...
    # Đi trọn prepare, removed_ids, install, cài bản mới lần hai. Không có lỗi 500.

def test_zip_without_a_lessons_key_uploads(ctx, capsys, tmp_path): ...
    # package.json không có khóa "lessons": prepare, removed_ids, install đều chạy.

def test_answer_hash_ignores_wording(): 
    a = make_item(); b = {**a, "question": "khác", "explanation": "khác"}
    assert catalog.answer_hash(a) == catalog.answer_hash(b)
    assert catalog.answer_hash(a) != catalog.answer_hash({**a, "correct": ["B"]})

def test_existing_lesson_package_keeps_its_ask_hash(ctx, capsys, tmp_path): ...
    # _hash_ask với lesson không có tests phải bằng đúng giá trị trước khi có tính năng này:
    # cài package chỉ có bài, approve, cài lại y nguyên; ask_status vẫn approved.

def test_changing_a_test_requeues_ask_approval(ctx, capsys, tmp_path): ...
    # approved, đổi lời giải một câu, cài lại: ask_status == "pending".

def test_removed_ids_lists_tests_and_items(ctx, capsys, tmp_path): ...
    # Bỏ cả bộ t2 và câu q2 của t1: removed gồm "test:t2" và "t1/q2".

def test_delete_package_and_owner_leave_no_test_rows(ctx, capsys, tmp_path): ...
    # Sau khi có lượt làm và mục ôn: delete_package rồi remove-user; 5 bảng mới đều 0 dòng.

def test_upload_json_goes_through_the_same_path(ctx, capsys, tmp_path): ...
    # POST /api/uploads content-type application/json: 200, có upload_id, "tests" == ["Đề"], "lessons" == [].
    # Commit xong, GET /api/packages có tests[0].items == 3, first_lesson None.

def test_upload_json_too_large_and_bad_problems(ctx, capsys, tmp_path): ...
    # Thân lớn hơn MAX_TESTS_TOTAL: 413. Id câu trùng: 400, problems có path "tests/t1.json".

def test_upload_zip_with_tests_only_and_with_lessons(ctx, capsys, tmp_path): ...

def test_join_a_test_only_package(ctx, capsys, tmp_path): ...
    # /api/join trả first_lesson None và package_id; người thứ hai thấy package trong /api/packages.shared với tests.

def test_ask_request_accepts_a_test_only_package(ctx, capsys, tmp_path): ...
    # POST ask-request: 200, ask_status pending. /api/admin/packages/{id}/review có "tests" với correct và explanation.
```

Viết hết phần `...` theo đúng lời chú thích, dùng `_ready_client`, `upload_and_commit`, `zip_of` như `tests/test_admin.py`.

- [ ] **Step 2: Chạy, thấy hỏng** — `python -m pytest tests/test_test_install.py -q`.

- [ ] **Step 3: Viết code**
  - Đọc đề bằng `contract.read_test_file` ở `_read_unpacked` và `removed_ids`. Đổi `package["lessons"]` thành `package.get("lessons", [])` ở `uploads.py:121`, `catalog._read_unpacked`, `catalog.removed_ids`.
  - `catalog._read_unpacked` trả `(package, lessons, tests, ask_hash)`; chỉ thêm phần đề vào `ask_parts` khi có đề, để hash của package cũ không đổi.
  - `install_version`, trong cùng transaction: với mỗi bộ đề, `INSERT ... ON CONFLICT(test_key, content_hash) DO NOTHING` vào `test_revision`, thay các dòng `package_tests`; xóa `test_pool` của câu và bộ đề không còn; với câu còn lại mà mã đáp án đổi, `UPDATE test_pool SET answer_hash=?, streak=0, last_correct_at=NULL`; xóa `test_revision` không còn được `package_tests` hay `test_attempt` nào trỏ tới.
  - `catalog.answer_hash(item)`: sha256 của `json.dumps([sorted(o["id"] for o in item["options"]), sorted(item["correct"])])`. Chỉ dùng id, nên sửa đáp án nghĩa là sửa `correct`; Task 9 ghi điều này vào tài liệu định dạng.
  - `catalog.removed_ids`: dùng `package.get("lessons", [])`, thêm `test:<id>` và `<test-id>/<item-id>`.
  - `uploads.receive(stream, path, chunk_timeout=None, total_timeout=None, limit=None)`; `uploads.prepare(path, owner, kind="zip")`, `kind="json"` gọi `contract.unpack_test_file` thay cho `safe_extract`; kết quả có thêm `"tests": [title, ...]`.
  - `/api/uploads`: nhận `application/zip` hoặc `application/json`, `.json` giới hạn `contract.MAX_TESTS_TOTAL`; thêm `"tests"` vào danh sách khóa trả về ở cuối route.
  - `/api/packages`: mỗi package thêm `tests: [{key, title, items, minutes}]`. `/api/admin/overview` thêm `tests` (số bộ).
  - `admin.has_content`: thêm `OR` có dòng `package_tests`. `review` trả thêm `tests` đầy đủ từ bản hiện tại.

- [ ] **Step 4: Chạy lại** — `python -m pytest tests/test_test_install.py tests/test_catalog.py tests/test_uploads.py tests/test_admin.py tests/test_share.py -q`. Mong đợi: PASS. Trên Windows đôi khi có `WinError 5` khi đổi tên thư mục vừa giải nén, chạy lại riêng test đó; lỗi này đã có trên `main`.

- [ ] **Step 5: Commit** — `feat: install practice tests from zip or a single json`.

---

### Task 3: Lượt làm, chấm điểm, giờ, API không lộ đáp án

**Files:** Tạo `app/practice.py`, `app/practice_api.py`; sửa `app/main.py` (`include_router`), `tests/test_catalog.py` và `tests/test_server.py` (thêm `app.practice`, `app.practice_api` vào danh sách module bị xóa khi tạo `ctx`; trong `test_catalog`, `ctx.practice` trỏ tới module mới). Test: `tests/test_practice.py`.

**Interfaces:**
- Consumes: `catalog.test_row`, `catalog.revision_data`, `catalog.answer_hash`.
- Produces trong `app/practice.py`:
  - `clock = time.time`, luôn gọi qua tên này để test đổi được; `GRACE = 5`.
  - `start(c, user, key, mode, restart=False) -> dict | None`, `load(c, user, attempt_id) -> sqlite3.Row | None`, `view(c, user, row) -> dict`.
  - `save(c, row, item_id, chosen=None, flagged=None) -> None`, `check(c, row, item_id, chosen) -> dict`, `pause(c, row)`, `resume(c, row)`, `submit(c, row)`, `discard(c, row)`.
  - `revealed(row, answer_row) -> bool`, `public_item(item, order, answer_row, reveal: bool) -> dict`, `Refused(code, status, message)` là exception.
  - `grade(item, chosen) -> bool`, `item_in(c, row, item_id) -> dict | None` (chỉ tìm trong `layout` của lượt và đọc từ bản đề của lượt; câu ngoài `layout` thì mọi route theo câu trả 404 `item`).
- API, mọi route lọc theo `request.state.user`, id lạ hay của người khác đều 404 như nhau, bị thu hồi quyền cũng 404:

| Route | Kết quả |
|---|---|
| `GET /api/tests` | `{tests: [Summary]}` |
| `GET /api/tests/{key}` | `Summary` + `history: [{id, mode, percent, passed, at}]`, không có đề |
| `POST /api/tests/{key}/attempts` `{mode, restart?}` | `Attempt` |
| `GET /api/attempts/{id}` | `Attempt` |
| `PUT /api/attempts/{id}/items/{item}` `{chosen?, flagged?}` | `{ok: true}` |
| `POST /api/attempts/{id}/items/{item}/check` `{chosen}` | item đã mở đáp án |
| `POST /api/attempts/{id}/pause`, `/resume`, `/submit` | `Attempt` |
| `DELETE /api/attempts/{id}` | `{ok: true}`, chỉ lượt chưa nộp |

`Summary`: `{key, package_id, package_title, title, description, items, minutes, pass_percent, best_percent, pool, open: {exam: id|null, practice: id|null, review: id|null}, ask}`. `best_percent` lấy từ lượt `exam` và `practice` đã nộp.

`Attempt`: `{id, test_key, title, lang, mode, status: "open"|"paused"|"submitted", time_limit_seconds, elapsed, remaining, pause_count, paused_seconds, ask, items, result}`. Lúc `paused`, `items` là `[]`, kể cả câu đã chọn. `result` là `null` tới khi nộp, sau đó là `{score, total, percent, passed, pass_percent, duration_seconds, by_domain: [{domain, correct, total, percent}]}`, `by_domain` sắp phần trăm tăng dần, gộp theo `casefold`.

Item công khai chỉ gồm: `id, domain, type, required, question, options: [{id, text}], chosen, flagged, checked`. Khi `reveal`, thêm `correct, is_correct, explanation, best_practice, docs`, và `why` trong từng lựa chọn. Dùng danh sách trường được phép, không xóa bớt từ bản đầy đủ.

Luật:
- `reveal` đúng khi lượt `exam`, `practice` đã nộp, hoặc lượt `practice`, `review` có `answer_row.correct IS NOT NULL`. Lượt `review` đã nộp vẫn chỉ mở câu đã kiểm tra, nếu không thì bấm nộp là lộ cả mục ôn. Dòng mới chỉ lưu, chưa chấm, thì không mở.
- `load` và `view` lấy quyền từ `test_revision.package_id` qua `catalog.has_access`, và lấy `title`, `lang`, `time_limit_minutes`, `pass_percent` từ `test_revision.data`, không qua `package_tests`: bộ đề đã bị xóa vẫn xem lại được, và tác giả đổi ngưỡng đậu không làm đổi kết quả cũ.
- `start`: chốt lượt quá giờ trước; có lượt dở thì trả nó, trừ khi `restart`, khi đó xóa rồi tạo mới; `IntegrityError` do bấm đúp thì đọc lại lượt dở. `layout` là `[{"id": "q1", "options": ["B", "A"]}]`; xáo bằng `random.SystemRandom`, câu `shuffle: false` giữ thứ tự lựa chọn.
- `save`: mọi id lựa chọn phải thuộc câu, không trùng; `single` tối đa 1, `multi` tối đa `required`. Câu đã kiểm tra thì từ chối `chosen` (409 `checked`) nhưng vẫn nhận `flagged`.
- `check`: chỉ `practice`, `review` (400 `mode`); nhận `chosen` trong thân request, lưu và chấm trong cùng một transaction, để không chấm nhầm lựa chọn cũ khi lần lưu trước còn đang trên đường; phải chọn đủ `required` (400 `count`). Câu đã kiểm tra rồi thì 409 `checked`.
- Đang dừng: `save`, `check`, `submit` trả 409 `paused`. `pause` khi đang dừng và `resume` khi không dừng không làm gì. `discard` luôn được.
- Đã nộp: `save`, `check`, `pause`, `resume`, `submit` trả 409 `submitted`.
- Chốt lười: `load` tự chốt lượt `exam` có giới hạn, không đang dừng, đã dùng quá `limit + GRACE`, với `submitted_at = started_at + paused_total + limit`; `graded_at` và mục ôn dùng đúng mốc đó, không dùng `clock()`, để đọc lại sau nhiều ngày không làm lệch luật 12 giờ. `load` gọi `c.commit()` ngay sau khi chốt, để `Refused` ném sau đó không làm rollback. Sau khi chốt, thao tác ghi trả 409 `submitted`, thân lỗi có `code`. `GET /api/tests`, `GET /api/tests/{key}` và `start` đều chốt lượt quá giờ của người đó.
- `submit` (`exam`, `practice`): chấm mọi câu trong `layout` chưa chấm để tính điểm. Mục ôn và `test_first_answer` chỉ nhận từ lượt `exam` khi nộp và từ `check`; câu Luyện tập chọn dở rồi nộp chỉ tính vào điểm của lượt đó. Câu trống `correct=0`, `chosen='[]'`; chỉ ghi dòng cho câu đã có dòng hoặc đã có chọn, câu không có dòng tính sai khi tính điểm.
- `elapsed = (paused_at hoặc submitted_at hoặc clock()) - started_at - paused_total`. `remaining` là `null` nếu không giới hạn, và không âm.

Ở task này, `grade_into_pool` chưa có; Task 4 sẽ gọi nó ở `check` và `submit`.

- [ ] **Step 1: Viết test hỏng**

```python
SECRET = ("correct", "explanation", "best_practice", "docs", "why", "is_correct")

def leaks(response):
    # Quét thân response thô, gồm cả tên khóa và chuỗi riêng, để bắt được cả lộ dưới tên khóa khác.
    raw = response.text
    return [k for k in SECRET if f'"{k}"' in raw] + [x for x in SENTINELS if x in raw]

def test_open_exam_never_returns_answers_on_any_route(ctx, capsys, tmp_path):
    # start, get, save, pause, resume, /api/tests, /api/tests/{key} đều leaks(...) == [].

def test_practice_reveals_only_the_checked_item(...):
    # check q1: item trả về có correct, why. GET lại: q1 có, q2 thì leaks(q2) == [].
def test_saved_but_unchecked_practice_item_stays_hidden(...):
    # PUT chọn q1 rồi GET: q1 không có đáp án.
def test_check_grades_the_choice_it_carries(...):
    # PUT A rồi check {chosen: [B]}: B được chấm và lưu; PUT A đến muộn sau đó: 409 checked.
def test_flag_after_check_keeps_the_grade(...):
    # flagged sau check: correct, answer_hash, chosen không đổi.
def test_flag_only_save_keeps_the_choice(...):
def test_item_outside_the_layout_is_404(...):
def test_practice_submit_does_not_feed_pool_or_stats_from_unchecked_items(...):
    # Chọn sai rồi nộp không kiểm tra: tính sai trong điểm, test_pool và test_first_answer không có dòng.
def test_changing_pass_percent_keeps_old_results(...):

def test_submitted_attempt_shows_everything(...):
def test_other_users_attempt_is_404_for_every_route(...):
def test_revoked_user_gets_404_but_keeps_rows(...):
def test_exam_refuses_check(...):                      # 400 mode
def test_check_needs_the_required_count(...):          # multi chọn 1 trong 2: 400 count
def test_checked_item_cannot_change_but_can_be_flagged(...):
def test_chosen_outside_the_item_is_refused(...):      # 400 input
def test_partial_multi_saves(...):
def test_last_write_wins_per_item(...):
def test_multi_is_all_or_nothing(...):
def test_blank_counts_as_wrong(...):
def test_score_and_domain_breakdown(...):              # 2 lĩnh vực, sắp yếu nhất lên đầu, "khác"/"Khác" gộp
def test_pass_uses_pass_percent(...):                  # 78% của 100 câu: 78 đậu, 77 không
def test_order_differs_between_attempts_and_stays_on_reload(...):
def test_shuffle_false_keeps_option_order(...):
def test_one_open_attempt_per_mode_and_restart(...):
def test_exam_and_practice_can_be_open_together(...):
def test_expired_exam_grades_saved_answers_on_read(ctx, capsys, tmp_path, monkeypatch):
    # clock tiến quá hạn + 6 s: GET trả status submitted, score đếm câu đã lưu,
    # duration_seconds == time_limit_seconds; start tạo được lượt mới.
def test_save_within_grace_passes_and_after_grace_is_refused(...):   # hạn+4: 200; hạn+6: 409 submitted
def test_pause_stops_the_clock_and_hides_items(...):
    # pause, clock +1000: GET paused, items == [], remaining không đổi, không bị chốt.
    # save, check, submit: 409 paused. resume: items trở lại, pause_count == 1, paused_seconds == 1000.
def test_practice_has_no_time_limit(...):              # remaining None dù đề có giờ
def test_every_read_route_finalizes_an_expired_exam(...):
    # GET /api/tests, GET /api/tests/{key}: open.exam là None và history có lượt đó.
def test_late_finalize_uses_the_deadline_as_the_grade_time(...):
    # Đọc lại sau 3 ngày: graded_at == hạn; test_pool.added_at == hạn.
def test_discard_only_while_open(...):
def test_removed_test_still_shows_old_results(...):    # cài bản không còn bộ đó: GET attempt 200, start 404
```

Mỗi test viết đủ assert theo lời chú thích; dùng `make_test`, cài bằng `catalog.install_version`. `practice_fixtures.SENTINELS` là các chuỗi riêng mà `make_item` đặt trong `explanation`, `why` và `best_practice`.

- [ ] **Step 2: Chạy, thấy hỏng.**
- [ ] **Step 3: Viết `app/practice.py` và `app/practice_api.py`**, route theo mẫu `app/admin.py`, dùng `web_util.bad` và `read_json`, `Refused` đổi thành `bad(status, code, message)` ở một chỗ.
- [ ] **Step 4: Chạy lại** — `python -m pytest tests/test_practice.py -q`. Sau đó `python -m pytest tests/test_server.py -q` để chắc route mới cũng cần đăng nhập.
- [ ] **Step 5: Thêm test vào CI rồi commit** — `feat: run practice test attempts on the server`.

---

### Task 4: Ôn câu sai

**Files:** Sửa `app/practice.py`, `app/practice_api.py`. Test: `tests/test_practice_pool.py`.

**Interfaces:**
- Produces: `practice.apply_to_pool(c, row, item_id, chosen, correct, now) -> None`, được gọi đúng một lần cho mỗi câu ở `check` và khi nộp lượt `exam`. `Summary.pool` là số câu đang chờ. `start(..., mode="review")` trả 400 `empty` khi mục trống.

Luật của `apply_to_pool`:
- Bỏ qua nếu câu không còn ở bản hiện tại, hoặc mã đáp án của bản hiện tại khác `answer_hash` của lượt. Nhờ vậy lượt dở trên bản cũ không làm sai mục ôn.
- `chosen` rỗng: không làm gì.
- Sai: upsert, `streak=0`, `last_correct_at=NULL`, cập nhật `answer_hash`.
- Đúng, chưa có dòng: không làm gì.
- Đúng, `streak=0`: `streak=1`, `last_correct_at=now`.
- Đúng, `streak>=1`: nếu `now - last_correct_at >= 12*3600` thì xóa dòng, nếu chưa đủ thì giữ nguyên.

Lượt `review`: `layout` chỉ gồm các câu đang trong mục, lấy từ bản hiện tại; `submit` không chấm câu chưa kiểm tra, không có `score`, `result` là `null` và không vào `history`.

`start(mode="review")`, theo đúng thứ tự: có lượt dở trên bản hiện tại, còn câu chưa kiểm tra đang trong mục, và không `restart` thì trả lượt đó; còn lại xóa lượt dở nếu có; mục trống thì 400 `empty`; tạo lượt mới. Như vậy lượt đã kiểm tra hết không chặn lần ôn sau.

- [ ] **Step 1: Viết test hỏng**

```python
def test_wrong_enters_blank_does_not(...):
def test_exam_only_enters_at_submit(...):              # lưu sai chưa nộp: pool == 0; nộp: 1
def test_practice_enters_on_check(...):
def test_two_correct_under_12_hours_stays(...):
def test_two_correct_12_hours_apart_leaves(...):       # đúng ở Thi thử cũng tính
def test_wrong_resets_the_count(...):
def test_review_has_only_pool_items_and_no_history(...):
def test_review_progress_counts_without_finishing(...):
def test_empty_pool_cannot_start_review(...):
def test_finished_but_unsubmitted_review_does_not_block_the_next(...):
    # Kiểm tra hết rồi đóng trang; 12 giờ sau start lại: lượt mới, chấm được, câu đúng lần 2 rời mục.
def test_open_review_with_unchecked_items_resumes(...):
def test_review_result_is_null(...):
def test_submitting_a_review_does_not_reveal_unchecked_items(...):   # leaks(...) == [] sau khi nộp ngay
def test_open_review_on_an_old_revision_is_replaced(...):
def test_new_answer_resets_streak(...):                # đổi correct: streak về 0, hash mới
def test_removed_item_leaves_the_pool(...):
def test_old_revision_attempt_cannot_touch_pool(...):
    # Lượt dở trên bản cũ, tác giả đổi đáp án q1 và xóa q2. Nộp lượt cũ: 200, điểm theo bản cũ,
    # q1 và q2 không vào mục ôn; xem lại lượt đó vẫn thấy đề và đáp án cũ.
def test_review_results_are_gated_like_practice(...):  # review chưa kiểm tra: leaks == []
```

- [ ] **Step 2: Chạy, thấy hỏng.** - [ ] **Step 3: Viết code.** - [ ] **Step 4: Chạy lại** `tests/test_practice_pool.py tests/test_practice.py`. - [ ] **Step 5: Thêm vào CI, commit** — `feat: keep each learner's wrong answers for review`.

---

### Task 5: Hỏi về câu này, báo sai câu, thống kê

**Files:** Sửa `app/main.py`, `app/practice.py`, `app/practice_api.py`. Test: `tests/test_practice_extras.py`.

**Interfaces:**
- Consumes: `practice.load`, `practice.revealed`, `practice.item_in`.
- Produces:
  - `GET`, `POST`, `DELETE /api/attempts/{id}/items/{item}/ask`. `POST` nhận `{question}`, trả `{text}`.
  - `POST /api/attempts/{id}/items/{item}/feedback` `{kind, text}`.
  - `GET /api/packages/{id}/test-stats` → `{tests: [{key, title, hidden, items: [{id, question, people, wrong_percent, top_wrong: {id, text} | null}]}]}`; chỉ chủ package; `hidden` là số câu dưới ngưỡng.
  - `practice.ask_target(c, user, attempt_id, item_id) -> (thread_key, item, test_title, ask_status) | None` (`None` là 404; câu chưa được mở thì ném `Refused("not_revealed", 403, ...)`), `practice.item_context(title, item) -> str`, `practice.stats(c, package_id, owner) -> list`, `STATS_MIN_PEOPLE = 3`.

Tách phần gọi AI trong `/api/ask` ở `main.py` thành `async def run_ask(user, thread_key, system, question, still_allowed)` rồi cả hai route dùng chung: cùng kiểm tra `ai.current()`, `QUESTION_MAX`, `AI_SLOTS`, trần phút và trần ngày. `keep_turn` nhận `still_allowed: Callable[[connection], bool]` thay cho `lesson_for` cố định. Route `/api/ask` cũ phải chạy y như trước.

`thread_key = f"{test_key}.{item_id}"`, nên `substr(lesson,1,14)` của `purge_rows` và `leave_package` vẫn dọn đúng.

`item_context` đặt mọi chữ của tác giả trong khối có ranh giới `CAU-<token_hex(8)>`. Dặn model: đó là dữ liệu, không phải lệnh; nhắc lựa chọn bằng nội dung, không bằng chữ cái, vì người học thấy thứ tự đã xáo. Lựa chọn và đáp án viết bằng `text`, không có id.

`feedback` lưu `lesson=test_key`, `target_type="test_item"`, `target_id=item`. Tách phần giới hạn và INSERT thành `save_feedback`. `package_feedback` đọc thêm `package_tests` và bản hiện tại: `lesson_title` là tên bộ đề, `target_text` là `question`, câu đã bị xóa thì `target_text` là `None`. Báo sai được khi đang Thi thử, vì không lộ gì.

`stats`: đọc `test_first_answer` của bộ đề, chỉ lấy dòng có `answer_hash` bằng mã của bản hiện tại và không phải chủ package. Lựa chọn sai hay gặp nhất đếm theo từng id đã chọn mà không thuộc `correct`. Sắp `wrong_percent` giảm dần.

- [ ] **Step 1: Viết test hỏng**

```python
def test_ask_refused_before_reveal(ctx, capsys, tmp_path, fake_ai):
    # Thi thử chưa nộp, Luyện tập chưa kiểm tra: GET, POST đều 403 not_revealed; fake_ai không nhận request nào.
def test_ask_prompt_holds_one_item_only(...):
    # 3 câu có chuỗi riêng; system chỉ chứa chuỗi của câu đang hỏi, có đáp án, có ranh giới CAU-.
def test_ask_prompt_names_options_by_text(...):        # không có "A." hay id lựa chọn nào làm nhãn; có dặn không dùng chữ cái
def test_ask_needs_approval_and_uses_zdr_path(...):    # ask_status khác approved: 503 disabled
def test_ask_thread_is_per_item_and_survives_reload(...):
def test_ask_shares_daily_quota_with_lessons(...):
def test_leave_removes_item_threads_and_delete_clears_one(...):
def test_lesson_ask_still_works(...):                  # hồi quy
def test_feedback_on_item_reaches_author_with_question(...):
def test_feedback_unknown_item_is_refused(...):
def test_stats_hidden_under_three_people(...):         # 2 người: items == [], hidden == n
def test_stats_excludes_author_and_review_and_blanks(...):
def test_stats_count_first_answer_only(...):           # sai rồi làm lại đúng vẫn tính sai, kể cả khi Làm lại xóa lượt Luyện tập đang dở
def test_stats_restart_after_answer_change(...):
def test_stats_owner_only_and_no_names(...):           # người khác 404; JSON không có tên người làm
```

`fake_ai`: fixture đổi `ai.call` và `ai.current` bằng `monkeypatch`, ghi lại `messages`.

- [ ] **Step 2: Chạy, thấy hỏng.** - [ ] **Step 3: Viết code.** - [ ] **Step 4: Chạy lại** `tests/test_practice_extras.py tests/test_ai.py tests/test_server.py tests/test_admin.py`. - [ ] **Step 5: Thêm vào CI, commit** — `feat: explain, report and measure test items`.

---

### Task 6: Danh sách đề và tải lên trên giao diện

**Files:** Tạo `web/static/practice.js` (phần danh sách), `web/static/test-prompt.txt`; sửa `web/app.html`, `web/static/app.js`, `web/static/library.js`, `web/static/app.css`. Test: `tests/e2e_practice.py`.

**Interfaces:**
- Consumes: `/api/tests`, `/api/packages`, `/api/uploads`.
- Produces: `app.js` `go(id, replace, hash)`, tham số thứ ba là hash giữ nguyên trên URL. `practice.js` có `testRoute() -> bool` đọc `#tests`, `#tests=<pkg>`, `#test=<key>`, `#attempt=<id>`, `#result=<id>`. Danh sách `SCREENS` thêm `tests`, `test-detail`, `test-run`, `test-result`. `go` với id ngoài danh sách vẫn về `home`, nên `hashchange` thành `if (!joinFromLink() && !testRoute()) go(...)` và cuối `init` thành `if (!testRoute()) go(location.hash.slice(1) || "home", true)`. `renderTestText(text) -> string` (HTML đã lọc), `testPrompt` đọc từ `/static/test-prompt.txt`, `parseTestJson(text) -> object` (ném lỗi có thông báo tiếng Việt), `mergeTestFiles(list) -> object`.

`renderTestText`, đúng cấu hình này:

```js
DOMPurify.sanitize(marked.parse(text), {
  ALLOWED_TAGS: ["p", "br", "strong", "em", "code", "pre", "ul", "ol", "li", "blockquote", "table", "thead", "tbody", "tr", "th", "td", "a"],
  ALLOWED_ATTR: ["href"], ALLOWED_URI_REGEXP: /^https:/i,
})
```

Link trong đề: chặn sự kiện ở vùng chứa, `confirm` kèm địa chỉ, rồi `window.open(href, "_blank", "noopener,noreferrer")`. Lĩnh vực, tiêu đề, lựa chọn: `textContent`.

`parseTestJson`, đúng thứ tự: bỏ BOM rồi thử nguyên văn; nếu lỗi thì chỉ bỏ một khối ```` ``` ```` bọc ngoài cùng rồi thử; nếu vẫn lỗi thì thử đoạn từ `{` đầu tiên tới `}` cuối cùng. Không xóa ```` ``` ```` ở nơi khác, vì `question` được phép chứa khối code. `mergeTestFiles`: khác `slug` thì báo lỗi; gộp `tests`, trùng id để server báo.

Giao diện:
- Trang đầu: mục "Bộ đề" dưới danh sách bài, chỉ hiện khi có đề: tên, số câu, thời gian, điểm cao nhất, số câu chờ ôn. Tài khoản chỉ có đề không thấy lời "chưa có bài" như thể trống.
- Màn `tests`: danh sách, lọc theo package khi có `=<pkg>`. Màn `#test=<key>`: mô tả, lịch sử, các nút Thi thử, Luyện tập, Ôn câu sai (ẩn khi `pool == 0`); có lượt dở thì nút chính là Tiếp tục, Làm lại là nút phụ có `confirm`.
- Thư viện: pill `N đề`; nút Học ẩn khi `first_lesson` rỗng; nút "Làm đề" tới `#tests=<id>`, thêm nút "Thống kê đề" cho tác giả ở Task 8.
- `joinFromLink`: không có `first_lesson` thì `location.hash = "#tests=" + d.package_id`, không dùng `location.replace` vì cùng trang thì không tải lại và `init` có thể ghi đè. `init` đọc `location.hash` ở bước cuối, nên thứ tự nào cũng đúng.
- `refresh()` tải thêm `/api/tests` vào `state.tests` trước `renderLesson()`, để tài khoản chỉ có đề không thấy lời "Chưa có bài học nào" và trang đầu cập nhật sau khi tải lên, xóa hay làm xong đề.
- Hộp Tải lên: nhận `.zip,.json`, cho chọn nhiều file `.json`; ô dán JSON; nút "Hướng dẫn cho AI khác" copy `test-prompt.txt`. Ở màn xác nhận, `upMeta` ghi `N bài, M đề` và `upLessons` liệt kê cả hai; `showConfirm` không được giả định `d.lessons` khác rỗng.

- [ ] **Step 1: Viết `tests/e2e_practice.py`**, dùng `check, free_port, login_first, make_zip` như `tests/e2e_admin.py`, nhận `--browser chrome|webkit`, ghi ảnh vào `SHOTS`. Kiểm tra:

```python
check("dán JSON có bọc khối code", ...)         # hộp dán nhận ```json ...``` kèm câu dẫn, tới bước xác nhận; question có khối code bên trong vẫn nguyên sau khi cài
check("dán chữ hỏng báo lỗi", ...)               # alert hiện, hộp không đóng, console không có lỗi
check("3 file cùng slug thành 3 bộ", ...)
check("khác slug bị từ chối", ...)
check("nút Học ẩn với package chỉ có đề", ...)
check("share link vào thẳng danh sách đề", ...)  # người thứ hai mở #join=..., xác nhận, thấy bộ đề
check("trang đầu có mục Bộ đề", ...)
check("không tràn ngang ở 360 px", pg.evaluate("document.documentElement.scrollWidth") <= 360)
check("đề độc không chạy", ...)                  # tiêu đề và question có XSS, <style>*{display:none}</style>, <svg onload=...>; __xss undefined, nút vẫn hiện
```

- [ ] **Step 2: Chạy, thấy hỏng** — `python tests/e2e_practice.py --browser chrome`.
- [ ] **Step 3: Viết code.**
- [ ] **Step 4: Chạy lại cả hai trình duyệt, xem ảnh chụp** ở 360 px và màn hình rộng. Mong đợi: `FAILS: 0`.
- [ ] **Step 5: Commit** — `feat: list practice tests and upload them from the app`.

---

### Task 7: Trang làm bài và kết quả

**Files:** Sửa `web/static/practice.js`, `web/app.html`, `web/static/app.css`. Test: `tests/e2e_practice.py`.

**Interfaces:**
- Consumes: mọi route của Task 3, Task 4.
- Produces: `body.in-test` trên màn làm bài; `#testGrid`, `#testSave` ("Đã lưu", "Đang lưu", "Chưa lưu"), `#testTimer`; `data-option="<id>"`, `data-act="test-check|test-next|test-prev|test-flag|test-pause|test-submit"` để e2e dùng.

Yêu cầu chốt:
- Chỉ vẽ một câu một lúc trong DOM, để đề 200 câu vẫn nhẹ trên điện thoại.
- `leaveAttempt()`: khi rời `#attempt=` bằng menu hay nút Back, bỏ `body.in-test`, dừng đồng hồ và hẹn giờ thử lại, gọi `speechSynthesis.cancel()`. Không tự nộp khi đã rời; giờ server vẫn chạy và lần đọc sau tự chốt.
- Lưu: mỗi câu một hàng đợi; đang gửi mà chọn tiếp thì gửi bản mới nhất sau đó; lỗi mạng hoặc 5xx thì hiện "Chưa lưu", thử lại sau 3 giây. Trả lời 4xx là dứt khoát: bỏ mục đó khỏi hàng đợi rồi tải lại lượt, không thử lại mãi. Nộp phải chờ lưu xong, không xong thì báo và không nộp. Kiểm tra gửi kèm `chosen` đang hiện trên màn hình.
- `visibilitychange` khi trở lại: tải lại lượt và cập nhật, nhưng giữ câu đang có thay đổi chưa lưu. Ghi nhận 409 `submitted` hay `paused` bằng cách tải lại lượt.
- Đồng hồ: tính từ `remaining` và `performance.now()`; về 0 thì nộp, nộp lỗi thì tải lại lượt khi có mạng.
- Tạm dừng: che đề, nút Tiếp tục; không lưu gì khi đang dừng.
- Nộp: hộp xác nhận liệt kê số câu chưa làm và các câu gắn cờ, bấm số để quay lại câu đó.
- Kết quả: điểm, Đậu hay Chưa đậu, thời gian, số lần và tổng thời gian dừng, bảng lĩnh vực; lọc tất cả, câu sai, câu gắn cờ; mỗi câu hiện lựa chọn của người làm, đáp án đúng, lời giải, `why`, best practice, link; nút Ôn câu sai, Làm lại.
- Luyện tập: câu đã kiểm tra hiện đáp án ngay, khóa lựa chọn.
- Lựa chọn hiện chữ theo vị trí A, B, C, không theo id gốc. Câu chọn nhiều ghi "chọn N".
- Điện thoại: thanh gọn câu X/N, giờ, Tạm dừng, lưới; lưới trong khung kéo lên. `body.in-test` ẩn dock nghe, thanh nổi và menu nổi.
- Cỡ chữ: 4 mức, `localStorage` khóa `learn.test-font`, có `try/catch`; đổi qua biến CSS.
- Giọng đọc: `speechSynthesis`, đọc chữ đã lọc của câu rồi từng lựa chọn; chọn giọng theo `lang`; không có giọng hợp thì ẩn nút và ghi lý do; có nút dừng, tự dừng khi đổi câu.

- [ ] **Step 1: Thêm vào `tests/e2e_practice.py`**

```python
check("Thi thử không có đáp án trong trang", ...)      # sau khi chọn: nội dung trang và mọi response /api không có chuỗi lời giải riêng
check("tải lại vẫn đúng câu và thứ tự", ...)
check("hai máy: máy cũ thấy câu máy kia lưu", ...)     # 2 context; context 1 lưu; context 2 phát visibilitychange
check("Kiểm tra chấm đúng lựa chọn đang hiện", ...)   # chọn A, chọn B, bấm Kiểm tra khi PUT bị route làm chậm
check("mất mạng hiện Chưa lưu và chặn nộp", ...)       # context.set_offline(True), chọn, nộp bị chặn; online lại, lưu xong, nộp được
check("hết giờ tự nộp", ...)                           # đề 1 phút với clock server đổi ở LAUNCH, hoặc attempt có started_at chỉnh trong DB
check("đóng máy rồi mở lại thấy kết quả", ...)
check("Tạm dừng che đề", ...)                          # không thấy chữ câu hỏi trong DOM
check("Luyện tập hiện đúng sai và why", ...)
check("chọn nhiều cần đủ số", ...)
check("kết quả có bảng lĩnh vực, lọc câu sai", ...)
check("Ôn câu sai chỉ có câu sai", ...)
check("nút lựa chọn cao ít nhất 44 px ở 360 px", ...)
check("không tràn ngang ở 360 px khi làm bài và ở kết quả", ...)
check("dock nghe không che nút khi làm bài", ...)
check("cỡ chữ còn sau khi tải lại", ...)
check("nút giọng đọc hoặc lý do ẩn đều hiện đúng", ...)
check("rời màn làm bài bằng Back dọn sạch", ...)       # body không còn in-test, dock hiện lại, không có request nộp
check("console sạch", ...)
```

- [ ] **Step 2: Chạy, thấy hỏng.** - [ ] **Step 3: Viết code.**
- [ ] **Step 4: Chạy cả Chrome và WebKit, xem ảnh chụp** màn làm bài, dừng, kết quả ở 360 px và rộng; sửa những gì mắt thấy sai rồi thêm kiểm tra. Mong đợi: `FAILS: 0`.
- [ ] **Step 5: Commit** — `feat: take practice tests and read the results`.

---

### Task 8: Hỏi về câu, báo sai, thống kê, duyệt của admin trên giao diện

**Files:** Sửa `web/static/practice.js`, `web/static/feedback.js`, `web/static/library.js`, `web/static/admin.js`, `web/static/answer.js`, `web/app.html`. Test: `tests/e2e_practice.py`, `tests/e2e_admin.py`.

**Interfaces:** Consumes: Task 5. `openFeedback` nhận thêm `url`, mặc định vẫn là route của bài học.

- `renderAnswer`: thêm `"style"` vào `FORBID_TAGS`, vì câu trả lời của AI giờ hiện ngay cạnh đề và có thể chép lại chữ của tác giả. Hỏi về câu mở `<dialog>` riêng, dùng `renderAnswer` và MathJax như ô Hỏi; chỉ hiện nút khi `ask` đúng và câu đã mở đáp án. Xóa hội thoại có `confirm`.
- Báo sai câu: nút ở mọi câu, kể cả đang Thi thử.
- Thống kê: nút "Thống kê đề" ở Thư viện của tác giả, trong dialog; hiện câu, số người, tỉ lệ sai, lựa chọn sai nhiều nhất; dòng "còn N câu chưa đủ 3 người".
- Góp ý của tác giả: hiện tên bộ đề và câu.
- `admin.js`: duyệt hiện cả bộ đề, gồm đáp án và lời giải; pill `N đề`. Admin đọc chữ của tác giả bằng `textContent`.

- [ ] **Step 1: Thêm kiểm tra**

```python
check("không có nút Hỏi khi đang Thi thử", ...)
check("Hỏi về câu chạy sau khi kiểm tra, còn sau khi tải lại", ...)   # FakeAI như e2e_admin; SEEN chỉ có câu đó
check("câu trả lời có <style> không làm hỏng trang", ...)
check("báo sai tới tác giả kèm câu", ...)
check("thống kê ẩn dưới 3 người, hiện khi đủ", ...)
check("admin duyệt thấy đề", ...)
```

- [ ] **Step 2: Chạy, thấy hỏng.** - [ ] **Step 3: Viết code.** - [ ] **Step 4: Chạy `tests/e2e_practice.py` và `tests/e2e_admin.py` trên Chrome và WebKit, xem ảnh.** - [ ] **Step 5: Commit** — `feat: ask about items, report them and show the author's stats`.

---

### Task 9: Skill và tài liệu cho AI khác

**Files:** Tạo `docs/practice-test-format.md`; sửa `web/static/test-prompt.txt`, `skills/creating-learn-packages/SKILL.md`, `docs/lesson-format.md`, `app/main.py` (`TOOLKIT_FILES`), `README.md`, `docs/design/03-bo-de-luyen-thi.md` (mục 12 và trạng thái). Test: `tests/test_toolkit.py`.

- `TOOLKIT_FILES` thêm `references/practice-test-format.md` từ `docs/practice-test-format.md`.
- `SKILL.md`: thêm nhánh bộ đề; `description` vẫn tối đa 200 ký tự và nhắc tới bộ đề, practice test. Hướng dẫn: viết một file `.json`, `learnpkg.py validate <file>`, tải lên.
- `practice-test-format.md` ghi: sửa đáp án là sửa `correct`, không đổi chỗ chữ giữa các lựa chọn, vì thống kê và mục ôn chỉ bắt đầu lại khi `correct` đổi.
- `test-prompt.txt` nói rõ: chỉ trả JSON; ví dụ hoàn chỉnh một câu chọn một và một câu chọn nhiều; tự kiểm tra từng đáp án; giải thích cả lựa chọn sai trong `why`; nhắc nội dung lựa chọn thay vì chữ cái; `domain` chỉ một lĩnh vực chính, tối đa 12 lĩnh vực; file dài thì trả từng bộ, cùng `slug`.

- [ ] **Step 1: Viết test hỏng**

```python
def test_zip_has_the_test_format(): ...                # references/practice-test-format.md có trong zip
def test_skill_description_stays_short(): ...          # <= 200 ký tự, có chữ "practice test" hoặc "bộ đề"
def test_prompt_example_passes_the_checker(tmp_path):  # lấy khối JSON trong test-prompt.txt, unpack_test_file, không có lỗi
def test_format_doc_example_passes_the_checker(tmp_path): ...
```

- [ ] **Step 2: Chạy, thấy hỏng.** - [ ] **Step 3: Viết tài liệu.** - [ ] **Step 4: Chạy lại `tests/test_toolkit.py`.**
- [ ] **Step 5: Thử bằng agent mới, môi trường chỉ có Python:** cho một đoạn tài liệu ngắn tự chế, chỉ đưa skill. File JSON tạo ra phải qua `learnpkg validate`, và server nhận được. Mong đợi: không cần ai sửa tay.
- [ ] **Step 6: Commit** — `docs: teach the skill and other AIs the practice test format`.

---

### Task 10: Chuyển file thật, deploy, kiểm tra bản thật

Người điều phối tự làm, không giao model free, vì có đề thật và thao tác trên server. Không commit gì của bước này vào repo.

- [ ] **Step 1: Chuyển file 180 câu theo đúng đường của skill.** Viết script trong scratchpad đọc `examSet1/2/3` từ file HTML của chủ dự án, ánh xạ `scenario` vào `question`, gọn `domain` về lĩnh vực chính (tối đa 12 mỗi bộ), tạo 3 file `.json` cùng `slug`.
- [ ] **Step 2: So bằng máy với file gốc.** Mỗi bộ 60 câu; 161 câu chọn một, 19 câu chọn hai; `correct`, `type`, `options` khớp từng câu; `time_limit_minutes` 105, `pass_percent` 78. `learnpkg validate` không có lỗi. Mong đợi: 0 khác biệt, in số đếm.
- [ ] **Step 3: Toàn bộ test.** `python -m pytest -q` và cả `e2e_practice`, `e2e_admin`, `e2e_platform`, `e2e_browser` trên Chrome và WebKit. Quét từ khóa cấm trên cây và lịch sử chưa push.
- [ ] **Step 4: Merge vào `main`, chờ CI xanh, deploy** bằng `3_deploy.py`. Kiểm tra có `premigrate` backup trên VM, `user_version` = 5, site công khai trả 200, bài 1, 2 và tiến độ còn nguyên.
- [ ] **Step 5: Thử trên bản thật** bằng script trong scratchpad: tải lên 3 file qua hộp Tải lên; làm trọn một lượt Thi thử và một lượt Luyện tập; share cho tài khoản thử, thử gọi API lấy đáp án; xóa tài khoản thử. Xem ảnh ở 360 px và rộng. Package đề thật giữ lại cho chủ dự án, không share cho ai.
- [ ] **Step 6: Đo tải trên VM.** Script gọi `PUT .../items/...` từ 50 phiên giả lập, mỗi phiên một lần mỗi giây, trong 60 giây, trên một bản tạm dùng database tạm, không đụng dữ liệu thật. Ghi độ trễ p50, p95, tỉ lệ lỗi, RAM vào `LESSONS_LEARNED.md`. Đây là số đo cho câu hỏi SQLite có đủ không.
- [ ] **Step 7: Dọn và cập nhật.** Xóa worktree, nhánh và kiểm là xóa được; cài lại skill vào `~/.claude/skills`, tạo lại zip; cập nhật `HANDOFF.md`, `LESSONS_LEARNED.md`. Báo chủ dự án điều gì đã và chưa kiểm tra.
