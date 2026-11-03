"""Lesson contract v1 checker. Uses only the standard library, and mutagen for lessons with audio."""
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import pathlib
import re

# The skill runs this where nothing may install. Without it, audio is refused, never let through unchecked.
try:
    from mutagen.mp3 import MP3
except ImportError:
    MP3 = None


ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
FILE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*\Z")
ALLOWED_EXT = {"html", "js", "css", "json", "svg", "png", "jpg", "webp", "woff2", "mp3", "md"}
MAX_JSON = 1 * 1024 * 1024
MAX_PAGE = 5 * 1024 * 1024
MAX_CONTENT = 1 * 1024 * 1024
MAX_META_TOTAL = 16 * 1024 * 1024
# Renders as nothing for the admin who approves the text, but still reaches the model.
INVISIBLE_RE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]")
MAX_TEXT = 4000
MAX_TITLE = 200
MAX_TOPIC = 80
MAX_DESCRIPTION = 1000
MAX_LESSONS = 50
# Test files are copied into the database, so the whole package's tests stay capped.
MAX_TEST_JSON = 5 * 1024 * 1024
MAX_TESTS_TOTAL = 16 * 1024 * 1024
MAX_TESTS = 20
MAX_TEST_ITEMS = 200
MAX_OPTIONS = 8
MAX_OPTION_TEXT = 1000
MAX_BEST_PRACTICE = 1000
MAX_DOMAIN = 100
MAX_MINUTES = 600
MAX_DOCS = 5
MAX_DOMAINS = 12
TEST_LANGS = ("vi", "en")
# Words that name a choice by letter give wrong answers once the options are shuffled.
LETTER_RE = re.compile(
    r"(?i:đáp án|lựa chọn|phương án|option|answer|choice)\s+[A-H]\b"
    r"|\b(?i:cả|both)\s+[A-H]\s+(?i:và|and)\s+[A-H]\b"
    r"|(?i:tất cả|cả|không có).{0,20}(?i:đáp án|lựa chọn|phương án)\s+(?i:trên|nào)"
    r"|(?i:all|none) of the (?i:above|options)"
)
MD_LINK_RE = re.compile(r"\]\(\s*<?([^)\s>]+)")


@dataclass
class Problem:
    path: str
    code: str
    message: str
    severity: str = "error"


def errors(problems):
    """Returns only hard errors; warnings do not block packaging."""
    return [p for p in problems if p.severity == "error"]


def read_json_file(path, limit=MAX_JSON):
    """Reads JSON accepting UTF-8 BOM and CRLF line endings, rejecting huge files."""
    path = pathlib.Path(path)
    if path.stat().st_size > limit:
        raise ValueError("File JSON quá lớn.")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_test_file(path):
    """Reads one tests/<id>.json file, capped at MAX_TEST_JSON."""
    return read_json_file(path, MAX_TEST_JSON)


def unpack_test_file(src, dest):
    """Turns a single .json upload into a package folder, then checks it.

    Every id must pass ID_RE and be unique before any file is written, so a
    hostile body cannot escape the destination folder.
    """
    try:
        body = read_json_file(src, MAX_TESTS_TOTAL)
    except Exception:
        return [Problem("package.json", "json_parse", "Không đọc được file bộ đề.")]
    if not isinstance(body, dict):
        return [Problem("package.json", "json_parse", "File bộ đề phải là một đối tượng.")]
    body_tests = body.get("tests")
    if not isinstance(body_tests, list):
        return [Problem("package.json", "json_parse", "File bộ đề phải có danh sách tests.")]

    entries = []
    seen = set()
    for test in body_tests:
        if not isinstance(test, dict):
            return [Problem("package.json", "bad_id", "Mỗi bộ đề phải là một đối tượng.")]
        test_id = test.get("id")
        if _bad_id(test_id):
            return [Problem("package.json", "bad_id", f"Id bộ đề không hợp lệ: {test_id}.")]
        if test_id in seen:
            return [Problem("package.json", "duplicate_id", f"Id bộ đề bị trùng: {test_id}.")]
        seen.add(test_id)
        entries.append(test)

    package = {
        "contract_version": "v1",
        "slug": body.get("slug", ""),
        "title": body.get("title", ""),
        "topic": body.get("topic", ""),
        "description": body.get("description", ""),
        "lessons": [],
        "tests": [test["id"] for test in entries],
    }
    try:
        dest = pathlib.Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        tests_dir = dest / "tests"
        tests_dir.mkdir(exist_ok=True)
        (dest / "package.json").write_text(json.dumps(package), encoding="utf-8")
        for entry in entries:
            test_body = {k: v for k, v in entry.items() if k != "id"}
            (tests_dir / f"{entry['id']}.json").write_text(json.dumps(test_body), encoding="utf-8")
    except Exception:
        return [Problem("package.json", "write_failed", "Không ghi được package rời file bộ đề.")]
    return check_package(dest)


