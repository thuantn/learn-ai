"""Tests for the library, sharing and feedback."""
import os
import pathlib

from test_catalog import _make_package, _ready_client, ctx  # noqa: F401
from test_uploads import CARDS, package_zip, upload_and_commit, zip_of

QUIZ = [{"id": "q1", "q": "Câu một?", "options": ["a", "b"], "answer": 0}]
TRACKS = {"short": {"file": "s.mp3", "label": "Ngắn"}}


def setup_pkg(ctx, capsys):
    """an owns a package; binh and cuong are other accounts."""
    a = _ready_client(ctx, capsys, "an")
    b = _ready_client(ctx, capsys, "binh")
    z = _ready_client(ctx, capsys, "cuong")
    a.__enter__(), b.__enter__(), z.__enter__()
    pid = upload_and_commit(a, zip_of(_make_package(ctx.tmp / "p", cards=CARDS, quiz=QUIZ, tracks=TRACKS)))["package_id"]
    return a, b, z, pid, f"{pid}.demo"


def token_of(url):
    return url.split("#join=")[1]


def test_share_by_email_gives_access_and_listing(ctx, capsys):
    a, b, _, pid, key = setup_pkg(ctx, capsys)
    assert b.get(f"/lesson/{key}").status_code == 404
    assert a.post(f"/api/packages/{pid}/share", json={"email": "binh"}).status_code == 200
    assert b.get(f"/lesson/{key}").status_code == 200
    shared = b.get("/api/packages").json()["shared"]
    assert [x["id"] for x in shared] == [pid] and shared[0]["author"] == "an"
    assert a.get("/api/packages").json()["mine"][0]["people"] == 1
    assert a.get(f"/api/packages/{pid}/people").json()["people"][0]["email"] == "binh"


def test_share_unknown_email_reports_clearly(ctx, capsys):
    a, _, _, pid, _ = setup_pkg(ctx, capsys)
    r = a.post(f"/api/packages/{pid}/share", json={"email": "khong-co"})
    assert r.status_code == 404 and r.json()["code"] == "no_account"
    assert a.get(f"/api/packages/{pid}/people").json()["people"] == []
    assert a.post(f"/api/packages/{pid}/share", json={"email": "an"}).status_code == 400


def test_share_email_case_insensitive(ctx, capsys):
    a, _, _, pid, _ = setup_pkg(ctx, capsys)
    assert a.post(f"/api/packages/{pid}/share", json={"email": " BINH "}).status_code == 200
    assert a.get(f"/api/packages/{pid}/people").json()["people"][0]["email"] == "binh"


def test_only_owner_can_share_list_link_or_delete(ctx, capsys):
    a, b, z, pid, key = setup_pkg(ctx, capsys)
    a.post(f"/api/packages/{pid}/share", json={"email": "binh"})
    for other in (b, z):  # someone it is shared with, and a stranger
        assert other.post(f"/api/packages/{pid}/share", json={"email": "cuong"}).status_code == 404
        assert other.post(f"/api/packages/{pid}/unshare", json={"email": "binh"}).status_code == 404
        assert other.get(f"/api/packages/{pid}/people").status_code == 404
        assert other.get(f"/api/packages/{pid}/link").status_code == 404
        assert other.post(f"/api/packages/{pid}/link").status_code == 404
        assert other.delete(f"/api/packages/{pid}/link").status_code == 404
        assert other.delete(f"/api/packages/{pid}").status_code == 404
        assert other.get(f"/api/packages/{pid}/feedback").status_code == 404
    assert a.get(f"/lesson/{key}").status_code == 200


