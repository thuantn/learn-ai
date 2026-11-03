"""SQLite: one connection per call, WAL so reads never wait for writes."""
import glob
import logging
import os
import sqlite3
import time

MIGRATIONS = [
    """
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
""",
    """
ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN quota_bytes INTEGER;
CREATE TABLE packages(
  id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  slug TEXT NOT NULL, title TEXT NOT NULL, topic TEXT NOT NULL, description TEXT NOT NULL,
  version INTEGER NOT NULL, size_bytes INTEGER NOT NULL, link_nonce TEXT,
  ask_status TEXT NOT NULL DEFAULT 'none', ask_hash TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
  UNIQUE(owner, slug));
CREATE TABLE package_lessons(
  key TEXT PRIMARY KEY, package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  ord INTEGER NOT NULL, data TEXT NOT NULL);
CREATE INDEX package_lessons_pkg ON package_lessons(package_id);
CREATE TABLE package_access(
  package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  via TEXT NOT NULL, granted_at REAL NOT NULL, revoked_at REAL, PRIMARY KEY(package_id, user));
CREATE INDEX package_access_user ON package_access(user);
CREATE TABLE feedback(
  id INTEGER PRIMARY KEY, package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  lesson TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL,
  author TEXT REFERENCES users(name) ON DELETE SET NULL, body TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX feedback_pkg ON feedback(package_id, created_at);
""",
    """
CREATE TABLE ai_settings(
  id INTEGER PRIMARY KEY CHECK(id=1), provider TEXT NOT NULL, model TEXT NOT NULL,
  key_blob BLOB NOT NULL, key_last4 TEXT NOT NULL, updated_by TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE admin_log(
  id INTEGER PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '', at REAL NOT NULL);
""",
    """
CREATE TABLE ask_message(
  id INTEGER PRIMARY KEY, user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE, lesson TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('user', 'assistant')), body TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX ask_message_thread ON ask_message(user, lesson, id);
""",
    """
CREATE TABLE test_revision(
  id INTEGER PRIMARY KEY, package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  test_key TEXT NOT NULL, content_hash TEXT NOT NULL, data TEXT NOT NULL, created_at REAL NOT NULL,
  UNIQUE(test_key, content_hash));
CREATE TABLE package_tests(
  key TEXT PRIMARY KEY, package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  ord INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, item_count INTEGER NOT NULL,
  time_limit_minutes INTEGER NOT NULL, pass_percent INTEGER NOT NULL,
  revision_id INTEGER NOT NULL REFERENCES test_revision(id) ON DELETE CASCADE);
CREATE INDEX package_tests_pkg ON package_tests(package_id);
CREATE TABLE test_attempt(
  id TEXT PRIMARY KEY, user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  test_key TEXT NOT NULL, revision_id INTEGER NOT NULL REFERENCES test_revision(id) ON DELETE CASCADE,
  mode TEXT NOT NULL CHECK(mode IN ('exam', 'practice', 'review')), layout TEXT NOT NULL,
  started_at REAL NOT NULL, paused_total REAL NOT NULL DEFAULT 0, pause_count INTEGER NOT NULL DEFAULT 0, paused_at REAL,
  submitted_at REAL, score INTEGER, total INTEGER);
CREATE UNIQUE INDEX test_attempt_open ON test_attempt(user, test_key, mode) WHERE submitted_at IS NULL;
CREATE INDEX test_attempt_user ON test_attempt(user, test_key, started_at);
CREATE TABLE test_answer(
  attempt TEXT NOT NULL REFERENCES test_attempt(id) ON DELETE CASCADE, item TEXT NOT NULL,
  chosen TEXT NOT NULL DEFAULT '[]', flagged INTEGER NOT NULL DEFAULT 0,
  answer_hash TEXT, correct INTEGER, graded_at REAL, PRIMARY KEY(attempt, item));
CREATE TABLE test_first_answer(
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  test_key TEXT NOT NULL, item TEXT NOT NULL, answer_hash TEXT NOT NULL, chosen TEXT NOT NULL, correct INTEGER NOT NULL, at REAL NOT NULL,
  PRIMARY KEY(user, test_key, item, answer_hash));
CREATE INDEX test_first_item ON test_first_answer(test_key, item, answer_hash);
CREATE TABLE test_pool(
  user TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  package_id TEXT NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
  test_key TEXT NOT NULL, item TEXT NOT NULL, answer_hash TEXT NOT NULL, streak INTEGER NOT NULL DEFAULT 0,
  last_correct_at REAL, added_at REAL NOT NULL, PRIMARY KEY(user, test_key, item));
""",
]

log = logging.getLogger("learn")


def path():
    return os.path.join(os.environ.get("DATA_DIR", "data"), "learn.db")


def connect():
    c = sqlite3.connect(path(), timeout=5)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _backup_premigrate(dest_dir, version):
    os.makedirs(dest_dir, exist_ok=True)
    target = os.path.join(dest_dir, time.strftime(f"premigrate-v{version}-%Y%m%d-%H%M%S.db", time.gmtime()))
    src = connect()
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return target


def admin_log(c, actor, action, target, detail=""):
    c.execute("INSERT INTO admin_log(actor, action, target, detail, at) VALUES(?,?,?,?,?)", (actor, action, target, detail, time.time()))


def init():
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        version = c.execute("PRAGMA user_version").fetchone()[0]
        if version >= len(MIGRATIONS):
            return
        has_users = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone() is not None
        backup_dir = os.environ.get("BACKUP_DIR")
        if has_users and backup_dir:
            _backup_premigrate(backup_dir, version)
        for i in range(version, len(MIGRATIONS)):
            sql = MIGRATIONS[i]
            try:
                c.executescript(f"BEGIN; {sql}; PRAGMA user_version={i + 1}; COMMIT;")
            except Exception:
                log.exception("migration %d failed", i + 1)
                c.execute("ROLLBACK")
                raise


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
