# Lesson format

Contract v1 is the only format the server accepts. `app/contract.py` does the checking. For multiple-choice practice tests, see the [practice test format](practice-test-format.md).

## A package

```
package.json
lessons/<lesson-id>/
  lesson.json
  page/index.html      the lesson page, with its other files in page/
  content.md           the lesson's full text for the AI to read; needed to request the Ask box
  audio/*.mp3          optional
```

- `package.json`: `contract_version`, `slug`, `title`, `topic`, `description`, and `lessons`, the list of `lesson-id` values in order.
- `lesson.json`:
  - `title`: at most 200 characters.
  - `summary`: 3 to 8 points, plain text.
  - `cards`: 5 to 30 cards, each with `id`, `q`, `a`.
  - `quiz`: may be empty. Each question has `id`, `q`, `options`, `answer` (the position of the correct option, counting from 0), `why`.
  - `tracks`: may be empty. At most `short` and `long`, each with `file` (in `audio/`) and `label`.
- Keep ids the same across versions, because progress is tied to them. Editing a card's content does not change its id. If an id disappears, the author must confirm this when uploading.
- Use bare ids in a package. The server adds a `p<12 hex>.` prefix to ids in the progress tables.
- The app shows "Bài N:" (lesson N) before each title, so do not put a number in `title`.
- A lesson with no `tracks` skips the listening step of the session.
- A lesson counts as done once the learner has finished the steps and opened the lesson page.

## Validating and packing

```
python scripts/learnpkg.py validate DIR [--profile full]
python scripts/learnpkg.py pack DIR OUT.zip [--profile full]
```

Upload the zip on the Library screen (Thư viện). The server runs this same check again, then shows the author the changes before accepting them.

## Limits

A zip can be up to 300 MB, and up to 600 MB and 2,000 files when unpacked, with a compression ratio of at most 100 times. A package holds at most 50 lessons. `page/index.html` can be up to 5 MB and `content.md` up to 1 MB. Each account has a quota of 1 GB, counted on unpacked size. Feedback can be up to 2,000 characters.

## The lesson page

The page is untrusted code and runs in a sandboxed iframe with no origin. It has no cookies, `localStorage`, network or forms. Inline scripts and `on*` attributes do not run, so every script goes in its own file in `page/`. The only libraries available are those the app provides under `/static/` (`lesson-bridge.js`, `lesson-fonts.css`, `vendor/`); nothing loads from outside.

The page talks to the app through `window.LearnBridge`, which is available once `/static/lesson-bridge.js` is loaded:

| Call | Result |
|---|---|
| `call("doc.get")` | The data saved for this person in this lesson, or `null` |
| `call("doc.set", {data})` | Saves one object |
| `call("quiz.answer", {id, option})` | `{correct}`. The server grades against `lesson.json`; a wrong answer becomes a review card |
| `askApp(text)` | Opens the app's Ask box with the question filled in; the learner presses send |
| `call("learner.id")` | The learner's own code within the package, not their email |
| `call("link.open", {url})` | The app asks the learner before opening; accepts only `https` |

The `id` passed to `quiz.answer` is the question's `id` in `lesson.json`. The correct answer lives only in `lesson.json` and the page does not need to know it; the `why` explanation may be in the page. The skill's lesson template already uses these calls.

Outgoing `<a href>` links go through `link.open` automatically. Links within the page (`#section`) only scroll to that section. They do not change `location.hash` or trigger `:target`, because WebKit reloads a sandboxed page on that kind of link.

On screens under 1024 px, the app's bar and the page's `nav.top` hide when scrolling down and come back when scrolling up, so a page's menu should go in `nav.top` to get this.

Quick-check questions that need no record can be graded in the page. Learners who read the source will see the answers, so do not do this for the end-of-lesson quiz.

Formulas use `/static/vendor/tex-svg.min.js` (MathJax). Put `window.MathJax = { tex: { inlineMath: [["\\(", "\\)"]], displayMath: [["\\[", "\\]"]] }, svg: { fontCache: "global" }, options: { enableMenu: false } };` in a `.js` file in `page/`, and load that file before `<script src="/static/vendor/tex-svg.min.js" async></script>`. Do not use `/static/mathjax-config.js`: it is meant for the app's own pages and turns off drawing formulas on page load.

The page must set its own background and text colours for both themes. Without them, the text is black on the app's dark background and nearly unreadable. `color-scheme: light dark` is not enough, because it follows the operating system and not the app's theme button.

Write theme colours with `@media (prefers-color-scheme: dark)` as usual. In the lesson frame this query follows the app's theme button and not the operating system: the server rewrites it when serving `.css`, `.html` and `.js` files of up to 2 MB. Larger files still follow the operating system.

## Full content outline

The labels below are in Vietnamese because the lessons so far are. `--profile full` requires the exact strings `Khởi động` and `Đi sâu` in the page, whatever language the lesson is in.

1. **Warm-up ("Khởi động"):** 3 questions to guess at first. On a return visit this becomes a review, putting missed questions first and including questions from the previous lesson.
2. **4 to 5 parts,** each with:
   - An explanation that is as long as it needs to be.
   - A tool that really calculates, with no hand-set numbers, and a "Dự đoán trước khi chạy" (predict before running) step.
   - A 2-question quick check.
   - An "Áp dụng vào dự án" (apply it to your project) box.
   - A collapsible "Đi sâu" (go deeper) section with formulas and links to the original papers.
   - "Hỏi về phần này" (ask about this part) and "Tự giải thích lại" (explain it back yourself) buttons.
3. **End-of-lesson quiz:** 8 questions, including some the learner must calculate.
4. **Review podcast:** scripts for a short and a long version, with audio the author creates.