def test_revoke_cuts_access_immediately_keeps_progress(ctx, capsys):
    a, b, _, pid, key = setup_pkg(ctx, capsys)
    a.post(f"/api/packages/{pid}/share", json={"email": "binh"})
    b.post(f"/api/lessons/{key}/start")
    b.put(f"/api/doc/{key}", json={"note": "của binh"})
    frame = b.post(f"/api/lessons/{key}/frame", json={}).json()
    page = {"Sec-Fetch-Dest": "iframe"}
    assert b.get(frame["url"], headers=page).status_code == 200
    assert len(b.get("/api/cards/due").json()["cards"]) == 5

    assert a.post(f"/api/packages/{pid}/unshare", json={"email": "binh"}).status_code == 200

    assert b.get(frame["url"], headers=page).status_code == 403
    assert b.post(f"/api/lessons/{key}/frame", json={}).status_code == 404
    assert b.get(f"/api/doc/{key}").status_code == 404
    assert b.put(f"/api/doc/{key}", json={"note": "x"}).status_code == 404
    assert b.get(f"/audio/{key}/short").status_code == 404
    assert b.get("/api/cards/due").json()["cards"] == []
    assert b.get("/api/lessons").json()["lessons"] == []
    assert b.get("/api/packages").json()["shared"] == []

    assert a.post(f"/api/packages/{pid}/share", json={"email": "binh"}).status_code == 200
    assert b.get(f"/api/doc/{key}").json()["data"] == {"note": "của binh"}
    assert len(b.get("/api/cards/due").json()["cards"]) == 5


def test_link_join_adds_to_shared_list(ctx, capsys):
    a, b, _, pid, key = setup_pkg(ctx, capsys)
    assert a.get(f"/api/packages/{pid}/link").json()["url"] is None
    url = a.post(f"/api/packages/{pid}/link").json()["url"]
    assert url.startswith("/#join=") and a.get(f"/api/packages/{pid}/link").json()["url"] == url  # can be copied again
    r = b.post("/api/join", json={"token": token_of(url)})
    assert r.json() == {"package_id": pid, "first_lesson": key}
    assert [x["id"] for x in b.get("/api/packages").json()["shared"]] == [pid]
    assert a.get(f"/api/packages/{pid}/people").json()["people"][0]["via"] == "link"


def test_revoked_user_cannot_rejoin_by_link(ctx, capsys):
    a, b, _, pid, key = setup_pkg(ctx, capsys)
    token = token_of(a.post(f"/api/packages/{pid}/link").json()["url"])
    b.post("/api/join", json={"token": token})
    a.post(f"/api/packages/{pid}/unshare", json={"email": "binh"})
    r = b.post("/api/join", json={"token": token})
    assert r.status_code == 403 and r.json()["code"] == "revoked"
    assert b.get(f"/lesson/{key}").status_code == 404


def test_old_link_dies_after_new_link_or_off(ctx, capsys):
    a, b, z, pid, _ = setup_pkg(ctx, capsys)
    old = token_of(a.post(f"/api/packages/{pid}/link").json()["url"])
    new = token_of(a.post(f"/api/packages/{pid}/link").json()["url"])
    assert old != new
    assert b.post("/api/join", json={"token": old}).status_code == 404
    a.delete(f"/api/packages/{pid}/link")
    assert z.post("/api/join", json={"token": new}).status_code == 404
    assert b.post("/api/join", json={"token": new}).status_code == 404


def test_forged_token_and_rate_limit(ctx, capsys):
    a, b, _, pid, _ = setup_pkg(ctx, capsys)
    a.post(f"/api/packages/{pid}/link")
    codes = [b.post("/api/join", json={"token": f"{pid}.AAAA"}).status_code for _ in range(11)]
    assert codes[:10] == [404] * 10 and codes[10] == 429
    assert b.post("/api/join", json={}).status_code == 429


def test_join_refuses_other_package_signature(ctx, capsys):
    a, b, _, pid, _ = setup_pkg(ctx, capsys)
    other = upload_and_commit(a, package_zip(ctx, "p2", slug="other", cards=CARDS))["package_id"]
    sig = token_of(a.post(f"/api/packages/{pid}/link").json()["url"]).split(".")[1]
    a.post(f"/api/packages/{other}/link")
    assert b.post("/api/join", json={"token": f"{other}.{sig}"}).status_code == 404