def audio_seconds(path):
    """Returns the duration of an MP3 file rounded to the nearest second, or None on error."""
    try:
        return int(round(MP3(str(path)).info.length))
    except Exception:
        return None


class PageChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.problems = []
        self.quiz_ids = set()

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if attr_dict.get("data-quiz"):
            self.quiz_ids.add(attr_dict["data-quiz"])
        for name, _ in attrs:
            if name.lower().startswith("on"):
                self.problems.append(Problem(
                    "page/index.html", "page_inline",
                    "Trang có sự kiện inline, sẽ không chạy dưới CSP.", "warning"
                ))
                break
        if tag == "form":
            self.problems.append(Problem(
                "page/index.html", "page_form",
                "Trang có <form>, sandbox không cho gửi form nên nút sẽ không chạy. Dùng nút type=\"button\".", "warning"
            ))
        if tag == "script":
            if "src" not in attr_dict:
                self.problems.append(Problem(
                    "page/index.html", "page_inline",
                    "Trang có script inline, sẽ không chạy dưới CSP.", "warning"
                ))
            else:
                self._check_resource(attr_dict["src"])
        if tag in ("link", "img", "audio", "video", "source", "embed", "iframe"):
            key = "href" if tag == "link" else "src"
            if key in attr_dict:
                self._check_resource(attr_dict[key])

    def _check_resource(self, src):
        if src.startswith("/static/"):
            return
        if src.startswith(("#", "data:", "javascript:")):
            return
        if src.startswith("//"):
            self.problems.append(Problem(
                "page/index.html", "page_external",
                f"Tài nguyên ngoài hoặc không hợp lệ: {src}. Chỉ dùng /static/ hoặc file trong package.", "warning"
            ))
            return
        if "://" not in src:
            return
        self.problems.append(Problem(
            "page/index.html", "page_external",
            f"Tài nguyên ngoài hoặc không hợp lệ: {src}. Chỉ dùng /static/ hoặc file trong package.", "warning"
        ))


