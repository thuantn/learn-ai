"""Pack and safely unpack lesson packages."""
import pathlib
import shutil
import stat
import zipfile

from .contract import Problem, check_package, errors

MAX_ZIP = 90 * 1024 * 1024
MAX_UNPACKED = 400 * 1024 * 1024
MAX_FILES = 2000
MAX_RATIO = 100


def pack(root, out):
    """Packs a valid package into a zip file. Raises ValueError if invalid or too large."""
    problems = check_package(root)
    if errors(problems):
        raise ValueError("Package không hợp lệ.")
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(pathlib.Path(root).rglob("*")):
            if path.is_file() and not path.is_symlink():
                arcname = path.relative_to(root).as_posix()
                zf.write(path, arcname)
    size = out.stat().st_size
    if size > MAX_ZIP:
        out.unlink()
        raise ValueError(f"Zip quá lớn: {size} > {MAX_ZIP} byte.")


def safe_extract(zip_path, dest):
    """Extracts a zip only if all paths are safe. Returns Problems; on error dest is unchanged."""
    zip_path = pathlib.Path(zip_path)
    dest = pathlib.Path(dest)
    tmp_dir = dest.with_name(dest.name + ".tmp")

    def cleanup():
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    try:
        try:
            zip_size = zip_path.stat().st_size
        except OSError as exc:
            return [Problem(str(zip_path), "zip_bad", f"Không đọc được file zip: {exc}")]

        if zip_size > MAX_ZIP:
            return [Problem(str(zip_path), "zip_size", f"Zip quá lớn: {zip_size} > {MAX_ZIP} byte.")]

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                infos = zf.infolist()
                if len(infos) > MAX_FILES:
                    return [Problem(str(zip_path), "zip_size", f"Quá nhiều file: {len(infos)} > {MAX_FILES}.")]

                problems = []
                seen = set()
                for info in infos:
                    name = info.filename
                    if "\\" in name:
                        problems.append(Problem(name, "zip_path", f"Tên file chứa dấu gạch chéo ngược: {name}."))
                        continue
                    norm = name.replace("\\", "/")
                    if norm.startswith("/"):
                        problems.append(Problem(name, "zip_path", f"Đường dẫn tuyệt đối không được phép: {name}."))
                        continue
                    is_dir = norm.endswith("/")
                    parts = [p for p in norm.split("/") if p != "."]
                    if any(p == ".." for p in parts) or (not is_dir and "" in parts):
                        problems.append(Problem(name, "zip_path", f"Đường dẫn chứa .. hoặc rỗng: {name}."))
                        continue
                    if any(":" in p for p in parts):
                        problems.append(Problem(name, "zip_path", f"Tên ổ đĩa không được phép: {name}."))
                        continue
                    if norm in seen:
                        problems.append(Problem(name, "zip_duplicate", f"Tên file trùng: {name}."))
                        continue
                    seen.add(norm)
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        problems.append(Problem(name, "zip_symlink", f"File symlink không được phép: {name}."))

                if problems:
                    return problems

                cleanup()
                tmp_dir.mkdir(parents=True)

                total = 0
                for info in infos:
                    norm = info.filename.replace("\\", "/")
                    if norm.endswith("/"):
                        target = tmp_dir / norm.rstrip("/")
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target = tmp_dir / norm
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        while True:
                            chunk = src.read(64 * 1024)
                            if not chunk:
                                break
                            total += len(chunk)
                            dst.write(chunk)
                            if total > MAX_UNPACKED:
                                problems.append(Problem(info.filename, "zip_size", f"Tổng dung lượng giải nén quá lớn: {total} > {MAX_UNPACKED} byte."))
                                break
                    if problems:
                        break
                    if not info.filename.lower().endswith(".mp3"):
                        uncompressed = target.stat().st_size
                        compressed = info.compress_size or 1
                        if uncompressed / compressed > MAX_RATIO:
                            problems.append(Problem(info.filename, "zip_size", f"Tỉ lệ nén quá cao: {uncompressed}/{compressed}."))
                            break

                if problems:
                    cleanup()
                    return problems

                if dest.exists():
                    shutil.rmtree(dest)
                tmp_dir.rename(dest)
                return []
        except zipfile.BadZipFile as exc:
            return [Problem(str(zip_path), "zip_bad", f"Không phải file zip hợp lệ: {exc}")]

    except Exception as exc:
        cleanup()
        return [Problem(str(zip_path), "zip_bad", f"Lỗi khi giải nén: {exc}")]