def test_owner_joining_own_link_is_noop(ctx, capsys):
    a, _, _, pid, key = setup_pkg(ctx, capsys)
    token = token_of(a.post(f"/api/packages/{pid}/link").json()["url"])
    assert a.post("/api/join", json={"token": token}).json()["first_lesson"] == key
    assert a.get(f"/api/packages/{pid}/people").json()["people"] == []
    assert a.get("/api/packages").json()["shared"] == []


def test_delete_package_removes_files_and_access(ctx, capsys):
    a, b, _, pid, key = setup_pkg(ctx, capsys)
    a.post(f"/api/packages/{pid}/share", json={"email": "binh"})
    b.post(f"/api/lessons/{key}/start")
    url = b.post(f"/api/lessons/{key}/frame", json={}).json()["url"]
    assert a.delete(f"/api/packages/{pid}").status_code == 200
    assert not (pathlib.Path(os.environ["PACKAGES_DIR"]) / pid).exists()
    assert b.get(url, headers={"Sec-Fetch-Dest": "iframe"}).status_code == 403
    assert b.get("/api/cards/due").json()["cards"] == []
    with ctx.db.connect() as c:
        assert c.execute("SELECT count(*) n FROM card_state").fetchone()["n"] == 0


def test_remove_user_removes_their_packages(ctx, capsys):
    a, b, _, pid, key = setup_pkg(ctx, capsys)
    a.post(f"/api/packages/{pid}/share", json={"email": "binh"})
    b.post(f"/api/lessons/{key}/start")
    b.put(f"/api/doc/{key}", json={"x": 1})
    assert ctx.cli.main(["remove-user", "an"]) == 0
    assert not (pathlib.Path(os.environ["PACKAGES_DIR"]) / pid).exists()
    with ctx.db.connect() as c:
        for table in ("packages", "package_lessons", "package_access", "card_state", "lesson_progress", "user_doc"):
            assert c.execute(f"SELECT count(*) n FROM {table}").fetchone()["n"] == 0, table


def test_package_listing_never_leaks_between_users(ctx, capsys):
    a, b, _, pid, _ = setup_pkg(ctx, capsys)
    a.post(f"/api/packages/{pid}/link")
    data = b.get("/api/packages").json()
    assert data["mine"] == [] and data["shared"] == [] and data["used"] == 0
    assert data["quota"] == 1024 ** 3


def test_update_while_page_open_serves_new_files_same_doc(ctx, capsys):
    a, b, _, pid, key = setup_pkg(ctx, capsys)
    a.post(f"/api/packages/{pid}/share", json={"email": "binh"})
    b.put(f"/api/doc/{key}", json={"note": 1})
    url = b.post(f"/api/lessons/{key}/frame", json={}).json()["url"]
    root = _make_package(ctx.tmp / "p2", cards=CARDS, quiz=QUIZ, tracks=TRACKS)
    (root / "lessons" / "demo" / "page" / "index.html").write_text("<!doctype html><html lang='vi'><body>bản mới</body></html>", "utf-8")
    assert upload_and_commit(a, zip_of(root))["version"] == 2
    assert "bản mới" in b.get(url, headers={"Sec-Fetch-Dest": "iframe"}).text
    assert b.get(f"/api/doc/{key}").json()["data"] == {"note": 1}


def test_learner_sends_owner_reads_with_email(ctx, capsys):
    a, b, _, pid, key = setup_pkg(ctx, capsys)
    a.post(f"/api/packages/{pid}/share", json={"email": "binh"})
    url = f"/api/lessons/{key}/feedback"
    assert b.post(url, json={"kind": "comment", "target_type": "lesson", "text": "hay"}).status_code == 200
    assert b.post(url, json={"kind": "wrong", "target_type": "card", "target_id": "c1", "text": "sai"}).status_code == 200
    assert b.post(url, json={"kind": "wrong", "target_type": "quiz", "target_id": "q1", "text": "sai đáp án"}).status_code == 200
    rows = a.get(f"/api/packages/{pid}/feedback").json()["feedback"]
    assert [x["body"] for x in rows] == ["sai đáp án", "sai", "hay"]
    assert rows[0]["author"] == "binh" and rows[0]["target_text"] == "Câu một?" and rows[0]["lesson_title"] == "Demo"
    assert rows[1]["target_text"] == "q1" and rows[2]["target_text"] is None
    assert a.get("/api/packages").json()["mine"][0]["feedback"] == 3


