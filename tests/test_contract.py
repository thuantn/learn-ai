"""Tests for the lesson contract checker."""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.contract import check_package, errors, audio_seconds


@pytest.fixture
def good_package(tmp_path):
    """A valid lesson package with the minimum required content."""
    root = tmp_path / "pkg"
    root.mkdir()
    package = {
        "contract_version": "v1",
        "slug": "demo",
        "title": "Demo",
        "topic": "test",
        "description": "x",
        "lessons": ["demo"],
    }
    (root / "package.json").write_text(json.dumps(package), encoding="utf-8")

    lesson_dir = root / "lessons" / "demo"
    lesson_dir.mkdir(parents=True)
    lesson = {
        "title": "Demo",
        "summary": ["a", "b", "c"],
        "cards": [
            {"id": "demo-c1", "q": "q1", "a": "a1"},
            {"id": "demo-c2", "q": "q2", "a": "a2"},
            {"id": "demo-c3", "q": "q3", "a": "a3"},
            {"id": "demo-c4", "q": "q4", "a": "a4"},
            {"id": "demo-c5", "q": "q5", "a": "a5"},
        ],
        "quiz": [],
        "tracks": {},
    }
    (lesson_dir / "lesson.json").write_text(json.dumps(lesson), encoding="utf-8")

    page_dir = lesson_dir / "page"
    page_dir.mkdir()
    (page_dir / "index.html").write_text(
        "<!doctype html><html><head></head><body><p>Hello</p></body></html>",
        encoding="utf-8",
    )
    return root


def test_good_package_passes(good_package):
    assert check_package(good_package) == []


def test_warning_does_not_block(good_package):
    """An inline event handler is a warning; the package can still be packed."""
    html = (good_package / "lessons" / "demo" / "page" / "index.html").read_text(encoding="utf-8")
    html = html.replace("<p>Hello</p>", '<p onclick="x">Hello</p>')
    (good_package / "lessons" / "demo" / "page" / "index.html").write_text(html, encoding="utf-8")
    problems = check_package(good_package)
    assert errors(problems) == []
    assert any(p.severity == "warning" for p in problems)


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
def test_lesson_rules(good_package, change, code):
    """Each change to lesson.json must produce its expected problem code."""
    path = good_package / "lessons" / "demo" / "lesson.json"
    lesson = json.loads(path.read_text(encoding="utf-8"))
    change(lesson)
    path.write_text(json.dumps(lesson), encoding="utf-8")
    assert code in {p.code for p in check_package(good_package)}


def test_contract_version_unknown_is_refused(good_package):
    """Only contract v1 is supported."""
    package = json.loads((good_package / "package.json").read_text(encoding="utf-8"))
    package["contract_version"] = "v2"
    (good_package / "package.json").write_text(json.dumps(package), encoding="utf-8")
    assert "contract_version" in {p.code for p in check_package(good_package)}


def test_lesson_listed_but_folder_missing(good_package):
    """A lesson id without a matching folder is reported."""
    package = json.loads((good_package / "package.json").read_text(encoding="utf-8"))
    package["lessons"].append("missing")
    (good_package / "package.json").write_text(json.dumps(package), encoding="utf-8")
    assert "lesson_missing" in {p.code for p in check_package(good_package)}


def test_disallowed_extension_and_upper_case(good_package):
    """evil.php is rejected, and A.MP3 must be renamed."""
    lesson_dir = good_package / "lessons" / "demo"
    (lesson_dir / "evil.php").write_text("x", encoding="utf-8")
    audio_dir = lesson_dir / "audio"
    audio_dir.mkdir()
    (audio_dir / "A.MP3").write_bytes(b"x")
    assert "file_type" in {p.code for p in check_package(good_package)}


def test_page_inline_handler_warns_as_broken(good_package):
    """onclick is a warning, not a hard error."""
    html = (good_package / "lessons" / "demo" / "page" / "index.html").read_text(encoding="utf-8")
    html = html.replace("<p>Hello</p>", '<a onclick="go()">x</a>')
    (good_package / "lessons" / "demo" / "page" / "index.html").write_text(html, encoding="utf-8")
    assert "page_inline" in {p.code for p in check_package(good_package)}


def test_page_inline_script_warns_as_broken(good_package):
    """Inline script blocks are a warning."""
    html = (good_package / "lessons" / "demo" / "page" / "index.html").read_text(encoding="utf-8")
    html = html.replace("<head></head>", "<head><script>x</script></head>")
    (good_package / "lessons" / "demo" / "page" / "index.html").write_text(html, encoding="utf-8")
    assert "page_inline" in {p.code for p in check_package(good_package)}


