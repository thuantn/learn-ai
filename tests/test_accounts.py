"""Tests for admin account management and self-service password change."""
import base64
import pytest
from test_catalog import _add_user, _client, _login, _make_package, _ready_client, ctx, GOOD
from test_uploads import upload_and_commit, zip_of

MASTER = base64.urlsafe_b64encode(b"m" * 32).decode()


@pytest.fixture
def accounts_world(ctx, capsys, monkeypatch):
    monkeypatch.setenv("KEY_ENCRYPTION_KEY", MASTER)
    clients = {n: _ready_client(ctx, capsys, n) for n in ("boss@example.com", "cuong@example.com")}
    for c in clients.values():
        c.__enter__()
    assert ctx.cli.main(["set-admin", "boss@example.com", "on"]) == 0
    yield ctx, clients, capsys
    for c in clients.values():
        c.__exit__(None, None, None)


def test_non_admin_gets_404_on_all_new_routes(accounts_world):
    ctx, clients, capsys = accounts_world
    cuong = clients["cuong@example.com"]
    target = "test@example.com"
    routes = [
        ("POST", "/api/admin/users", {"name": target}),
        ("POST", f"/api/admin/users/{target}/reset-password", {}),
        ("POST", f"/api/admin/users/{target}/end-sessions", {}),
        ("PUT", f"/api/admin/users/{target}", {"admin": True}),
        ("DELETE", f"/api/admin/users/{target}", {"confirm": target}),
    ]
    unknown = cuong.get("/no-such-route")
    for method, path, body in routes:
        real = cuong.request(method, path, json=body)
        assert real.status_code == 404, f"{method} {path} status {real.status_code}"
        assert real.content == unknown.content, f"{method} {path} content mismatch"


def test_create_user_flow(accounts_world):
    ctx, clients, capsys = accounts_world
    boss = clients["boss@example.com"]

    # Valid creation with mixed case and whitespace
    r = boss.post("/api/admin/users", json={"name": "  NewUser@Example.COM  "})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "newuser@example.com"
    temp_pw = data["password"]
    assert len(temp_pw) >= 18
    assert "no-store" in r.headers.get("Cache-Control", "")

    # New user can log in and is forced to change password
    c = _client(ctx)
    lr = _login(c, "newuser@example.com", temp_pw)
    assert lr.status_code == 200
    assert lr.json()["must_change"] is True
    # API requires password change first
    assert c.get("/api/me").status_code == 403

    # Duplicate create returns 409 exists
    dup = boss.post("/api/admin/users", json={"name": "newuser@example.com"})
    assert dup.status_code == 409
    assert dup.json()["code"] == "exists"

    # Bad names return 400 name_bad
    for bad_name in ("notanemail", "@b.com", "user@", "user@domain", "a" * 250 + "@b.com", ""):
        bad_r = boss.post("/api/admin/users", json={"name": bad_name})
        assert bad_r.status_code == 400
        assert bad_r.json()["code"] == "name_bad"


def test_reset_password_flow(accounts_world):
    ctx, clients, capsys = accounts_world
    boss = clients["boss@example.com"]

    # Create and ready user
    add_r = boss.post("/api/admin/users", json={"name": "worker@example.com"})
    assert add_r.status_code == 200
    first_temp = add_r.json()["password"]

    user_c = _client(ctx)
    assert _login(user_c, "worker@example.com", first_temp).status_code == 200
    assert user_c.post("/api/change-password", json={"password": GOOD}).status_code == 200
    assert user_c.get("/api/me").status_code == 200

    # Reset password
    reset_r = boss.post("/api/admin/users/worker@example.com/reset-password")
    assert reset_r.status_code == 200
    new_temp = reset_r.json()["password"]
    assert new_temp != first_temp
    assert "no-store" in reset_r.headers.get("Cache-Control", "")

    # Old password fails
    c2 = _client(ctx)
    assert _login(c2, "worker@example.com", GOOD).status_code == 401

    # New temporary password works and must_change is 1
    lr = _login(c2, "worker@example.com", new_temp)
    assert lr.status_code == 200
    assert lr.json()["must_change"] is True

    # User's existing session cookie stops working
    assert user_c.get("/api/me").status_code == 401

    # Overview shows must_change is True
    ov = boss.get("/api/admin/overview").json()
    u_info = next(u for u in ov["users"] if u["name"] == "worker@example.com")
    assert u_info["must_change"] is True

    # Reset of missing user -> 404
    assert boss.post("/api/admin/users/ghost@example.com/reset-password").status_code == 404

    # Reset of self -> 409 code self
    self_r = boss.post("/api/admin/users/boss@example.com/reset-password")
    assert self_r.status_code == 409
    assert self_r.json()["code"] == "self"


