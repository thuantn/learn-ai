"""Admin commands, run on the server:
  python -m app.cli add-user NAME        create an account, prints a temporary password once
  python -m app.cli reset-password NAME  new temporary password, ends all sessions
  python -m app.cli end-sessions NAME    ends all sessions
  python -m app.cli remove-user NAME     deletes the account and its data
  python -m app.cli list-users
"""
import secrets
import sys
import time

from . import auth, db


def temp_password():
    return secrets.token_urlsafe(18)


def main(argv):
    db.init()
    cmd = argv[0] if argv else ""
    name = argv[1].strip().lower() if len(argv) > 1 else ""
    with db.connect() as c:
        if cmd == "list-users":
            for r in c.execute("SELECT name, must_change FROM users ORDER BY name"):
                print(r["name"], "(chưa đổi mật khẩu tạm)" if r["must_change"] else "")
            return 0
        if not name or cmd not in ("add-user", "reset-password", "end-sessions", "remove-user"):
            print(__doc__)
            return 2
        exists = c.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone()
        if cmd == "add-user":
            if exists:
                print("Tài khoản đã có. Dùng reset-password.")
                return 1
            password = temp_password()
            c.execute("INSERT INTO users VALUES(?,?,1,?)", (name, auth.hash_password(password), time.time()))
            print(f"Mật khẩu tạm của {name}: {password}")
            return 0
        if not exists:
            print("Không có tài khoản này.")
            return 1
        if cmd == "reset-password":
            password = temp_password()
            c.execute("UPDATE users SET pw_hash=?, must_change=1 WHERE name=?", (auth.hash_password(password), name))
            c.execute("DELETE FROM sessions WHERE user=?", (name,))
            print(f"Mật khẩu tạm của {name}: {password}")
        elif cmd == "end-sessions":
            c.execute("DELETE FROM sessions WHERE user=?", (name,))
            print("Đã kết thúc mọi phiên.")
        else:
            c.execute("DELETE FROM users WHERE name=?", (name,))
            print("Đã xóa tài khoản và dữ liệu.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
