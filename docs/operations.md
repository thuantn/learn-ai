# Operations

The app runs with Docker Compose on one VM and reaches the Internet through a Cloudflare Tunnel, with no port open on the host. The domain name and VM address are kept out of the repo. This is how the production copy runs; for another proxy see `README.md`.

## Credentials

No credential is in the repo, the image or the logs.

| Item | Where it lives | How it travels |
|---|---|---|
| User password | Known only to that person; the server stores an Argon2id hash | HTTPS to the app |
| Temporary password | Shown once by the `add-user` command or the `/admin` page | The administrator hands it to the user. The app sends no email; the "Soạn email mời" (compose invitation) button on `/admin` only opens the administrator's mail program |
| Tunnel token | `.env` with mode 600 on the VM | SFTP over SSH from the admin machine |
| AI key | Entered by an admin on `/admin`, stored encrypted with AES-GCM in the database. `AI_API_KEY` in `.env` is used only until one is entered | The server calls the AI provider. It never reaches the browser and cannot be read back; the screen shows only the last 4 characters |
| Master key (`KEY_ENCRYPTION_KEY`) | `.env` on the VM, not in backups | Encrypts the AI key. If it is lost or changed, the saved key can no longer be read and the Ask box goes off unless `AI_API_KEY` is set. The app keeps running and an admin enters the AI key again |
| Lesson link key (`LINK_SECRET`) | `.env` on the VM | Signs the lesson pages' `/s/<token>/...` URLs and share links; never reaches the browser. Required: the app does not start without it. Changing it kills every old share link |
| Deploy user's SSH key | Admin machine, outside the repo and outside any cloud-synced folder | Never leaves the machine |
| VM admin password | Admin machine | Used only for SSH and for `sudo`'s stdin when creating the user |

Rules:
- Keep these files outside synced folders such as OneDrive.
- Do not send credentials to a reviewing model. Review prompts hold only document content.
- Delete files holding temporary passwords once the user has changed the password.
- On Windows, `chmod` in Git Bash has no real effect. A file's permissions depend on the ACL of the home folder.

## First deploy

1. Create the tunnel and DNS record on a machine with a Cloudflare certificate, then get the token:
   ```
   cloudflared tunnel create learn-ai
   cloudflared tunnel route dns learn-ai <domain>
   cloudflared tunnel token learn-ai
   ```
2. On the VM, create a dedicated user in the `docker` group, lock its password and allow login only with an SSH key.
3. Copy the code from `git archive HEAD`. Create `data/`, `backups/` and `packages/` owned by that user.
4. Create `.env` with mode 600 as described in `README.md`. A random `LINK_SECRET` of 32 or more characters is required. `KEY_ENCRYPTION_KEY` is the base64url of 32 random bytes.
5. Run:
   ```
   docker compose up -d --build
   docker compose exec app python -m app.cli add-user <email>
   ```