def test_end_sessions(accounts_world):
    ctx, clients, capsys = accounts_world
    boss = clients["boss@example.com"]

    add_r = boss.post("/api/admin/users", json={"name": "sessionuser@example.com"})
    temp = add_r.json()["password"]
    c = _client(ctx)
    assert _login(c, "sessionuser@example.com", temp).status_code == 200

    # Missing user -> 404
    assert boss.post("/api/admin/users/missing@example.com/end-sessions").status_code == 404

    # End sessions
    end_r = boss.post("/api/admin/users/sessionuser@example.com/end-sessions")
    assert end_r.status_code == 200
    assert end_r.json() == {"ok": True}

    # Session killed
    assert c.get("/api/me").status_code == 401


def test_put_admin_and_quota_bounds(accounts_world):
    ctx, clients, capsys = accounts_world
    boss = clients["boss@example.com"]

    assert boss.post("/api/admin/users", json={"name": "target@example.com"}).status_code == 200

    # Toggle admin on
    r = boss.put("/api/admin/users/target@example.com", json={"admin": True})
    assert r.status_code == 200
    ov = boss.get("/api/admin/overview").json()
    assert next(u for u in ov["users"] if u["name"] == "target@example.com")["admin"] is True

    # Toggle admin off
    r = boss.put("/api/admin/users/target@example.com", json={"admin": False})
    assert r.status_code == 200
    ov = boss.get("/api/admin/overview").json()
    assert next(u for u in ov["users"] if u["name"] == "target@example.com")["admin"] is False

    # Set quota
    r = boss.put("/api/admin/users/target@example.com", json={"quota_gb": 10})
    assert r.status_code == 200
    ov = boss.get("/api/admin/overview").json()
    assert next(u for u in ov["users"] if u["name"] == "target@example.com")["quota"] == 10 * 1024 ** 3

    # Bounds rejected: 0, 101, True, "5"
    for b in (0, 101, True, "5"):
        bad_r = boss.put("/api/admin/users/target@example.com", json={"quota_gb": b})
        assert bad_r.status_code == 400 and bad_r.json()["code"] == "input", f"quota_gb {b}"

    # Missing fields or invalid types
    assert boss.put("/api/admin/users/target@example.com", json={}).status_code == 400
    assert boss.put("/api/admin/users/target@example.com", json={"admin": "yes"}).status_code == 400

    # Non-existent user -> 404
    assert boss.put("/api/admin/users/missing@example.com", json={"admin": True}).status_code == 404

    # Removing own admin -> 409 code self
    self_r = boss.put("/api/admin/users/boss@example.com", json={"admin": False})
    assert self_r.status_code == 409
    assert self_r.json()["code"] == "self"


def test_delete_user_flow(accounts_world):
    ctx, clients, capsys = accounts_world
    boss = clients["boss@example.com"]

    # User with package
    user = "pkgowner@example.com"
    pw = boss.post("/api/admin/users", json={"name": user}).json()["password"]
    c = _client(ctx)
    assert _login(c, user, pw).status_code == 200
    assert c.post("/api/change-password", json={"password": GOOD}).status_code == 200

    pid = upload_and_commit(c, zip_of(_make_package(ctx.tmp / "pkg_del", content="# Test\n")))["package_id"]
    folder = ctx.catalog.packages_dir() / pid
    assert folder.exists()

    # DELETE without exact confirm -> 400
    assert boss.request("DELETE", f"/api/admin/users/{user}", json={"confirm": "wrong"}).status_code == 400
    assert boss.request("DELETE", f"/api/admin/users/{user}", json={}).status_code == 400

    # DELETE of self -> 409 code self
    self_r = boss.request("DELETE", "/api/admin/users/boss@example.com", json={"confirm": "boss@example.com"})
    assert self_r.status_code == 409 and self_r.json()["code"] == "self"

    # DELETE of missing user -> 404
    assert boss.request("DELETE", "/api/admin/users/nobody@example.com", json={"confirm": "nobody@example.com"}).status_code == 404

    # Valid delete
    del_r = boss.request("DELETE", f"/api/admin/users/{user}", json={"confirm": user})
    assert del_r.status_code == 200
    assert not folder.exists()

    with ctx.db.connect() as db_c:
        assert db_c.execute("SELECT 1 FROM users WHERE name=?", (user,)).fetchone() is None
        assert db_c.execute("SELECT 1 FROM packages WHERE id=?", (pid,)).fetchone() is None


