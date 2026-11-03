"""Fixtures that build practice test packages with handwritten questions only."""
import json
import pathlib

# Unique strings that make_item hides in explanation, why and best_practice, for leak checks.
SENTINELS = ("MÃ-KHÔNG-LỜI-GIẢI", "MÃ-KHÔNG-LỰA-CHỌN", "MÃ-KHÔNG-MỐT")


def make_item(id="q1", type="single", correct=("A",), domain="Chung", options=("A", "B", "C", "D"), **extra):
    """A valid question; every text field always holds a valid value."""
    item = {
        "id": id,
        "type": type,
        "domain": domain,
        "question": f"Câu hỏi {id}?",
        "options": [{"id": oid, "text": f"Chữ {oid}", "why": f"{oid} {SENTINELS[1]}"} for oid in options],
        "correct": list(correct),
        "explanation": f"{SENTINELS[0]} lời giải cho câu {id}.",
        "best_practice": SENTINELS[2],
    }
    item.update(extra)
    return item


def make_test(n=3, title="Đề", **extra):
    test = {"title": title, "items": [make_item(f"q{i}") for i in range(1, n + 1)]}
    test.update(extra)
    return test


def write_package(root, tests, slug="de", lessons=()):
    """Writes a package folder with package.json and tests/<id>.json, no lesson folders."""
    root = pathlib.Path(root)
    root.mkdir(parents=True, exist_ok=True)
    package = {
        "contract_version": "v1",
        "slug": slug,
        "title": "Bộ đề",
        "topic": "luyện tập",
        "description": "Đề luyện tập.",
        "lessons": list(lessons),
        "tests": list(tests),
    }
    (root / "package.json").write_text(json.dumps(package), encoding="utf-8")
    tests_dir = root / "tests"
    tests_dir.mkdir(exist_ok=True)
    for key, test in tests.items():
        (tests_dir / f"{key}.json").write_text(json.dumps(test), encoding="utf-8")
    return root


def one_file(tests, slug="de"):
    """The single .json upload format: one package that only holds tests."""
    return {
        "slug": slug,
        "title": "Bộ đề",
        "topic": "luyện tập",
        "description": "Đề luyện tập.",
        "tests": [{**test, "id": key} for key, test in tests.items()],
    }