def test_page_external_resource(good_package):
    """Scripts loaded from outside the package are a warning."""
    html = (good_package / "lessons" / "demo" / "page" / "index.html").read_text(encoding="utf-8")
    html = html.replace("<head></head>", '<head><script src="https://x"></script></head>')
    (good_package / "lessons" / "demo" / "page" / "index.html").write_text(html, encoding="utf-8")
    assert "page_external" in {p.code for p in check_package(good_package)}


def test_links_to_other_sites_are_allowed(good_package):
    """Ordinary links to other sites are allowed."""
    html = (good_package / "lessons" / "demo" / "page" / "index.html").read_text(encoding="utf-8")
    html = html.replace("<p>Hello</p>", '<a href="https://x">x</a>')
    (good_package / "lessons" / "demo" / "page" / "index.html").write_text(html, encoding="utf-8")
    assert check_package(good_package) == []


def test_bom_and_crlf_json_is_accepted(good_package):
    """package.json may have a UTF-8 BOM and CRLF line endings."""
    text = "\ufeff{\"contract_version\": \"v1\",\r\n\"slug\": \"demo\",\r\n\"title\": \"Demo\",\r\n\"topic\": \"test\",\r\n\"description\": \"x\",\r\n\"lessons\": [\"demo\"]\r\n}"
    (good_package / "package.json").write_text(text, encoding="utf-8")
    assert check_package(good_package) == []


def test_full_profile_requires_more(good_package):
    """The full profile requires quiz, both tracks, content.md and section headings."""
    codes = {p.code for p in check_package(good_package, "full")}
    assert {"full_quiz", "full_tracks", "full_content", "full_sections"} <= codes


def test_audio_seconds_reads_mp3():
    """tests/fixtures/tone.mp3 lasts about one second."""
    assert audio_seconds(ROOT / "tests" / "fixtures" / "tone.mp3") == 1


def test_static_paths_are_not_external(good_package):
    """Scripts under /static/ are supplied by the app and are not external."""
    html = (good_package / "lessons" / "demo" / "page" / "index.html").read_text(encoding="utf-8")
    html = html.replace("<head></head>", '<head><script src="/static/lesson-bridge.js"></script></head>')
    (good_package / "lessons" / "demo" / "page" / "index.html").write_text(html, encoding="utf-8")
    assert check_package(good_package) == []


def test_wrong_json_types_do_not_crash(good_package):
    """Hostile lesson.json values must produce error Problems, never exceptions."""
    base = json.loads((good_package / "lessons" / "demo" / "lesson.json").read_text(encoding="utf-8"))
    cases = [
        ("summary number", {"summary": ["a", 2, "c"]}, "empty_text"),
        ("cards string", {"cards": [base["cards"][0], base["cards"][1], "bad", base["cards"][2], base["cards"][3], base["cards"][4]]}, "empty_text"),
        ("cards number", {"cards": [base["cards"][0], base["cards"][1], 99, base["cards"][2], base["cards"][3], base["cards"][4]]}, "empty_text"),
        ("card q number", {"cards": [{**base["cards"][0], "q": 123}] + base["cards"][1:]}, "empty_text"),
        ("card a number", {"cards": [{**base["cards"][0], "a": 123}] + base["cards"][1:]}, "empty_text"),
        ("quiz string", {"quiz": ["bad"]}, "quiz_answer"),
        ("quiz number", {"quiz": [42]}, "quiz_answer"),
        ("tracks value string", {"tracks": {"short": "bad.mp3"}}, "tracks_format"),
    ]
    for label, changes, expected in cases:
        lesson = json.loads((good_package / "lessons" / "demo" / "lesson.json").read_text(encoding="utf-8"))
        lesson.update(changes)
        (good_package / "lessons" / "demo" / "lesson.json").write_text(json.dumps(lesson), encoding="utf-8")
        try:
            problems = check_package(good_package)
        except Exception as exc:
            pytest.fail(f"{label} raised {exc}")
        assert expected in {p.code for p in errors(problems)}, f"{label}: expected {expected}, got {problems}"


def test_card_answer_required(good_package):
    """Missing or empty answers, quiz questions and summary items are empty_text."""
    base = json.loads((good_package / "lessons" / "demo" / "lesson.json").read_text(encoding="utf-8"))
    cases = [
        ("missing card a", lambda l: l["cards"][0].pop("a", None), "empty_text"),
        ("empty card a", lambda l: l["cards"][0].update(a=""), "empty_text"),
        ("whitespace card a", lambda l: l["cards"][0].update(a="   "), "empty_text"),
        ("missing quiz q", lambda l: l.update(quiz=[{"id": "q1", "options": ["a", "b"], "answer": 0}]), "empty_text"),
        ("empty quiz q", lambda l: l.update(quiz=[{"id": "q1", "q": "", "options": ["a", "b"], "answer": 0}]), "empty_text"),
        ("summary number", lambda l: l.update(summary=["a", 2, "c"]), "empty_text"),
        ("summary empty", lambda l: l.update(summary=["a", "", "c"]), "empty_text"),
    ]
    for label, change, expected in cases:
        lesson = json.loads((good_package / "lessons" / "demo" / "lesson.json").read_text(encoding="utf-8"))
        change(lesson)
        (good_package / "lessons" / "demo" / "lesson.json").write_text(json.dumps(lesson), encoding="utf-8")
        problems = check_package(good_package)
        assert expected in {p.code for p in errors(problems)}, f"{label}: {problems}"


