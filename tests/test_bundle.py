"""Tests for safe lesson package packing and extraction."""
import json
import pathlib
import shutil
import sys
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_contract import good_package

from app.bundle import MAX_FILES, MAX_RATIO, pack, safe_extract
from app.contract import check_package


def test_round_trip(good_package, tmp_path):
    """Pack a valid package and unpack it safely; the result passes the checker."""
    zip_path = tmp_path / "out.zip"
    pack(good_package, zip_path)
    dest = tmp_path / "unpacked"
    assert safe_extract(zip_path, dest) == []
    assert check_package(dest) == []


@pytest.mark.parametrize("name", ["../x.html", "/etc/x", "C:/x", "a\\b.html", "lessons/../../x"])
def test_bad_names(tmp_path, name, monkeypatch):
    """Dangerous paths inside a zip are rejected and nothing is written to dest."""
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        info = zipfile.ZipInfo(name.replace("\\", "/"))
        zf.writestr(info, "x")
    if "\\" in name:
        # Python's zipfile normalizes backslashes, so pretend the archive kept the backslash.
        original = zipfile.ZipFile.infolist
        def patched(self):
            infos = original(self)
            for info in infos:
                if info.filename == name.replace("\\", "/"):
                    info.filename = name
            return infos
        monkeypatch.setattr(zipfile.ZipFile, "infolist", patched)
    dest = tmp_path / "dest"
    problems = safe_extract(zip_path, dest)
    assert any(p.code == "zip_path" for p in problems)
    assert not dest.exists() or not any(dest.iterdir())


def test_duplicate_names(tmp_path):
    """Two entries with the same name are rejected."""
    zip_path = tmp_path / "dup.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.txt", "x")
        zf.writestr("a.txt", "y")
    dest = tmp_path / "dest"
    problems = safe_extract(zip_path, dest)
    assert any(p.code == "zip_duplicate" for p in problems)
    assert not dest.exists() or not any(dest.iterdir())


def test_symlink_entry(tmp_path):
    """Zip entries that look like symlinks are rejected."""
    zip_path = tmp_path / "sym.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120777 << 16) | info.external_attr
        zf.writestr(info, "target")
    dest = tmp_path / "dest"
    problems = safe_extract(zip_path, dest)
    assert any(p.code == "zip_symlink" for p in problems)
    assert not dest.exists() or not any(dest.iterdir())


def test_bomb_ratio(tmp_path):
    """A zip bomb with extreme compression ratio is rejected."""
    zip_path = tmp_path / "bomb.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zeros.bin", bytes(200 * 1024 * 1024))
    dest = tmp_path / "dest"
    problems = safe_extract(zip_path, dest)
    assert any(p.code == "zip_size" for p in problems)
    assert not dest.exists() or not any(dest.iterdir())


def test_too_many_files(tmp_path):
    """More than MAX_FILES entries are rejected."""
    zip_path = tmp_path / "many.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i in range(MAX_FILES + 1):
            zf.writestr(f"{i}.txt", "x")
    dest = tmp_path / "dest"
    problems = safe_extract(zip_path, dest)
    assert any(p.code == "zip_size" for p in problems)
    assert not dest.exists() or not any(dest.iterdir())


def test_not_a_zip(tmp_path):
    """A non-zip file is rejected cleanly."""
    zip_path = tmp_path / "not.zip"
    zip_path.write_text("not a zip", encoding="utf-8")
    dest = tmp_path / "dest"
    problems = safe_extract(zip_path, dest)
    assert any(p.code == "zip_bad" for p in problems)
    assert not dest.exists() or not any(dest.iterdir())


def test_pack_refuses_invalid_package(good_package, tmp_path):
    """Packing a package that fails validation raises an error."""
    package = json.loads((good_package / "package.json").read_text(encoding="utf-8"))
    package["contract_version"] = "v2"
    (good_package / "package.json").write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(ValueError):
        pack(good_package, tmp_path / "out.zip")


