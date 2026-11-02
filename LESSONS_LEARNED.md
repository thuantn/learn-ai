# Lessons learned

## Rules for this repo

- Keep it clean enough to be public: no lesson content, audio, `data/`, `.env`, real hostnames or personal details. Those live outside the repo. Design docs belong in `docs/`, written without those details.
- Run `tests/e2e_browser.py` and look at the screenshots after any UI change. A passing check over a blank page has happened.

## Traps found

- 02/11/2026 — Playwright `wait_for_function` with a string is refused by the app's CSP. `page.evaluate` works, so the e2e script polls with that.
- 02/11/2026 — Markdown strips the backslashes of `\(` and `\)`, so formulas must be set aside before `marked.parse`. Test the Ask box with an answer that contains a formula.
- 02/11/2026 — DOMPurify logs a CSP violation in the console when it strips an `on*` attribute. The handler does not run; it is only noise.
- 02/11/2026 — Outbound QUIC can be blocked, and a healthy app container says nothing about the tunnel. Check the public URL after every deploy. See `docs/operations.md`.
- 03/11/2026 — A CSP block is a console error, not a page error. `pageerror` listeners miss it, so the e2e scripts listen to the console too.
- 03/11/2026 — Playwright delivers console events at the next sync call, so they can arrive after the page has gone. Filter by the source URL, not by timing.
- 03/11/2026 — `doc.set` replies before the write. A save that arrived during a write over 2 seconds used to wait for the next save; `tests/e2e_platform.py` holds a PUT open to pin this.
- 03/11/2026 — Commit only inside `if pytest ...`. A pipe into `tail` hides the exit code.

