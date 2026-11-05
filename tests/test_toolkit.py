"""Tests for the skill download: one zip that Claude app, web and Claude Code all accept."""
import io
import json
import pathlib
import re
import subprocess
import sys
import zipfile

from test_catalog import _ready_client, ctx  # noqa: F401

NAME = "creating-learn-packages"


def fetch(ctx, capsys, dest):
    c = _ready_client(ctx, capsys)
    with c:
        r = c.get("/api/toolkit.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert f'filename="{NAME}.zip"' in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        z.extractall(dest)
    return names


def learnpkg(skill, *args, cwd):
    """-S leaves out site-packages, as where nothing can be installed: the skill must stand on the standard library."""
    return subprocess.run(
        [sys.executable, "-S", "-B", str(skill / "scripts" / "learnpkg.py"), *args], cwd=cwd, capture_output=True, encoding="utf-8",
    )


def test_zip_has_the_skill_folder_as_its_only_root(ctx, capsys, tmp_path):
    names = fetch(ctx, capsys, tmp_path)
    assert sorted(names) == sorted(ctx.main.TOOLKIT_FILES)
    assert {pathlib.PurePosixPath(n).parts[0] for n in names} == {NAME}
    assert f"{NAME}/SKILL.md" in names
    for name in names:
        assert "\\" not in name
        assert not any(part.startswith(".") or part == "__pycache__" or part.endswith(".pyc") for part in pathlib.PurePosixPath(name).parts), name


def test_frontmatter_meets_the_upload_rules(ctx, capsys, tmp_path):
    fetch(ctx, capsys, tmp_path)
    text = (tmp_path / NAME / "SKILL.md").read_text("utf-8")
    fields = dict(line.split(": ", 1) for line in text.split("---\n")[1].strip().splitlines())
    assert set(fields) == {"name", "description"}
    assert fields["name"] == NAME and re.fullmatch(r"[a-z0-9-]{1,64}", fields["name"])
    assert not re.search("anthropic|claude", fields["name"])
    assert len(fields["description"]) <= 200, len(fields["description"])
    assert "<" not in fields["description"] and ">" not in fields["description"]


def test_every_path_the_skill_names_is_in_the_zip(ctx, capsys, tmp_path):
    fetch(ctx, capsys, tmp_path)
    skill = tmp_path / NAME
    text = (skill / "SKILL.md").read_text("utf-8") + (skill / "references" / "lesson-format.md").read_text("utf-8")
    for path in ("references/lesson-format.md", "scripts/learnpkg.py", "template/"):
        assert path in text, path
        assert (skill / path).exists(), path
    assert "docs/lesson-format.md" not in text


def test_works_with_only_python_from_any_folder(ctx, capsys, tmp_path):
    fetch(ctx, capsys, tmp_path / "kit")
    skill = tmp_path / "kit" / NAME
    work = tmp_path / "elsewhere"
    work.mkdir()
    before = sorted(p.as_posix() for p in skill.rglob("*"))
    out = learnpkg(skill, "validate", str(skill / "template"), cwd=work)
    assert out.returncode == 0, out.stdout + out.stderr
    out = learnpkg(skill, "pack", str(skill / "template"), "bai.zip", cwd=work)
    assert out.returncode == 0 and (work / "bai.zip").is_file(), out.stdout + out.stderr
    assert sorted(p.as_posix() for p in skill.rglob("*")) == before, "the skill folder may be read-only"


def test_the_draft_command_in_the_skill_works_with_only_python(ctx, capsys, tmp_path):
    fetch(ctx, capsys, tmp_path / "kit")
    skill = tmp_path / "kit" / NAME
    assert "python -m zipfile -c NHÁP.zip THƯ_MỤC" in (skill / "SKILL.md").read_text("utf-8")
    out = subprocess.run([sys.executable, "-S", "-B", "-m", "zipfile", "-c", "nhap.zip", str(skill / "template")], cwd=tmp_path, capture_output=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    with zipfile.ZipFile(tmp_path / "nhap.zip") as z:
        assert "template/package.json" in z.namelist()


def test_audio_without_mutagen_says_what_to_do(ctx, capsys, tmp_path):
    fetch(ctx, capsys, tmp_path / "kit")
    skill = tmp_path / "kit" / NAME
    work = tmp_path / "bai"
    import shutil
    shutil.copytree(skill / "template", work)
    lesson = work / "lessons" / "bai-mau"
    (lesson / "audio").mkdir()
    shutil.copy(pathlib.Path(__file__).parent / "fixtures" / "tone.mp3", lesson / "audio" / "a.mp3")
    data = json.loads((lesson / "lesson.json").read_text("utf-8"))
    data["tracks"] = {"short": {"file": "a.mp3", "label": "Ngắn"}}
    (lesson / "lesson.json").write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    out = learnpkg(skill, "validate", str(work), cwd=tmp_path)
    assert out.returncode == 1 and "pip install mutagen" in out.stdout and "Traceback" not in out.stderr, out.stdout + out.stderr


def test_server_still_refuses_a_broken_mp3(ctx, tmp_path):
    from app import contract
    bad = tmp_path / "x.mp3"
    bad.write_bytes(b"not audio")
    assert contract.MP3 is not None
    assert contract.audio_seconds(bad) is None


def test_every_skill_file_is_in_the_list(ctx):
    root = pathlib.Path(ctx.main.__file__).resolve().parent.parent
    on_disk = {p.relative_to(root).as_posix() for p in (root / "skills").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert on_disk <= set(ctx.main.TOOLKIT_FILES.values()), "a new skill file must be added to TOOLKIT_FILES"


def test_toolkit_needs_login(ctx):
    from test_catalog import _client
    with _client(ctx) as c:
        assert c.get("/api/toolkit.zip").status_code == 401




def test_zip_has_the_test_format(ctx, capsys, tmp_path):
    entry = f"{NAME}/references/practice-test-format.md"
    assert entry in fetch(ctx, capsys, tmp_path)
    source = pathlib.Path(ctx.main.__file__).resolve().parent.parent / "docs" / "practice-test-format.md"
    assert (tmp_path / entry).read_text("utf-8") == source.read_text("utf-8")


def test_the_image_holds_every_toolkit_file(ctx):
    """The zip is built inside the image, which has only what .dockerignore lets through and the Dockerfile copies."""
    root = pathlib.Path(ctx.main.__file__).resolve().parent.parent
    copied = re.findall(r"^COPY (\S+) ", (root / "Dockerfile").read_text("utf-8"), re.M)
    allowed = [l[1:] for l in (root / ".dockerignore").read_text("utf-8").splitlines() if l.startswith("!")]

    def inside(path, roots):
        return any(path == r or path.startswith(r + "/") for r in roots)

    assert not [s for s in ctx.main.TOOLKIT_FILES.values() if not (inside(s, copied) and inside(s, allowed))]


def test_skill_description_stays_short(ctx, capsys, tmp_path):
    fetch(ctx, capsys, tmp_path)
    text = (tmp_path / NAME / "SKILL.md").read_text("utf-8")
    desc = dict(line.split(": ", 1) for line in text.split("---\n")[1].strip().splitlines())["description"]
    assert len(desc) <= 200, len(desc)
    assert re.search(r"practice test|bộ đề", desc, re.IGNORECASE)


def json_block(text, after=""):
    """The first ```json block after the heading `after`."""
    m = re.search(r"```json[^\S\r\n]*\r?\n(.*?)\r?\n```", text[text.index(after):], re.DOTALL)
    assert m, "no json block"
    return m.group(1)


def assert_example_passes(example, tmp_path, ctx, capsys):
    from app import contract
    path = tmp_path / "example.json"
    path.write_text(example, encoding="utf-8")
    problems = contract.unpack_test_file(path, tmp_path / "out")
    assert problems == [], [f"{p.code}: {p.message}" for p in problems]
    # the same file through the skill's own checker, as an author with only Python would run it
    fetch(ctx, capsys, tmp_path / "zip")
    run = learnpkg(tmp_path / "zip" / NAME, "validate", str(path), cwd=tmp_path)
    assert run.returncode == 0, run.stdout + run.stderr


def test_prompt_example_passes_the_checker(ctx, capsys, tmp_path):
    root = pathlib.Path(__file__).resolve().parent.parent
    assert_example_passes(json_block((root / "web" / "static" / "test-prompt.txt").read_text("utf-8")), tmp_path, ctx, capsys)


def test_format_doc_example_passes_the_checker(ctx, capsys, tmp_path):
    root = pathlib.Path(__file__).resolve().parent.parent
    doc = (root / "docs" / "practice-test-format.md").read_text("utf-8")
    assert_example_passes(json_block(doc, "## Single-File Example"), tmp_path, ctx, capsys)