def test_pack_uses_forward_slashes(good_package, tmp_path):
    """Packed archive names always use forward slashes, even on Windows."""
    zip_path = tmp_path / "out.zip"
    pack(good_package, zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            assert "\\" not in name


def test_directory_entries_are_accepted(good_package, tmp_path):
    """Directory entries ending with '/' are accepted and only create folders."""
    root = good_package
    zip_path = tmp_path / "dirs.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("package.json", (root / "package.json").read_text(encoding="utf-8"))
        zf.writestr("lessons/", "")
        zf.writestr("lessons/demo/", "")
        zf.writestr("lessons/demo/lesson.json", (root / "lessons" / "demo" / "lesson.json").read_text(encoding="utf-8"))
        zf.writestr("lessons/demo/page/", "")
        zf.writestr("lessons/demo/page/index.html", (root / "lessons" / "demo" / "page" / "index.html").read_text(encoding="utf-8"))
    dest = tmp_path / "unpacked"
    assert safe_extract(zip_path, dest) == []
    assert check_package(dest) == []


def test_oversized_zip_refused_before_reading(tmp_path, monkeypatch):
    """MAX_ZIP is checked before the zip is opened."""
    from app import bundle
    monkeypatch.setattr(bundle, "MAX_ZIP", 10)
    zip_path = tmp_path / "big.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("x.txt", "this is more than ten bytes")
    dest = tmp_path / "dest"
    problems = safe_extract(zip_path, dest)
    assert any(p.code == "zip_size" for p in problems)
    assert not dest.exists() or not any(dest.iterdir())


def test_pack_refuses_too_large(good_package, tmp_path, monkeypatch):
    """pack raises ValueError mentioning the limit and leaves no partial file."""
    from app import bundle
    monkeypatch.setattr(bundle, "MAX_ZIP", 10)
    zip_path = tmp_path / "out.zip"
    with pytest.raises(ValueError, match="10"):
        pack(good_package, zip_path)
    assert not zip_path.exists()


def test_failed_extract_keeps_existing_dest(good_package, tmp_path, monkeypatch):
    """A bad new zip must not overwrite a good existing dest or leave .tmp behind."""
    from app import bundle
    zip_path = tmp_path / "good.zip"
    pack(good_package, zip_path)
    dest = tmp_path / "dest"
    assert safe_extract(zip_path, dest) == []
    assert check_package(dest) == []
    good_contents = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*"))

    monkeypatch.setattr(bundle, "MAX_UNPACKED", 5)
    bad_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.txt", "1234567890")
    problems = safe_extract(bad_zip, dest)
    assert any(p.code == "zip_size" for p in problems)
    assert not (tmp_path / "dest.tmp").exists()
    assert sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*")) == good_contents


def test_cli_exit_codes(good_package, tmp_path):
    """learnpkg.py validate returns correct exit codes and prints messages."""
    import os
    import subprocess
    script = ROOT / "scripts" / "learnpkg.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    result = subprocess.run(
        [sys.executable, str(script), "validate", str(good_package)],
        capture_output=True, text=True, cwd=ROOT, env=env,
    )
    assert result.returncode == 0
    assert "Package hợp lệ." in result.stdout

    bad_pkg = tmp_path / "bad"
    shutil.copytree(good_package, bad_pkg)
    package = json.loads((bad_pkg / "package.json").read_text(encoding="utf-8"))
    package["contract_version"] = "v2"
    (bad_pkg / "package.json").write_text(json.dumps(package), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), "validate", str(bad_pkg)],
        capture_output=True, text=True, cwd=ROOT, env=env,
    )
    assert result.returncode == 1
    assert "Phiên bản contract không được hỗ trợ" in result.stdout

    warn_pkg = tmp_path / "warn"
    shutil.copytree(good_package, warn_pkg)
    html = (warn_pkg / "lessons" / "demo" / "page" / "index.html").read_text(encoding="utf-8")
    html = html.replace("<p>Hello</p>", '<p onclick="x">Hello</p>')
    (warn_pkg / "lessons" / "demo" / "page" / "index.html").write_text(html, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), "validate", str(warn_pkg)],
        capture_output=True, text=True, cwd=ROOT, env=env,
    )
    assert result.returncode == 0
    assert "warning" in result.stdout
