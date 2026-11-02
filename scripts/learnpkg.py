"""CLI for lesson package validation and packing.

  python scripts/learnpkg.py validate DIR [--profile full]
  python scripts/learnpkg.py pack DIR OUT.zip [--profile full]
"""
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.bundle import pack, safe_extract
from app.contract import check_package, errors


def _print_problems(problems):
    for p in problems:
        print(f"{p.severity}: {p.path}: {p.message}")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    val = sub.add_parser("validate", help="Kiểm tra một package.")
    val.add_argument("dir", help="Thư mục package")
    val.add_argument("--profile", default="basic", help="basic hoặc full")

    pkg = sub.add_parser("pack", help="Đóng gói thành zip.")
    pkg.add_argument("dir", help="Thư mục package")
    pkg.add_argument("out", help="Đường dẫn file zip đầu ra, nằm ngoài thư mục package")
    pkg.add_argument("--profile", default="basic", help="basic hoặc full")

    args = ap.parse_args(argv)
    if args.cmd == "validate":
        problems = check_package(pathlib.Path(args.dir), args.profile)
        _print_problems(problems)
        if errors(problems):
            return 1
        print("Package hợp lệ.")
        return 0

    if args.cmd == "pack":
        problems = check_package(pathlib.Path(args.dir), args.profile)
        _print_problems(problems)
        if errors(problems):
            return 1
        try:
            pack(pathlib.Path(args.dir), pathlib.Path(args.out))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Đã đóng gói: {args.out}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
