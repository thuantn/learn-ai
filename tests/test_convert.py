"""Tests for legacy-to-contract conversion."""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.contract import check_package, errors
from scripts.convert_legacy import convert


def make_source(tmp_path):
    """Creates a minimal legacy lesson source tree."""
    src = tmp_path / "src"
    audio = src / "demo" / "audio"
    audio.mkdir(parents=True)
    (audio / "tone.mp3").write_bytes(b"fake mp3")

    summary = src / "demo" / "app" / "summary.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("- Điểm A.\n- Điểm B.\n- Điểm C.\n", encoding="utf-8")

    cards = [
        {"id": "demo-c1", "q": "q1", "a": "a1"},
        {"id": "demo-c2", "q": "q2", "a": "a2"},
        {"id": "demo-c3", "q": "q3", "a": "a3"},
        {"id": "demo-c4", "q": "q4", "a": "a4"},
        {"id": "demo-c5", "q": "q5", "a": "a5"},
    ]
    (src / "demo" / "app" / "cards.json").write_text(json.dumps(cards), encoding="utf-8")

    page = '''<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><title>REAL_NAME</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-mml-chtml.min.js"></script>
</head><body>
<nav><a href="#skip">Skip</a></nav>
<h1>REAL_NAME</h1>
<p>Đoạn văn hiển thị.</p>
<audio src="audio/tone.mp3"></audio>
<script>
const QS=[
{"q":"Câu một","o":["a","b","c"],"a":1},
{"q":"Câu hai","o":["x","y","z"],"a":2}
];
(function(){
function secName(sec){return sec;}
const EXPLAIN={sec:"giải thích"};
async function ask(q){console.log(q);}
function openPanel(prefill){console.log(prefill);}
document.addEventListener("click",function(){
pendingExplain={sec,prompt:EXPLAIN[sec]};
});
})();
</script>
<footer>REAL_NAME</footer>
</body></html>'''
    (src / "demo" / "page.html").write_text(page, encoding="utf-8")
    return src


def make_config(tmp_path, source, extra_replace=None):
    replace = [["REAL_NAME", "TÁC GIẢ MẪU"]]
    if extra_replace:
        replace.extend(extra_replace)
    cfg = {
        "source": str(source),
        "replace": replace,
        "package": {
            "slug": "demo",
            "title": "Bài mẫu",
            "topic": "test",
            "description": "Gói mẫu kiểm tra chuyển đổi.",
        },
        "lessons": [{
            "id": "demo",
            "order": 1,
            "title": "Bài mẫu",
            "folder": "demo",
            "page": "page.html",
            "doc": "demodoc",
            "audio_dir": "audio",
            "tracks": {},
        }],
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg_path


def test_converted_package_is_valid(tmp_path):
    src = make_source(tmp_path)
    cfg = make_config(tmp_path, src)
    out = convert(str(cfg), str(tmp_path / "out"))
    assert errors(check_package(out)) == []


def test_quiz_ids_are_stable_by_position(tmp_path):
    src = make_source(tmp_path)
    cfg = make_config(tmp_path, src)
    out = convert(str(cfg), str(tmp_path / "out"))
    lesson = json.loads((out / "lessons" / "demo" / "lesson.json").read_text(encoding="utf-8"))
    ids = [q["id"] for q in lesson["quiz"]]
    assert ids == ["demo-q0", "demo-q1"]


def test_page_uses_bridge_not_shim(tmp_path):
    src = make_source(tmp_path)
    cfg = make_config(tmp_path, src)
    out = convert(str(cfg), str(tmp_path / "out"))
    html = (out / "lessons" / "demo" / "page" / "index.html").read_text(encoding="utf-8")
    assert "lesson-bridge.js" in html
    assert "lesson-fonts.css" in html
    assert "lesson-shim.js" not in html
    assert 'href="/"' not in html


def test_legacy_patch_missing_stops(tmp_path):
    src = make_source(tmp_path)
    page = (src / "demo" / "page.html").read_text(encoding="utf-8")
    page = page.replace("async function ask(q){", "async function renamedAsk(q){")
    (src / "demo" / "page.html").write_text(page, encoding="utf-8")
    cfg = make_config(tmp_path, src)
    with pytest.raises(SystemExit) as exc:
        convert(str(cfg), str(tmp_path / "out"))
    assert "ask" in str(exc.value)


def test_scripts_are_relative_files(tmp_path):
    import re
    src = make_source(tmp_path)
    cfg = make_config(tmp_path, src)
    out = convert(str(cfg), str(tmp_path / "out"))
    page_dir = out / "lessons" / "demo" / "page"
    assert (page_dir / "page.1.js").is_file()
    html = (page_dir / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<script(?![^>]*\bsrc=)', html) is None


def test_content_md_has_text_not_script(tmp_path):
    src = make_source(tmp_path)
    cfg = make_config(tmp_path, src)
    out = convert(str(cfg), str(tmp_path / "out"))
    md = (out / "lessons" / "demo" / "content.md").read_text(encoding="utf-8")
    assert "Đoạn văn hiển thị" in md
    assert "const QS" not in md
    assert "pendingExplain" not in md


def test_replace_removes_names(tmp_path):
    src = make_source(tmp_path)
    cfg = make_config(tmp_path, src)
    out = convert(str(cfg), str(tmp_path / "out"))
    md = (out / "lessons" / "demo" / "content.md").read_text(encoding="utf-8")
    assert "REAL_NAME" not in md
    html = (out / "lessons" / "demo" / "page" / "index.html").read_text(encoding="utf-8")
    assert "REAL_NAME" not in html
    assert "TÁC GIẢ MẪU" in html


def test_audio_reference_becomes_relative(tmp_path):
    src = make_source(tmp_path)
    cfg = make_config(tmp_path, src)
    out = convert(str(cfg), str(tmp_path / "out"))
    html = (out / "lessons" / "demo" / "page" / "index.html").read_text(encoding="utf-8")
    assert 'src="../audio/tone.mp3"' in html
    assert (out / "lessons" / "demo" / "audio" / "tone.mp3").is_file()


def test_sample_package_is_valid():
    out = ROOT / "sample" / "package"
    assert check_package(out) == []


def test_cli_exits_on_invalid_package(tmp_path, monkeypatch):
    src = make_source(tmp_path)
    cfg = make_config(tmp_path, src)
    (src / "demo" / "app" / "cards.json").unlink()
    from scripts import convert_legacy
    monkeypatch.setattr(convert_legacy, "convert", lambda c, o, d=False: pathlib.Path(o))

    class FakeProblem:
        path = "x"
        code = "bad"
        message = "lỗi"
        severity = "error"

    monkeypatch.setattr(convert_legacy, "check_package", lambda p: [FakeProblem()])
    assert convert_legacy.main([str(cfg), str(tmp_path / "out")]) == 1
