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
- 03/11/2026 — A thinking model counts its thinking against `max_tokens`. On OpenRouter a real question spent 5000 tokens and returned no text, and `effort: low` did not help; `reasoning: {enabled: false}` did. A test call with a tiny budget proves nothing either way, so measure a real question too.
- 03/11/2026 — WebKit reloads a sandboxed page on a `#` link; Chrome does not. The bridge now scrolls by itself. Test samples need the link types real lessons use, or the WebKit run passes without exercising them.
- 03/11/2026 — `wait_for_function` with a string is refused by the app's CSP. Poll from Python instead.

- 03/11/2026 — In WebKit runs, `/api/lessons due to access control checks` is a home-screen request cut off by the test leaving the page. It happens on main too. `e2e_platform` and `e2e_sandbox` count it as a page error, so read the message before treating that failure as new.