def test_stranger_cannot_send_or_read_feedback(ctx, capsys):
    a, b, z, pid, key = setup_pkg(ctx, capsys)
    body = {"kind": "comment", "target_type": "lesson", "text": "x"}
    assert z.post(f"/api/lessons/{key}/feedback", json=body).status_code == 404
    assert z.get(f"/api/packages/{pid}/feedback").status_code == 404
    a.post(f"/api/packages/{pid}/share", json={"email": "binh"})
    assert b.get(f"/api/packages/{pid}/feedback").status_code == 404


def test_feedback_length_and_kind_validated(ctx, capsys):
    a, _, _, _, key = setup_pkg(ctx, capsys)
    url = f"/api/lessons/{key}/feedback"
    good = {"kind": "comment", "target_type": "lesson", "text": "x"}
    for bad in (
        {**good, "text": "   "},
        {**good, "text": "x" * 2001},
        {**good, "text": 5},
        {**good, "kind": "spam"},
        {**good, "target_type": "other"},
        {**good, "target_type": "card", "target_id": "khong-co"},
        {**good, "target_type": "card", "target_id": "q1"},  # a quiz id is not a card
        {**good, "target_type": "quiz", "target_id": "c1"},
    ):
        assert a.post(url, json=bad).status_code == 400, bad
    assert a.post(url, json={**good, "text": "x" * 2000}).status_code == 200


def test_feedback_rate_limit_counts_from_database(ctx, capsys):
    a, _, _, _, key = setup_pkg(ctx, capsys)
    url = f"/api/lessons/{key}/feedback"
    body = {"kind": "comment", "target_type": "lesson", "text": "x"}
    assert [a.post(url, json=body).status_code for _ in range(20)] == [200] * 20
    assert a.post(url, json=body).status_code == 429
    with ctx.db.connect() as c:
        c.execute("UPDATE feedback SET created_at=created_at-4000")
    assert a.post(url, json=body).status_code == 200


def test_html_feedback_stored_as_plain_text(ctx, capsys):
    a, _, _, pid, key = setup_pkg(ctx, capsys)
    text = "<img src=x onerror=alert(1)>"
    a.post(f"/api/lessons/{key}/feedback", json={"kind": "comment", "target_type": "lesson", "text": text})
    assert a.get(f"/api/packages/{pid}/feedback").json()["feedback"][0]["body"] == text


def test_author_removed_keeps_feedback(ctx, capsys):
    a, b, _, pid, key = setup_pkg(ctx, capsys)
    a.post(f"/api/packages/{pid}/share", json={"email": "binh"})
    b.post(f"/api/lessons/{key}/feedback", json={"kind": "comment", "target_type": "lesson", "text": "x"})
    ctx.cli.main(["remove-user", "binh"])
    rows = a.get(f"/api/packages/{pid}/feedback").json()["feedback"]
    assert rows[0]["body"] == "x" and rows[0]["author"] is None


def test_feedback_refuses_a_list_as_target_type(ctx, capsys):
    a, b, _, pkg, key = setup_pkg(ctx, capsys)
    a.post(f"/api/packages/{pkg}/share", json={"email": "binh"})
    r = b.post(f"/api/lessons/{key}/feedback", json={"kind": "comment", "target_type": ["lesson"], "text": "x"})
    assert r.status_code == 400


def test_library_lists_only_what_the_caller_can_see(ctx, capsys):
    a, b, _, pkg, key = setup_pkg(ctx, capsys)
    assert b.get("/api/packages").json()["shared"] == []
    a.post(f"/api/packages/{pkg}/share", json={"email": "binh"})
    shared = b.get("/api/packages").json()["shared"]
    assert [x["id"] for x in shared] == [pkg] and shared[0]["lessons"]