def test_page_required(good_package):
    """A lesson must contain page/index.html in every profile."""
    (good_package / "lessons" / "demo" / "page" / "index.html").unlink()
    for profile in ("basic", "full"):
        problems = check_package(good_package, profile)
        assert "page_missing" in {p.code for p in errors(problems)}


def test_titles_required(good_package):
    """Package and lesson titles must be present and non-empty."""
    # Missing package title
    package = json.loads((good_package / "package.json").read_text(encoding="utf-8"))
    package.pop("title")
    (good_package / "package.json").write_text(json.dumps(package), encoding="utf-8")
    assert "empty_text" in {p.code for p in errors(check_package(good_package))}

    # Empty package title
    package["title"] = ""
    (good_package / "package.json").write_text(json.dumps(package), encoding="utf-8")
    assert "empty_text" in {p.code for p in errors(check_package(good_package))}

    # Missing lesson title
    package["title"] = "Demo"
    (good_package / "package.json").write_text(json.dumps(package), encoding="utf-8")
    lesson = json.loads((good_package / "lessons" / "demo" / "lesson.json").read_text(encoding="utf-8"))
    lesson.pop("title")
    (good_package / "lessons" / "demo" / "lesson.json").write_text(json.dumps(lesson), encoding="utf-8")
    assert "empty_text" in {p.code for p in errors(check_package(good_package))}


def test_track_file_cannot_leave_audio(good_package):
    """Track file names must stay inside the audio folder."""
    for fname in ["../page/index.html", "foo/bar.mp3", ""]:
        lesson = json.loads((good_package / "lessons" / "demo" / "lesson.json").read_text(encoding="utf-8"))
        lesson["tracks"] = {"short": {"file": fname, "label": "x"}}
        (good_package / "lessons" / "demo" / "lesson.json").write_text(json.dumps(lesson), encoding="utf-8")
        problems = check_package(good_package)
        assert "track_missing" in {p.code for p in errors(problems)}, f"file={fname!r}: {problems}"


def test_protocol_relative_is_external(good_package):
    """Protocol-relative URLs are external resources."""
    html = (good_package / "lessons" / "demo" / "page" / "index.html").read_text(encoding="utf-8")
    html = html.replace("<head></head>", '<head><script src="//evil.example/x.js"></script></head>')
    (good_package / "lessons" / "demo" / "page" / "index.html").write_text(html, encoding="utf-8")
    assert "page_external" in {p.code for p in check_package(good_package)}


def test_quiz_and_card_ids_unique_across_lesson(good_package):
    """Card and quiz IDs must be unique across the whole package."""
    lesson = json.loads((good_package / "lessons" / "demo" / "lesson.json").read_text(encoding="utf-8"))

    # Quiz id equal to a card id
    lesson["quiz"] = [{"id": "demo-c1", "q": "?", "options": ["a", "b"], "answer": 0}]
    (good_package / "lessons" / "demo" / "lesson.json").write_text(json.dumps(lesson), encoding="utf-8")
    problems = check_package(good_package)
    assert "duplicate_id" in {p.code for p in errors(problems)}

    # Same card id in two different lessons
    root = good_package
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    package["lessons"].append("demo2")
    (root / "package.json").write_text(json.dumps(package), encoding="utf-8")

    lesson2_dir = root / "lessons" / "demo2"
    lesson2_dir.mkdir(parents=True)
    lesson2 = dict(lesson)
    lesson2["cards"] = [{"id": "shared-id", "q": "q", "a": "a"}] + lesson2["cards"][1:]
    (lesson2_dir / "lesson.json").write_text(json.dumps(lesson2), encoding="utf-8")
    page_dir = lesson2_dir / "page"
    page_dir.mkdir()
    (page_dir / "index.html").write_text(
        "<!doctype html><html><head></head><body><p>Hello</p></body></html>",
        encoding="utf-8",
    )

    lesson1 = json.loads((root / "lessons" / "demo" / "lesson.json").read_text(encoding="utf-8"))
    lesson1["cards"][0]["id"] = "shared-id"
    (root / "lessons" / "demo" / "lesson.json").write_text(json.dumps(lesson1), encoding="utf-8")

    problems = check_package(root)
    assert "duplicate_id" in {p.code for p in errors(problems)}
