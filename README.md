# learn-ai

Self-hosted learning app for phone and desktop. A session has up to four steps: review a summary, listen to a podcast (if the lesson has audio), do spaced-repetition flashcards (FSRS), read the full lesson page. A lesson counts as done once the steps are finished and its page has been opened. Each person has an account, so progress is tracked per person. Each account uploads its own lesson packages and shares them by email or link. Lessons are not in this repo; `sample/package` holds a demo.

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

`add-user` prints a temporary password that must be changed at first login. This needs Python 3.12 and a POSIX shell (Git Bash on Windows). `.venv/Scripts` is the Windows path; elsewhere use `.venv/bin`. The secret and `COOKIE_SECURE=0` here are for a local run only.

## Lesson packages

A package is a zip holding `package.json` and `lessons/<id>/`; the format is in `docs/lesson-format.md`. Check one with `scripts/learnpkg.py validate DIR [--profile full]`, zip it with `scripts/learnpkg.py pack DIR OUT.zip`, then upload it from the Library screen. The server runs the same check on every upload. `scripts/convert_legacy.py` turns an old lesson folder into a package. A zip can be up to 300 MB; uploads go in 2 MB parts, and an update sends only new or changed files.

An author can download a Claude skill from the upload dialog. The zip holds one `creating-learn-packages/` folder with the instructions, a lesson template and the checker, and needs only Python unless the lesson has audio. It can be uploaded to Claude app or web, or unpacked into `~/.claude/skills/` for Claude Code.

Practice tests can be included in a package or uploaded directly as a single `.json` file (`docs/practice-test-format.md`). Learners can take timed exams or practice with immediate feedback, review missed questions, and ask AI questions about revealed items.

## Tests

`python -m pytest -q` runs the server tests. The browser tests need `playwright` and run one at a time; most take `--browser chrome|webkit`:

- `tests/e2e_shell.py`: the app's screens and navigation
- `tests/e2e_practice.py`: practice tests
- `tests/e2e_platform.py`: upload, share, revoke, feedback
- `tests/e2e_admin.py`: the admin page and Ask approval, against a fake provider
- `tests/e2e_bridge.py`: the lesson page's bridge to the app while the page is busy
- `tests/e2e_lesson_phone.py`: the lesson page on a phone
- `tests/e2e_browser.py PACKAGE_DIR`, `tests/e2e_sandbox.py PACKAGE_DIR`: the study session and the sandbox, against an unpacked package

## Deploy

The app needs HTTPS in front of it, because session cookies are `Secure` and it sends HSTS, and lasting storage for `./data`, `./backups` and `./packages`. The included `compose.yml` runs it with Docker Compose behind a Cloudflare Tunnel, so no host port is opened. That is the only setup run in production so far; for anything else see [Other reverse proxies](#other-reverse-proxies).

Create `.env` (mode 600):

```
APP_UID=            # id -u of the deploy user
APP_GID=
PUBLIC_ORIGIN=https://your.host
ALLOWED_HOSTS=your.host
TUNNEL_TOKEN=       # from your Cloudflare Tunnel
LINK_SECRET=        # required, random 32+ byte string. Signs sandbox URLs and share links; changing it kills every share link.
KEY_ENCRYPTION_KEY= # base64url of 32 random bytes. Encrypts the AI key saved on the admin page; without it no key can be saved there.
AI_API_KEY=         # optional default until a key is saved on the admin page. Use a key with a spending cap.
```

Make `./data`, `./backups` and `./packages` owned by that user, then:

```
docker compose up -d --build
docker compose exec app python -m app.cli add-user you@example.com
```

Give yourself the admin page with `docker compose exec app python -m app.cli set-admin you@example.com on`; accounts can also be managed there. Other commands in `app/cli.py`: `set-quota`, `import-package`, `reset-password`, `end-sessions`, `remove-user`, `list-users`. The database is backed up daily to `./backups`, keeping 14 copies.

Set `MTU` in `.env` if the host network is below 1500.

### Other reverse proxies

Caddy, nginx, Traefik and the like should work, but this has not been run end to end. In `compose.yml`, remove the `tunnel` service, add `ports: ["127.0.0.1:8000:8000"]` to `app` if the proxy runs on the host, and set `TRUSTED_PROXY` to the proxy's container name or its address as the app sees it. `TUNNEL_TOKEN` is then not needed. The proxy must:

- Set `cf-connecting-ip` to the client's address, replacing any value the client sent. The login limit reads the address from this header, whose name comes from Cloudflare. Without it every visitor counts as the proxy, so one person's failed logins can block everyone for a while. If a client's own value gets through, it can dodge the limit.
- Accept request bodies of at least 2 MB, because uploads go in 2 MB parts. nginx allows 1 MB by default.

## Security

Passwords are hashed with Argon2id, sessions are random tokens stored as SHA-256 in `__Host-` cookies and end sooner for admins (4 hours idle, 24 hours at most, against 7 and 30 days), login is rate limited by IP, account and pair, and the CSP allows only same-origin scripts. Lesson pages are author code: they run in a sandboxed iframe with no origin and talk to the app only through a message bridge (`docs/design/02a-ket-qua-sandbox.md`). `cf-connecting-ip` is trusted only from the address in `TRUSTED_PROXY`. AI answers go through DOMPurify. Report problems through a private GitHub security advisory.

More in `docs/`: design, lesson and practice test formats, operations and how credentials are handled. 
## License

MIT, see `LICENSE`. It covers the code here; lessons and practice tests that people upload stay theirs. Third-party licenses are in `THIRD_PARTY.md`, including `mutagen`, which is GPL and is installed with the app.
