# learn-ai

Self-hosted learning app for phone and desktop. A session has three steps: review a summary, listen to a podcast, do spaced-repetition flashcards (FSRS). Each person has an account, so progress is tracked per person. Lessons are not in this repo; `sample/` holds a demo.

Stack: FastAPI, SQLite (WAL), one uvicorn worker, plain JS. No build step.

## Run locally

```
python -m venv .venv && .venv/Scripts/pip install --require-hashes -r requirements.txt
.venv/Scripts/pip install pytest httpx
.venv/Scripts/python -m pytest -q tests/test_server.py
DATA_DIR=./data CONTENT_DIR=sample COOKIE_SECURE=0 .venv/Scripts/python -m app.cli add-user you@example.com
DATA_DIR=./data CONTENT_DIR=sample COOKIE_SECURE=0 .venv/Scripts/python -m uvicorn app.main:app --port 8000
```

`add-user` prints a temporary password that must be changed at first login.

## Lesson content

`scripts/package_content.py CONFIG.json OUT_DIR` turns lesson folders into what the server reads: it moves inline scripts to files so the strict CSP holds, swaps CDN links for `/static/vendor/`, copies audio and measures it with `ffprobe`, and writes `manifest.json`. A lesson needs `app/summary.md` and an approved `app/cards.json`; `--allow-draft` accepts `cards.draft.json` instead.

`tests/e2e_browser.py OUT_DIR` runs the whole app in real Chrome against that content and a stub AI (needs `playwright`).

## Deploy

Runs with Docker Compose behind a Cloudflare Tunnel; no host port is opened. Create `.env` (mode 600):

```
APP_UID=            # id -u of the deploy user
APP_GID=
PUBLIC_ORIGIN=https://your.host
ALLOWED_HOSTS=your.host
TUNNEL_TOKEN=
LINK_SECRET=        # random 32+ byte string for signed sandbox lesson URLs
AI_API_KEY=         # optional; the Ask box says it is off without it. Use a key with a spending cap.
```

Put packaged lessons in `./content`, lesson packages for the sandbox in `./packages`, make `./data` and `./backups` owned by that user, then:

```
docker compose up -d --build
docker compose exec app python -m app.cli add-user you@example.com
```

Other commands in `app/cli.py`: `reset-password`, `end-sessions`, `remove-user`, `list-users`. The database is backed up daily to `./backups`, keeping 14 copies.

Set `MTU` in `.env` if the host network is below 1500.

## Security

Passwords are hashed with Argon2id, sessions are random tokens stored as SHA-256 in `__Host-` cookies, login is rate limited by IP, account and pair, and the CSP allows only same-origin scripts. `cf-connecting-ip` is trusted only from the tunnel container. AI answers go through DOMPurify. Report problems through a private GitHub security advisory.

More in `docs/`: design, lesson format, operations and how credentials are handled. Third-party files: see `THIRD_PARTY.md`.