def test_admin_log_rows_contain_no_passwords(accounts_world):
    ctx, clients, capsys = accounts_world
    boss = clients["boss@example.com"]

    user = "audit@example.com"
    pw1 = boss.post("/api/admin/users", json={"name": user}).json()["password"]
    pw2 = boss.post(f"/api/admin/users/{user}/reset-password").json()["password"]
    boss.put(f"/api/admin/users/{user}", json={"admin": True, "quota_gb": 7})
    boss.post(f"/api/admin/users/{user}/end-sessions")
    boss.request("DELETE", f"/api/admin/users/{user}", json={"confirm": user})

    with ctx.db.connect() as c:
        rows = [dict(r) for r in c.execute("SELECT action, detail FROM admin_log").fetchall()]

    actions = {r["action"] for r in rows}
    for act in ("user_add", "user_reset", "set_admin", "set_quota", "user_end_sessions", "user_remove"):
        assert act in actions, f"Missing log for {act}"

    for r in rows:
        assert pw1 not in r["detail"]
        assert pw2 not in r["detail"]


def test_voluntary_password_change_flow(accounts_world):
    ctx, clients, capsys = accounts_world
    c = clients["cuong@example.com"]

    # Missing current -> 400 code current
    r = c.post("/api/change-password", json={"password": "new-strong-password-12345"})
    assert r.status_code == 400 and r.json()["code"] == "current"

    # Wrong current -> 400 code current
    r = c.post("/api/change-password", json={"current": "wrong-password", "password": "new-strong-password-12345"})
    assert r.status_code == 400 and r.json()["code"] == "current"

    # Wrong current with a weak new password still says only that the current one is wrong
    r = c.post("/api/change-password", json={"current": "wrong-password", "password": "short"})
    assert r.status_code == 400 and r.json()["code"] == "current"

    # Repeated wrong tries -> 429
    for _ in range(2):
        c.post("/api/change-password", json={"current": "wrong", "password": "new-strong-password-12345"})
    blocked_r = c.post("/api/change-password", json={"current": "wrong", "password": "new-strong-password-12345"})
    assert blocked_r.status_code == 429 and blocked_r.json()["code"] == "wait"

    # Clear rate limit
    ctx.main.limiter.succeeded("testclient", "cuong@example.com")

    # Right current + weak new -> 400 weak
    weak_r = c.post("/api/change-password", json={"current": GOOD, "password": "short"})
    assert weak_r.status_code == 400 and weak_r.json()["code"] == "weak"

    # Right current + same as current -> 400 weak
    same_r = c.post("/api/change-password", json={"current": GOOD, "password": GOOD})
    assert same_r.status_code == 400 and same_r.json()["code"] == "weak"
    assert "Mật khẩu mới phải khác mật khẩu hiện tại." in same_r.json()["error"]

    # Success
    NEW_GOOD = "mat-khau-moi-rat-manh-va-dai-hon-15-ky-tu"
    old_cookie = c.cookies.get(ctx.main.auth.cookie_name())
    succ_r = c.post("/api/change-password", json={"current": GOOD, "password": NEW_GOOD})
    assert succ_r.status_code == 200

    # New cookie works
    assert c.get("/api/me").status_code == 200

    # Old session cookie dead
    old_client = _client(ctx)
    old_client.cookies.set(ctx.main.auth.cookie_name(), old_cookie)
    assert old_client.get("/api/me").status_code == 401

    # Login with new password works
    c_new = _client(ctx)
    assert _login(c_new, "cuong@example.com", NEW_GOOD).status_code == 200

    # must_change user still changes without current
    temp = _add_user(ctx.cli, capsys, "forced@example.com")
    c_forced = _client(ctx)
    assert _login(c_forced, "forced@example.com", temp).status_code == 200
    assert c_forced.post("/api/change-password", json={"password": NEW_GOOD}).status_code == 200
