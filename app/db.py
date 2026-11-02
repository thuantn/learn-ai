"""SQLite: one connection per call, WAL so reads never wait for writes."""
import glob
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  name TEXT PRIMARY KEY, pw_hash TEXT NOT NULL, must_change INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  created_at REAL NOT NULL, last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS card_state(
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE, card_id TEXT NOT NULL, lesson TEXT NOT NULL,
  due REAL NOT NULL, card_json TEXT NOT NULL, PRIMARY KEY(user, card_id));
CREATE INDEX IF NOT EXISTS card_due ON card_state(user, due);
CREATE TABLE IF NOT EXISTS review_log(
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE, card_id TEXT NOT NULL, rating INTEGER NOT NULL, reviewed_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS listen_pos(
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE, episode TEXT NOT NULL, seconds REAL NOT NULL, updated_at REAL NOT NULL,
  PRIMARY KEY(user, episode));
CREATE TABLE IF NOT EXISTS wrong_card(
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE, card_id TEXT NOT NULL, lesson TEXT NOT NULL,
  question TEXT NOT NULL, answer TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(user, card_id));
CREATE TABLE IF NOT EXISTS lesson_progress(
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE, lesson TEXT NOT NULL, status TEXT NOT NULL, track TEXT NOT NULL, updated_at REAL NOT NULL,
  PRIMARY KEY(user, lesson));
CREATE TABLE IF NOT EXISTS user_doc(
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE, name TEXT NOT NULL, body TEXT NOT NULL, updated_at REAL NOT NULL,
  PRIMARY KEY(user, name));
CREATE TABLE IF NOT EXISTS ask_usage(
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE, day TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY(user, day));
"""


def path():
    return os.path.join(os.environ.get("DATA_DIR", "data"), "learn.db")


def connect():
    c = sqlite3.connect(path(), timeout=5)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init():
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)


def backup(dest_dir, keep=14):
    """Copies the live database safely, then keeps only the newest files."""
    os.makedirs(dest_dir, exist_ok=True)
    target = os.path.join(dest_dir, time.strftime("learn-%Y%m%d-%H%M%S.db", time.gmtime()))
    src = connect()
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    for old in sorted(glob.glob(os.path.join(dest_dir, "learn-*.db")))[:-keep]:
        os.remove(old)
    return target