6. Check from the Internet, not just that the container is healthy. See [Checks after a deploy](#checks-after-a-deploy).

## Updates

- **Code:** copy the new version, then `docker compose up -d --build`.
- **Lessons:** authors upload their own zip on the Library screen (Thư viện), with no deploy needed. An administrator can run `import-package <zip> <owner email>`.

Packages live in `packages/<id>/<version>/`; their details and permissions are in the database. The temporary folder `packages/.staging` is cleaned at startup.

Before each upgrade with a migration, the app copies the database to `backups/premigrate-v<n>-<time>.db`. If the copy fails it stops and does not migrate. Backups hold only the database, not `packages/`; if that folder is lost, authors must upload their zips again.

## Converting old-style lessons

`scripts/convert_legacy.py CONFIG.json OUT_DIR [--allow-draft]` turns an old-style lesson folder into a package. The config file stays outside the repo:

```json
{
  "source": "path to the folder holding the lessons",
  "replace": [["old string", "new string"]],
  "package": {"slug": "...", "title": "...", "topic": "...", "description": "..."},
  "lessons": [{
    "id": "bai03", "order": 3, "title": "Lesson title",
    "folder": "Bai03-Ten", "page": "bai03_ten.html", "doc": "lesson3", "audio_dir": "podcast",
    "tracks": {"long": {"file": "b.mp3", "label": "Long version"}}
  }]
}
```

`replace` is for removing names from a page before publishing it.

## Accounts

```
python -m app.cli add-user <email>        create an account, print a temporary password
python -m app.cli reset-password <email>  issue a new temporary password, delete all sessions
python -m app.cli end-sessions <email>    delete all sessions
python -m app.cli remove-user <email>     delete the account, its data and its packages
python -m app.cli import-package <zip> <email>  install a package for its owner
python -m app.cli set-admin <email> on|off  grant or remove admin rights
python -m app.cli set-quota <email> <GB>    change the quota, from 1 to 100
python -m app.cli list-users
```

Run these in the container with `docker compose exec app`. Except for `import-package`, all of this can also be done on the `/admin` page. Users change their own password in the app, which requires the current password.

## Administration and the Ask box

Only admin accounts can open `/admin`. Anyone else gets a 404, as if the route did not exist. The page has accounts, Ask approval, the AI provider and key, abuse reports, package removal, storage and a log.

Turning on the Ask box takes two things:
1. Enter a key on `/admin` and press Thử kết nối (test connection). Use a separate key with a spending cap, not one shared with another app. If it reports that the model cannot run under ZDR (zero data retention), change the model; do not turn ZDR off.
2. The author presses "Xin bật ô Hỏi" (request the Ask box) in the Library, and an admin reads the content and approves it. If a new version changes what the AI reads, the package goes back on the waiting list and its Ask box stops until it is approved again.

Each person has one conversation per lesson, shared between the app's page and the lesson page. It is stored in the `ask_message` table, so it is in the backups. The AI receives at most the last 6 exchanges, within a limit of 16,000 characters. Each lesson keeps at most 200 rows per person. Authors have no way to see conversations through the app, but anyone with access to the database can read them. A conversation is lost when the learner presses Xóa (delete) or removes the lesson from their library, and when the package or the account is deleted. If access is revoked the conversation stays, and it reappears if the lesson is shared again.

There is no Internet option yet; it depends on being able to check ZDR with a real key.

Admin sessions are shorter: they end after 4 hours unused and 24 hours at most, against 7 and 30 days for everyone else. If a session ends during a timed test, the clock keeps running until the person logs in again.

A prompt injection test with a real model was run on 05/11/2026 (`deepseek/deepseek-v4.1-flash`, 72 answers, on the production copy). Instructions hidden in a lesson made the AI add a harmless string to its answer in 6 of 36 tries, using two ways of hiding: a note in a quiz explanation and an instruction deep in a long lesson. Combining those same two ways with a phishing link, an image or a script got through in 0 of 24 tries. The browser ran no scripts and loaded nothing from the planted addresses. The AI did not reveal other lessons, keys or server details. The rule was then also repeated after the data block (`ai.DATA_REMINDER`). A rerun on the production copy gave 0 of 12 for the two ways of hiding and 0 of 8 for the phishing link, and normal answers were still correct. This holds only for that model and those questions and is not a guarantee: test again after changing the model, and the approver must still read all the content before turning on the Ask box.

## Checks after a deploy

- The home page redirects to login, and the response has CSP, HSTS and `nosniff`.
- Someone not logged in cannot get `/api/*` or lesson pages.
- The cookie is `__Host-session`, `Secure`, `HttpOnly`, `SameSite=Strict`.
- Audio returns `206` and can be seeked.
- A regular account opening `/admin` gets a 404.
- Download the skill from the upload dialog, unpack it, and run `creating-learn-packages/scripts/learnpkg.py validate` on `template/`.
- A lesson page shows formulas and reports that it saved to the account.
- `docker port` shows nothing for the app. Other apps on the VM are still healthy. Measure with `docker stats`.
- Two test accounts on the production copy: upload, share, study, revoke, feedback. After deleting the accounts, check that the package folder is gone.
- `tests/e2e_browser.py PACKAGE_DIR` run locally with a real lesson.

## Problems seen so far

- **Tunnel does not come up, and the log says `failed to dial to edge with quic`:** the network blocks QUIC. Compose already sets `--protocol http2`.
- **Build network errors or connections hanging in the container:** the VM has a low MTU. Set `MTU=1280` in `.env`; the build uses `network: host`.
- **Uploads through the tunnel are very slow:** measured at 0.07 MB/s once, while SFTP to the same VM was much faster. The VM's network is suspected of throttling the tunnel's connection, but nobody has confirmed this. The app uploads in 2 MB parts and sends only new files, so it stays usable. For a large package, copy it to the VM and run `import-package`.
- **Console reports CSP blocking `cloudflareinsights`:** Cloudflare injects an analytics script on its own. It is harmless; turn off Web Analytics on the zone to stop it.

## Backup and restore

The app backs up the database at startup and every 24 hours into `backups/`, keeping 14 copies. To restore: stop the app, copy a backup to `data/learn.db`, delete `learn.db-wal` and `learn.db-shm` if present, then start it again. Backups do not include `packages/`: at startup the app deletes only versions older than the one the database records, and it keeps unknown folders and logs them. A package updated after the backup was taken will not open until its author uploads it again.

## If you suspect a leak

1. Revoke the AI key at the provider.
2. Delete the old tunnel or change its token, and deploy `.env` again.
3. Run `end-sessions` and `reset-password` for the people involved.
4. Replace the deploy user's SSH key.
5. Record the cause in `LESSONS_LEARNED.md`, without any secret values.
