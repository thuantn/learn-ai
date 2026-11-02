"""Tests for the author toolkit download."""
import io
import pathlib
import subprocess
import sys
import zipfile

from test_catalog import _ready_client, ctx  # noqa: F401


def test_toolkit_holds_exactly_the_listed_files_and_validates_the_template(ctx, capsys, tmp_path):
    c = _ready_client(ctx, capsys)
    with c:
        r = c.get("/api/toolkit.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        z.extractall(tmp_path / "kit")
    assert sorted(names) == sorted(ctx.main.TOOLKIT_FILES)
    for name in names:
        assert not any(part.startswith(".") or part == "__pycache__" or part.endswith(".pyc") for part in pathlib.PurePosixPath(name).parts), name
    assert {"app/contract.py", "scripts/learnpkg.py", "docs/lesson-format.md", "skills/creating-learn-packages/SKILL.md"} <= set(names)
    out = subprocess.run(
        [sys.executable, "scripts/learnpkg.py", "validate", "skills/creating-learn-packages/template"],
        cwd=tmp_path / "kit", capture_output=True, encoding="utf-8",
    )
    assert out.returncode == 0, out.stdout + out.stderr
    packed = subprocess.run(
        [sys.executable, "scripts/learnpkg.py", "pack", "skills/creating-learn-packages/template", "out.zip"],
        cwd=tmp_path / "kit", capture_output=True, encoding="utf-8",
    )
    assert packed.returncode == 0 and (tmp_path / "kit" / "out.zip").is_file(), packed.stdout + packed.stderr


def test_every_skill_file_is_in_the_list(ctx):
    root = pathlib.Path(ctx.main.__file__).resolve().parent.parent
    on_disk = {p.relative_to(root).as_posix() for p in (root / "skills").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert on_disk <= set(ctx.main.TOOLKIT_FILES), "a new skill file must be added to TOOLKIT_FILES"


def test_toolkit_needs_login(ctx):
    from test_catalog import _client
    with _client(ctx) as c:
        assert c.get("/api/toolkit.zip").status_code == 401
