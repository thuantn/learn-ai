"""Tests for the practice test format checker."""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import app.contract as contract
import learnpkg

from practice_fixtures import make_item, make_test, write_package, one_file


def codes(root): return {p.code for p in contract.check_package(root) if p.severity == "error"}
def warns(root): return {p.code for p in contract.check_package(root) if p.severity == "warning"}


def test_test_only_package_is_valid(tmp_path):
    assert codes(write_package(tmp_path / "p", {"t1": make_test()})) == set()


def test_package_needs_a_lesson_or_a_test(tmp_path):
    assert "package_empty" in codes(write_package(tmp_path / "p", {}))


@pytest.mark.parametrize("change,code", [
    (dict(type="single", correct=["A", "B"]), "test_correct"),
    (dict(type="multi", correct=["A"]), "test_correct"),
    (dict(correct=["Z"]), "test_correct"),
    (dict(id="Bad Id"), "bad_id"),
    (dict(question=""), "empty_text"),
    (dict(question="x" * 4001), "text_too_long"),
    (dict(explanation=""), "empty_text"),
    (dict(docs=["http://a.vn"]), "bad_link"),
    (dict(docs=["javascript:alert(1)"]), "bad_link"),
    (dict(docs=[" https://a.vn"]), "bad_link"),
    (dict(docs=["https://a.vn/" + str(i) for i in range(6)]), "test_docs"),
    (dict(question="xem [đây](javascript:alert(1))"), "bad_link"),
    (dict(explanation="![x](http://a.vn/a.png)"), "bad_link"),
    (dict(question="có​chữ vô hình"), "invisible_text"),
    (dict(options=[{"id": "A", "text": "x"}]), "test_options"),
    (dict(options=[{"id": "A", "text": "x"}, {"id": "A", "text": "y"}]), "test_options"),
    (dict(options=["x", "y"]), "test_options"),
    (dict(options=[{"id": "A", "text": 1}, {"id": "B", "text": "y"}]), "test_options"),
    (dict(options=[{"id": "A", "text": "x", "why": "y" * 1001}, {"id": "B", "text": "y"}]), "text_too_long"),
    (dict(correct="A"), "test_correct"),
    (dict(correct=[["A"]]), "test_correct"),
    (dict(type="essay"), "test_type"),
    (dict(domain=5), "bad_type"),
    (dict(domain="x" * 101), "text_too_long"),
    (dict(best_practice="x" * 1001), "text_too_long"),
    (dict(docs="https://a.vn"), "test_docs"),
    (dict(shuffle="no"), "bad_type"),
])
def test_bad_items(tmp_path, change, code):
    assert code in codes(write_package(tmp_path / "p", {"t1": make_test(items=[{**make_item(), **change}])}))


@pytest.mark.parametrize("change,code", [
    (dict(time_limit_minutes="105"), "test_time"),
    (dict(time_limit_minutes=True), "test_time"),
    (dict(time_limit_minutes=601), "test_time"),
    (dict(pass_percent="78"), "test_pass"),
    (dict(pass_percent=0), "test_pass"),
    (dict(pass_percent=101), "test_pass"),
    (dict(lang="fr"), "test_lang"),
    (dict(title=""), "empty_text"),
    (dict(items="x"), "test_items"),
    (dict(items=[1]), "test_items"),
])
def test_bad_tests(tmp_path, change, code):
    assert code in codes(write_package(tmp_path / "p", {"t1": {**make_test(), **change}}))


def test_duplicate_item_and_test_ids(tmp_path):
    t = make_test(items=[make_item("q1"), make_item("q1")])
    assert "duplicate_id" in codes(write_package(tmp_path / "p", {"t1": t}))
    # Hai bộ đề được dùng chung id câu.
    assert codes(write_package(tmp_path / "q", {"t1": make_test(), "t2": make_test()})) == set()


def test_test_id_must_differ_from_lesson_id(tmp_path):
    assert "duplicate_id" in codes(write_package(tmp_path / "p", {"bai": make_test()}, lessons=["bai"]))


def test_limits(tmp_path):
    assert "test_count" in codes(write_package(tmp_path / "a", {f"t{i}": make_test(1) for i in range(21)}))
    assert "test_items" in codes(write_package(tmp_path / "b", {"t1": make_test(201)}))
    assert "test_size" in codes(write_package(tmp_path / "c", {"t1": make_test(1, description="x" * (5 * 1024 * 1024))}))


def test_letter_reference_warns_unless_kept_in_order(tmp_path):
    mention = make_item(question="Cả A và B đều đúng?")
    assert "test_letters" in warns(write_package(tmp_path / "a", {"t1": make_test(items=[mention])}))
    assert "test_letters" not in warns(write_package(tmp_path / "b", {"t1": make_test(items=[{**mention, "shuffle": False}])}))
    above = make_item(explanation="Tất cả đáp án trên đều đúng.")
    assert "test_letters" in warns(write_package(tmp_path / "c", {"t1": make_test(items=[above])}))


def test_many_domains_warn(tmp_path):
    items = [make_item(f"q{i}", domain=f"L{i}") for i in range(13)]
    assert "test_domains" in warns(write_package(tmp_path / "p", {"t1": make_test(items=items)}))


def test_one_file_unpacks_to_a_package(tmp_path):
    src = tmp_path / "de.json"
    src.write_text(json.dumps(one_file({"t1": make_test()})), encoding="utf-8-sig")
    assert contract.unpack_test_file(src, tmp_path / "out") == []
    assert (tmp_path / "out/tests/t1.json").is_file()
    package = json.loads((tmp_path / "out/package.json").read_text("utf-8"))
    assert package["tests"] == ["t1"] and package["lessons"] == [] and package["contract_version"] == "v1"
    assert codes(tmp_path / "out") == set()


@pytest.mark.parametrize("body", ["[]", "{", '{"slug":"de","title":"x","tests":[{"id":"../x"}]}', '{"slug":"de","title":"x","tests":"x"}'])
def test_one_file_bad_input_writes_nothing_outside(tmp_path, body):
    src = tmp_path / "de.json"
    src.write_text(body, encoding="utf-8")
    assert contract.unpack_test_file(src, tmp_path / "out")
    assert not (tmp_path / "x.json").exists()


def test_one_file_with_duplicate_test_ids_is_refused(tmp_path):
    body = one_file({"t1": make_test()})
    body["tests"] = body["tests"] * 2
    src = tmp_path / "de.json"
    src.write_text(json.dumps(body), encoding="utf-8")
    assert "duplicate_id" in {p.code for p in contract.unpack_test_file(src, tmp_path / "out")}


def test_a_test_file_over_one_megabyte_is_fine(tmp_path):
    items = [make_item(f"q{i}", question="x" * 3900, explanation="x" * 3900) for i in range(190)]
    root = write_package(tmp_path / "p", {"t1": make_test(items=items)})
    assert (root / "tests/t1.json").stat().st_size > 1024 * 1024
    assert codes(root) == set()


def test_learnpkg_validates_a_json_file(tmp_path, capsys):
    src = tmp_path / "de.json"
    src.write_text(json.dumps(one_file({"t1": make_test()})), encoding="utf-8")
    assert learnpkg.main(["validate", str(src)]) == 0