def _has_invisible(value):
    if isinstance(value, str):
        return bool(INVISIBLE_RE.search(value))
    if isinstance(value, dict):
        return any(_has_invisible(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_invisible(v) for v in value)
    return False


def _bad_id(value):
    return not isinstance(value, str) or not ID_RE.match(value)


def _bad_name(value):
    return not isinstance(value, str) or not FILE_RE.match(value)


def _too_long(value, limit):
    return isinstance(value, str) and len(value) > limit


def check_package(root, profile="basic"):
    """Validates a lesson package and returns a list of Problems."""
    root = pathlib.Path(root)
    problems = []

    package_path = root / "package.json"
    if not package_path.is_file():
        problems.append(Problem("package.json", "package_json", "Thiếu file package.json."))
        return problems

    try:
        package = read_json_file(package_path)
    except Exception as exc:
        problems.append(Problem("package.json", "json_parse", "Không đọc được package.json."))
        return problems

    if not isinstance(package, dict):
        problems.append(Problem("package.json", "json_parse", "package.json phải là một đối tượng."))
        return problems

    if package.get("contract_version") != "v1":
        problems.append(Problem("package.json", "contract_version", "Phiên bản contract không được hỗ trợ. Chỉ chấp nhận v1."))
        return problems

    slug = package.get("slug", "")
    if _bad_id(slug):
        problems.append(Problem("package.json", "bad_id", f"Slug không hợp lệ: {slug}."))

    title = package.get("title", "")
    if not isinstance(title, str) or not title.strip():
        problems.append(Problem("package.json", "empty_text", "Package đang trống tiêu đề."))
    elif _too_long(title, MAX_TITLE):
        problems.append(Problem("package.json", "text_too_long", f"Tiêu đề quá dài: {len(title)} > {MAX_TITLE}."))

    topic = package.get("topic", "")
    if not isinstance(topic, str):
        problems.append(Problem("package.json", "bad_type", "Topic phải là chuỗi."))
    elif _too_long(topic, MAX_TOPIC):
        problems.append(Problem("package.json", "text_too_long", f"Topic quá dài: {len(topic)} > {MAX_TOPIC}."))

    description = package.get("description", "")
    if not isinstance(description, str):
        problems.append(Problem("package.json", "bad_type", "Description phải là chuỗi."))
    elif _too_long(description, MAX_DESCRIPTION):
        problems.append(Problem("package.json", "text_too_long", f"Mô tả quá dài: {len(description)} > {MAX_DESCRIPTION}."))

    lessons = package.get("lessons", [])
    if not isinstance(lessons, list):
        problems.append(Problem("package.json", "lessons", "Danh sách bài phải là một mảng."))
        return problems
    tests = package.get("tests", [])
    if not isinstance(tests, list):
        problems.append(Problem("package.json", "tests", "Danh sách bộ đề phải là một mảng."))
        return problems
    if not lessons and not tests:
        problems.append(Problem("package.json", "package_empty", "Package phải có ít nhất một bài học hoặc một bộ đề."))
    if len(lessons) > MAX_LESSONS:
        problems.append(Problem("package.json", "lessons_count", f"Số bài phải từ 1 đến {MAX_LESSONS}."))
    if len(tests) > MAX_TESTS:
        problems.append(Problem("package.json", "test_count", f"Số bộ đề tối đa là {MAX_TESTS}."))

    seen_ids = set()
    for lesson_id in lessons:
        if _bad_id(lesson_id):
            problems.append(Problem("package.json", "bad_id", f"Id bài không hợp lệ: {lesson_id}."))
            continue
        if lesson_id in seen_ids:
            problems.append(Problem("package.json", "duplicate_id", f"Id bài bị trùng: {lesson_id}."))
            continue
        seen_ids.add(lesson_id)
        lesson_dir = root / "lessons" / lesson_id
        if not lesson_dir.is_dir():
            problems.append(Problem(f"lessons/{lesson_id}", "lesson_missing", f"Thiếu thư mục bài: lessons/{lesson_id}."))
            continue
        problems.extend(_check_lesson(lesson_dir, lesson_id, profile, seen_ids))

    for test_id in tests:
        if _bad_id(test_id):
            problems.append(Problem("package.json", "bad_id", f"Id bộ đề không hợp lệ: {test_id}."))
            continue
        if test_id in seen_ids:
            problems.append(Problem("package.json", "duplicate_id", f"Id bộ đề bị trùng: {test_id}."))
            continue
        seen_ids.add(test_id)
        problems.extend(_check_test(root, test_id))

    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        parts = rel.split("/")
        for part in parts:
            if part == "package.json":
                continue
            if not _bad_name(part):
                continue
            problems.append(Problem(rel, "file_name", f"Tên file không hợp lệ: {part}. Chỉ dùng chữ thường, số, dấu chấm, gạch dưới, gạch ngang."))
        if path.name == "package.json":
            continue
        if "." not in path.name:
            problems.append(Problem(rel, "file_type", f"File thiếu đuôi: {path.name}."))
            continue
        ext = path.name.rsplit(".", 1)[1]
        if ext not in ALLOWED_EXT:
            problems.append(Problem(rel, "file_type", f"Đuôi file không được chấp nhận: {path.name}. Các đuôi hợp lệ: html, js, css, json, svg, png, jpg, webp, woff2, mp3, md."))

    # lesson.json and content.md are copied into the database, so they stay small however many lessons there are.
    lessons_root = root / "lessons"
    if lessons_root.is_dir():
        meta = sum(f.stat().st_size for d in lessons_root.iterdir() for f in (d / "lesson.json", d / "content.md") if f.is_file())
        if meta > MAX_META_TOTAL:
            problems.append(Problem("lessons", "meta_size", "Tổng lesson.json và content.md của package quá lớn."))

    tests_root = root / "tests"
    if tests_root.is_dir():
        total_tests = sum(f.stat().st_size for f in tests_root.iterdir() if f.is_file())
        if total_tests > MAX_TESTS_TOTAL:
            problems.append(Problem("tests", "test_size", "Tổng dung lượng bộ đề của package quá lớn."))

    return problems


def _has_bad_md_link(text):
    return any(not url.startswith("https://") for url in MD_LINK_RE.findall(text))


def _check_test(root, test_id):
    problems = []
    rel = f"tests/{test_id}.json"
    test_path = pathlib.Path(root) / "tests" / f"{test_id}.json"
    if not test_path.is_file():
        problems.append(Problem(rel, "test_missing", f"Thiếu file bộ đề: {rel}."))
        return problems
    if test_path.stat().st_size > MAX_TEST_JSON:
        problems.append(Problem(rel, "test_size", "File bộ đề quá lớn."))
        return problems
    try:
        test = read_test_file(test_path)
    except Exception:
        problems.append(Problem(rel, "json_parse", "Không đọc được file bộ đề."))
        return problems
    if not isinstance(test, dict):
        problems.append(Problem(rel, "json_parse", "File bộ đề phải là một đối tượng."))
        return problems

    if _has_invisible(test):
        problems.append(Problem(rel, "invisible_text", "Bộ đề có ký tự vô hình. Xóa chúng đi."))

    title = test.get("title", "")
    if not isinstance(title, str) or not title.strip():
        problems.append(Problem(rel, "empty_text", f"Bộ đề {test_id} đang trống tiêu đề."))
    elif _too_long(title, MAX_TITLE):
        problems.append(Problem(rel, "text_too_long", f"Tiêu đề bộ đề quá dài: {len(title)} > {MAX_TITLE}."))

    description = test.get("description", "")
    if not isinstance(description, str):
        problems.append(Problem(rel, "bad_type", "Mô tả bộ đề phải là chuỗi."))
    elif _too_long(description, MAX_DESCRIPTION):
        problems.append(Problem(rel, "text_too_long", f"Mô tả bộ đề quá dài: {len(description)} > {MAX_DESCRIPTION}."))

    lang = test.get("lang", "vi")
    if not isinstance(lang, str) or lang not in TEST_LANGS:
        problems.append(Problem(rel, "test_lang", "Ngôn ngữ bộ đề chỉ chấp nhận vi hoặc en."))

    minutes = test.get("time_limit_minutes", 0)
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not (0 <= minutes <= MAX_MINUTES):
        problems.append(Problem(rel, "test_time", f"Thời gian làm bài phải từ 0 đến {MAX_MINUTES} phút."))

    pass_percent = test.get("pass_percent", 70)
    if not isinstance(pass_percent, int) or isinstance(pass_percent, bool) or not (1 <= pass_percent <= 100):
        problems.append(Problem(rel, "test_pass", "Ngưỡng đậu phải từ 1 đến 100."))

    items = test.get("items")
    if not isinstance(items, list) or not (1 <= len(items) <= MAX_TEST_ITEMS):
        problems.append(Problem(rel, "test_items", f"Số câu phải từ 1 đến {MAX_TEST_ITEMS}."))
        return problems

    seen_items = set()
    domains = set()
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(Problem(rel, "test_items", f"Câu {idx + 1}: Câu hỏi phải là một đối tượng."))
            continue
        iid = item.get("id", "")
        prefix = f"Câu {iid}:"
        if _bad_id(iid):
            problems.append(Problem(rel, "bad_id", f"{prefix} Id câu không hợp lệ: {iid}."))
        elif iid in seen_items:
            problems.append(Problem(rel, "duplicate_id", f"{prefix} Id câu bị trùng: {iid}."))
        else:
            seen_items.add(iid)

        domain = item.get("domain", "")
        if not isinstance(domain, str):
            problems.append(Problem(rel, "bad_type", f"{prefix} Lĩnh vực phải là chuỗi."))
        elif _too_long(domain, MAX_DOMAIN):
            problems.append(Problem(rel, "text_too_long", f"{prefix} Lĩnh vực quá dài."))
        else:
            domains.add((domain.strip() or "Khác").casefold())

        itype = item.get("type")
        if itype not in ("single", "multi"):
            problems.append(Problem(rel, "test_type", f"{prefix} Loại câu chỉ chấp nhận single hoặc multi."))

        question = item.get("question", "")
        if not isinstance(question, str) or not question.strip():
            problems.append(Problem(rel, "empty_text", f"{prefix} Câu hỏi đang trống nội dung."))
        else:
            if _too_long(question, MAX_TEXT):
                problems.append(Problem(rel, "text_too_long", f"{prefix} Câu hỏi quá dài."))
            if _has_bad_md_link(question):
                problems.append(Problem(rel, "bad_link", f"{prefix} Link trong câu hỏi phải bắt đầu bằng https://."))

        options = item.get("options")
        opt_ids = []
        opt_texts = []
        if not isinstance(options, list) or not (2 <= len(options) <= MAX_OPTIONS):
            problems.append(Problem(rel, "test_options", f"{prefix} Số lựa chọn phải từ 2 đến {MAX_OPTIONS}."))
        else:
            bad_opt = False
            for opt in options:
                if not isinstance(opt, dict):
                    bad_opt = True
                    continue
                oid = opt.get("id")
                otext = opt.get("text")
                if not isinstance(oid, str) or len(oid) != 1 or oid not in "ABCDEFGH" or oid in opt_ids:
                    bad_opt = True
                else:
                    opt_ids.append(oid)
                if not isinstance(otext, str) or not otext.strip():
                    bad_opt = True
                else:
                    opt_texts.append(otext)
                    if _too_long(otext, MAX_OPTION_TEXT):
                        problems.append(Problem(rel, "text_too_long", f"{prefix} Nội dung lựa chọn quá dài."))
                    if _has_bad_md_link(otext):
                        problems.append(Problem(rel, "bad_link", f"{prefix} Link trong lựa chọn phải bắt đầu bằng https://."))
                why = opt.get("why", "")
                if not isinstance(why, str):
                    problems.append(Problem(rel, "bad_type", f"{prefix} Giải thích lựa chọn phải là chuỗi."))
                else:
                    opt_texts.append(why)
                    if _too_long(why, MAX_OPTION_TEXT):
                        problems.append(Problem(rel, "text_too_long", f"{prefix} Giải thích lựa chọn quá dài."))
                    if _has_bad_md_link(why):
                        problems.append(Problem(rel, "bad_link", f"{prefix} Link trong giải thích lựa chọn phải bắt đầu bằng https://."))
            if bad_opt:
                problems.append(Problem(rel, "test_options", f"{prefix} Lựa chọn không hợp lệ."))

        correct = item.get("correct")
        if (
            not isinstance(correct, list)
            or not correct
            or any(not isinstance(c, str) or c not in opt_ids for c in correct)
            or len(set(correct)) != len(correct)
            or (itype == "single" and len(correct) != 1)
            or (itype == "multi" and len(correct) < 2)
        ):
            problems.append(Problem(rel, "test_correct", f"{prefix} Đáp án đúng không hợp lệ."))

        explanation = item.get("explanation", "")
        if not isinstance(explanation, str) or not explanation.strip():
            problems.append(Problem(rel, "empty_text", f"{prefix} Lời giải đang trống."))
        else:
            if _too_long(explanation, MAX_TEXT):
                problems.append(Problem(rel, "text_too_long", f"{prefix} Lời giải quá dài."))
            if _has_bad_md_link(explanation):
                problems.append(Problem(rel, "bad_link", f"{prefix} Link trong lời giải phải bắt đầu bằng https://."))

        best_practice = item.get("best_practice", "")
        if not isinstance(best_practice, str):
            problems.append(Problem(rel, "bad_type", f"{prefix} Best practice phải là chuỗi."))
        else:
            if _too_long(best_practice, MAX_BEST_PRACTICE):
                problems.append(Problem(rel, "text_too_long", f"{prefix} Best practice quá dài."))
            if _has_bad_md_link(best_practice):
                problems.append(Problem(rel, "bad_link", f"{prefix} Link trong best practice phải bắt đầu bằng https://."))

        docs = item.get("docs", [])
        if not isinstance(docs, list) or len(docs) > MAX_DOCS:
            problems.append(Problem(rel, "test_docs", f"{prefix} Danh sách docs phải là mảng tối đa {MAX_DOCS} link."))
        else:
            for doc in docs:
                if not isinstance(doc, str) or not doc.startswith("https://"):
                    problems.append(Problem(rel, "bad_link", f"{prefix} Link trong docs phải bắt đầu bằng https://."))
                    break

        shuffle = item.get("shuffle", True)
        if not isinstance(shuffle, bool):
            problems.append(Problem(rel, "bad_type", f"{prefix} Trường shuffle phải là boolean."))
        elif shuffle:
            texts_to_scan = [
                t for t in [question, explanation, best_practice, *opt_texts] if isinstance(t, str)
            ]
            if any(LETTER_RE.search(t) for t in texts_to_scan):
                problems.append(Problem(
                    rel, "test_letters",
                    f"{prefix} Nội dung nhắc tới chữ cái lựa chọn trong khi vẫn xáo thứ tự.",
                    "warning",
                ))

    if len(domains) > MAX_DOMAINS:
        problems.append(Problem(
            rel, "test_domains",
            f"Bộ đề có hơn {MAX_DOMAINS} lĩnh vực ({len(domains)}).",
            "warning",
        ))

    return problems


def _check_lesson(lesson_dir, lesson_id, profile, seen_ids):
    problems = []
    lesson_path = lesson_dir / "lesson.json"
    if not lesson_path.is_file():
        problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "lesson_json", "Thiếu file lesson.json."))
        return problems

    try:
        lesson = read_json_file(lesson_path)
    except Exception as exc:
        problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "json_parse", "Không đọc được lesson.json."))
        return problems

    if not isinstance(lesson, dict):
        problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "json_parse", "lesson.json phải là một đối tượng."))
        return problems

    title = lesson.get("title", "")
    if not isinstance(title, str) or not title.strip():
        problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "empty_text", f"Bài {lesson_id} đang trống tiêu đề."))
    elif _too_long(title, MAX_TITLE):
        problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "text_too_long", f"Tiêu đề bài quá dài: {len(title)} > {MAX_TITLE}."))

    if _has_invisible(lesson):
        problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "invisible_text", "lesson.json có ký tự vô hình. Xóa chúng đi."))
    cards_for_check = lesson.get("cards")
    if title == "Tên bài" or (isinstance(cards_for_check, list) and any(isinstance(x, dict) and str(x.get("q", "")).startswith("Câu hỏi thẻ") for x in cards_for_check)):
        problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "template_left", "lesson.json vẫn còn nội dung của khung mẫu.", "warning"))

    summary = lesson.get("summary", [])
    if not isinstance(summary, list) or not (3 <= len(summary) <= 8):
        problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "summary_count", "Tóm tắt cần 3–8 ý."))
    else:
        for item in summary:
            if not isinstance(item, str) or not item.strip():
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "empty_text", "Ý tóm tắt không được để trống."))
            elif _too_long(item, MAX_TEXT):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "text_too_long", "Ý tóm tắt quá dài."))

    cards = lesson.get("cards", [])
    if not isinstance(cards, list) or not (5 <= len(cards) <= 30):
        problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "cards_count", "Số thẻ phải từ 5 đến 30."))
    else:
        for idx, card in enumerate(cards):
            if not isinstance(card, dict):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "empty_text", f"Thẻ thứ {idx + 1} không phải đối tượng."))
                continue
            cid = card.get("id", "")
            if _bad_id(cid):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "bad_id", f"Id thẻ không hợp lệ: {cid}."))
            elif cid in seen_ids:
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "duplicate_id", f"Id thẻ bị trùng: {cid}."))
            else:
                seen_ids.add(cid)
            q = card.get("q", "")
            if not isinstance(q, str) or not q.strip():
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "empty_text", f"Thẻ {cid} đang trống câu hỏi."))
            elif _too_long(q, MAX_TEXT):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "text_too_long", f"Câu hỏi thẻ {cid} quá dài."))
            a = card.get("a", "")
            if not isinstance(a, str) or not a.strip():
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "empty_text", f"Thẻ {cid} đang trống câu trả lời."))
            elif _too_long(a, MAX_TEXT):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "text_too_long", f"Câu trả lời thẻ {cid} quá dài."))

    quiz = lesson.get("quiz", [])
    if not isinstance(quiz, list):
        problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "quiz_format", "Quiz phải là một mảng."))
    else:
        for q in quiz:
            if not isinstance(q, dict):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "quiz_answer", "Câu quiz không phải đối tượng."))
                continue
            qid = q.get("id", "")
            if _bad_id(qid):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "bad_id", f"Id quiz không hợp lệ: {qid}."))
            elif qid in seen_ids:
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "duplicate_id", f"Id quiz bị trùng: {qid}."))
            else:
                seen_ids.add(qid)
            q_text = q.get("q", "")
            if not isinstance(q_text, str) or not q_text.strip():
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "empty_text", f"Câu {qid} đang trống nội dung."))
            elif _too_long(q_text, MAX_TEXT):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "text_too_long", f"Câu {qid} quá dài."))
            options = q.get("options", [])
            answer = q.get("answer")
            if not isinstance(options, list) or not options or not isinstance(answer, int) or isinstance(answer, bool) or answer < 0 or answer >= len(options):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "quiz_answer", f"Câu {qid} có đáp án không hợp lệ."))
            else:
                bad_option = False
                for opt in options:
                    if not isinstance(opt, str) or not opt.strip():
                        bad_option = True
                        break
                if bad_option:
                    problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "quiz_answer", f"Câu {qid} có lựa chọn không hợp lệ."))
            why = q.get("why", "")
            if not isinstance(why, str):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "bad_type", f"Giải thích câu {qid} phải là chuỗi."))
            elif why and _too_long(why, MAX_TEXT):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "text_too_long", f"Giải thích câu {qid} quá dài."))
        if profile == "full" and len(quiz) != 8:
            problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "full_quiz", "Mức Đầy đủ cần đúng 8 câu quiz."))

    tracks = lesson.get("tracks", {})
    if not isinstance(tracks, dict):
        problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "tracks_format", "Tracks phải là một đối tượng."))
    else:
        for key in tracks:
            if key not in ("short", "long"):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "track_key", f"Track không hợp lệ: {key}. Chỉ chấp nhận short hoặc long."))
        for key, track in tracks.items():
            if not isinstance(track, dict):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "tracks_format", f"Track {key} không phải đối tượng."))
                continue
            label = track.get("label", "")
            if not isinstance(label, str) or not label.strip():
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "track_label", f"Track {key} thiếu nhãn."))
            elif _too_long(label, MAX_TITLE):
                problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "text_too_long", f"Nhãn track {key} quá dài."))
            fname = track.get("file", "")
            if _bad_name(fname) or not fname:
                problems.append(Problem(f"lessons/{lesson_id}/audio/{fname}", "track_missing", f"Không tìm thấy file audio: {fname}."))
            else:
                audio_path = lesson_dir / "audio" / fname
                if not audio_path.is_file():
                    problems.append(Problem(f"lessons/{lesson_id}/audio/{fname}", "track_missing", f"Không tìm thấy file audio: {fname}."))
                else:
                    seconds = audio_seconds(audio_path)
                    if MP3 is None:
                        problems.append(Problem(f"lessons/{lesson_id}/audio/{fname}", "track_bad", "Cần mutagen để kiểm tra audio: chạy pip install mutagen rồi kiểm tra lại."))
                    elif seconds is None or seconds == 0:
                        problems.append(Problem(f"lessons/{lesson_id}/audio/{fname}", "track_bad", f"File mp3 không đọc được hoặc thời lượng bằng 0: {fname}."))

    page_path = lesson_dir / "page" / "index.html"
    if page_path.is_file():
        if page_path.stat().st_size > MAX_PAGE:
            problems.append(Problem(f"lessons/{lesson_id}/page/index.html", "page_size", "Trang bài quá lớn."))
        else:
            try:
                html = page_path.read_text(encoding="utf-8")
                checker = PageChecker()
                checker.feed(html)
                problems.extend(checker.problems)
                known = {q.get("id") for q in lesson.get("quiz", []) if isinstance(q, dict)} if isinstance(lesson.get("quiz"), list) else set()
                for qid in sorted(checker.quiz_ids - known):
                    problems.append(Problem(f"lessons/{lesson_id}/page/index.html", "page_quiz_id", f"Trang có câu {qid} nhưng lesson.json không có, server sẽ không chấm được.", "warning"))
                if profile == "full" and ("Khởi động" not in html or "Đi sâu" not in html):
                    problems.append(Problem(f"lessons/{lesson_id}/page/index.html", "full_sections", "Mức Đầy đủ cần có chuỗi 'Khởi động' và 'Đi sâu' trong trang."))
            except Exception as exc:
                problems.append(Problem(f"lessons/{lesson_id}/page/index.html", "html_parse", "Không đọc được trang."))
    else:
        problems.append(Problem(f"lessons/{lesson_id}/page/index.html", "page_missing", f"Thiếu trang bài: lessons/{lesson_id}/page/index.html."))

    content_path = lesson_dir / "content.md"
    if content_path.is_file():
        if content_path.stat().st_size > MAX_CONTENT:
            problems.append(Problem(f"lessons/{lesson_id}/content.md", "content_size", "File content.md quá lớn."))
        else:
            try:
                if _has_invisible(content_path.read_text(encoding="utf-8-sig")):
                    problems.append(Problem(f"lessons/{lesson_id}/content.md", "invisible_text", "content.md có ký tự vô hình. Xóa chúng đi."))
            except UnicodeDecodeError:
                problems.append(Problem(f"lessons/{lesson_id}/content.md", "content_encoding", "File content.md phải là UTF-8."))
    elif profile == "full":
        problems.append(Problem(f"lessons/{lesson_id}/content.md", "full_content", "Mức Đầy đủ cần có file content.md."))

    return problems
