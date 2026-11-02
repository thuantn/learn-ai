"""Lesson contract v1 checker. Uses only the standard library and mutagen."""
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import pathlib
import re

from mutagen.mp3 import MP3


ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
FILE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*\Z")
ALLOWED_EXT = {"html", "js", "css", "json", "svg", "png", "jpg", "webp", "woff2", "mp3", "md"}
MAX_JSON = 1 * 1024 * 1024
MAX_PAGE = 5 * 1024 * 1024
MAX_CONTENT = 1 * 1024 * 1024
MAX_META_TOTAL = 16 * 1024 * 1024
MAX_TEXT = 4000
MAX_TITLE = 200
MAX_TOPIC = 80
MAX_DESCRIPTION = 1000
MAX_LESSONS = 50


@dataclass
class Problem:
    path: str
    code: str
    message: str
    severity: str = "error"


def errors(problems):
    """Returns only hard errors; warnings do not block packaging."""
    return [p for p in problems if p.severity == "error"]


def read_json_file(path):
    """Reads JSON accepting UTF-8 BOM and CRLF line endings, rejecting huge files."""
    path = pathlib.Path(path)
    if path.stat().st_size > MAX_JSON:
        raise ValueError("File JSON quá lớn.")
    return json.loads(path.read_text(encoding="utf-8-sig"))


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

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        for name, _ in attrs:
            if name.lower().startswith("on"):
                self.problems.append(Problem(
                    "page/index.html", "page_inline",
                    "Trang có sự kiện inline, sẽ không chạy dưới CSP.", "warning"
                ))
                break
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
    if not (1 <= len(lessons) <= MAX_LESSONS):
        problems.append(Problem("package.json", "lessons_count", f"Số bài phải từ 1 đến {MAX_LESSONS}."))

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
        if profile == "full" and not ("short" in tracks and "long" in tracks):
            problems.append(Problem(f"lessons/{lesson_id}/lesson.json", "full_tracks", "Mức Đầy đủ cần có cả track short và long."))
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
                    if seconds is None or seconds == 0:
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
                content_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                problems.append(Problem(f"lessons/{lesson_id}/content.md", "content_encoding", "File content.md phải là UTF-8."))
    elif profile == "full":
        problems.append(Problem(f"lessons/{lesson_id}/content.md", "full_content", "Mức Đầy đủ cần có file content.md."))

    return problems
