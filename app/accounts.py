"""Account creation, temporary passwords and removal for admins and CLI."""
import re
import secrets
import shutil
import time

from . import auth, catalog, db

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._%+-]{0,63}@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")


def temp_password() -> str:
    return secrets.token_urlsafe(18)


def create(c, name: str) -> str:
    if c.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
        raise ValueError("exists")
    password = temp_password()
    c.execute(
        "INSERT INTO users(name, pw_hash, must_change, created_at) VALUES(?,?,1,?)",
        (name, auth.hash_password(password), time.time()),
    )
    return password


def reset(c, name: str) -> str:
    if not c.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
        raise ValueError("missing")
    password = temp_password()
    c.execute("UPDATE users SET pw_hash=?, must_change=1 WHERE name=?", (auth.hash_password(password), name))
    c.execute("DELETE FROM sessions WHERE user=?", (name,))
    return password


def remove(name: str) -> None:
    with db.connect() as c:
        if not c.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
            raise ValueError("missing")
        owned = [r["id"] for r in c.execute("SELECT id FROM packages WHERE owner=?", (name,))]
        for package_id in owned:
            catalog.purge_rows(c, package_id)
        c.execute("DELETE FROM users WHERE name=?", (name,))
    for package_id in owned:
        shutil.rmtree(catalog.packages_dir() / package_id, ignore_errors=True)
