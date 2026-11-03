# learn-ai

Self-hosted learning app for phone and desktop. A session has three steps: review a summary, listen to a podcast, do spaced-repetition flashcards (FSRS). Each person has an account, so progress is tracked per person. Each account uploads its own lesson packages and shares them by email or link. Lessons are not in this repo; `sample/package` holds a demo.

Stack: FastAPI, SQLite (WAL), one uvicorn worker, plain JS. No build step.

## Run locally

```
python -m venv .venv && .venv/Scripts/pip install --require-hashes -r requirements.txt
.venv/Scripts/pip install pytest httpx
.venv/Scripts/python -m pytest -q tests/test_server.py
export DATA_DIR=./data PACKAGES_DIR=./packages LINK_SECRET=local-only-secret-local-only-secret COOKIE_SECURE=0
.venv/Scripts/python -m app.cli add-user you@example.com
.venv/Scripts/python scripts/learnpkg.py pack sample/package demo.zip
.venv/Scripts/python -m app.cli import-package demo.zip you@example.com
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

`add-user` prints a temporary password that must be changed at first login.

## Lesson packages

A package is a zip holding `package.json` and `lessons/<id>/`; the format is in `docs/lesson-format.md`. Check one with `scripts/learnpkg.py validate DIR [--profile full]`, zip it with `scripts/learnpkg.py pack DIR OUT.zip`, then upload it from the Library screen. The server runs the same check on every upload. `scripts/convert_legacy.py` turns an old lesson folder into a package.

An author can download a Claude skill from the upload dialog. The zip holds one `creating-learn-packages/` folder with the instructions, a lesson template and the checker, and needs only Python unless the lesson has audio. It can be uploaded to Claude app or web, or unpacked into `~/.claude/skills/` for Claude Code.

`tests/e2e_platform.py` runs upload, share, revoke and feedback in a real browser, `tests/e2e_admin.py` the admin page and Ask approval against a fake provider. `tests/e2e_browser.py PACKAGE_DIR` and `tests/e2e_sandbox.py PACKAGE_DIR` run the study session and the sandbox against an unpacked package (need `playwright`).

## Deploy

Runs with Docker Compose behind a Cloudflare Tunnel; no host port is opened. Create `.env` (mode 600):

```
APP_UID=            # id -u of the deploy user
APP_GID=
PUBLIC_ORIGIN=https://your.host
ALLOWED_HOSTS=your.host
TUNNEL_TOKEN=
LINK_SECRET=        # required, random 32+ byte string. Signs sandbox URLs and share links; changing it kills every share link.
KEY_ENCRYPTION_KEY= # base64url of 32 random bytes. Encrypts the AI key saved on the admin page.
AI_API_KEY=         # optional default until a key is saved on the admin page. Use a key with a spending cap.
```

Make `./data`, `./backups` and `./packages` owned by that user, then:

```
docker compose up -d --build
docker compose exec app python -m app.cli add-user you@example.com
```

Give yourself the admin page with `set-admin you@example.com on`. Other commands in `app/cli.py`: `set-quota`, `import-package`, `reset-password`, `end-sessions`, `remove-user`, `list-users`. The database is backed up daily to `./backups`, keeping 14 copies.

Set `MTU` in `.env` if the host network is below 1500.

## Security

Passwords are hashed with Argon2id, sessions are random tokens stored as SHA-256 in `__Host-` cookies, login is rate limited by IP, account and pair, and the CSP allows only same-origin scripts. Lesson pages are author code: they run in a sandboxed iframe with no origin and talk to the app only through a message bridge (`docs/design/02a-ket-qua-sandbox.md`). `cf-connecting-ip` is trusted only from the tunnel container. AI answers go through DOMPurify. Report problems through a private GitHub security advisory.

More in `docs/`: design, lesson format, operations and how credentials are handled. Third-party files: see `THIRD_PARTY.md`.
