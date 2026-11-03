# Practice Test Format

Contract v1 defines the format for practice tests and question banks in learn-ai. Tests can be packaged in a zip archive or uploaded directly as a single `.json` file. The server validates every upload using `app/contract.py`.

## Upload Options

### 1. Single `.json` File (Recommended for Test-Only Content)

A single `.json` file containing the package metadata and a `tests` list. This can be uploaded directly in the Library without creating a zip.

### 2. Full Package Folder (in Zip)

For packages combining lessons and practice tests:

```text
package.json
tests/<test-id>.json
lessons/<lesson-id>/...
```

In `package.json`, list test IDs under `"tests"`:

```json
{
  "contract_version": "v1",
  "slug": "artisan-bread-baking",
  "title": "Artisan Bread Baking",
  "topic": "Culinary Arts",
  "description": "Practice tests on sourdough and artisan bread.",
  "lessons": [],
  "tests": ["fermentation-fundamentals"]
}
```

A package can have only lessons, only tests, or both. It cannot be empty.

## Single-File Example

Here is a complete, valid single-file upload:

```json
{
  "slug": "artisan-bread-baking",
  "title": "Artisan Bread Baking Practice Exam",
  "topic": "Culinary Arts",
  "description": "Practice questions on fermentation, dough hydration, and baking techniques.",
  "tests": [
    {
      "id": "fermentation-fundamentals",
      "title": "Fermentation Fundamentals",
      "description": "Essential concepts regarding sourdough starters, hydration ratios, and proofing.",
      "lang": "en",
      "time_limit_minutes": 45,
      "pass_percent": 80,
      "items": [
        {
          "id": "dough-hydration",
          "type": "single",
          "domain": "Hydration",
          "question": "What is the primary effect of increasing dough hydration from 65% to 78% in artisan bread?",
          "options": [
            {
              "id": "A",
              "text": "It produces a denser crumb with smaller and tighter air pockets.",
              "why": "Higher hydration yields an open, airy crumb rather than a dense crumb."
            },
            {
              "id": "B",
              "text": "It creates an open crumb structure and requires gentler handling during shaping.",
              "why": "Additional water relaxes the gluten mesh and produces larger gas pockets, making the dough softer and more delicate."
            },
            {
              "id": "C",
              "text": "It accelerates crust browning while keeping the internal baking time identical.",
              "why": "Crust browning depends primarily on oven steam, residual sugars, and temperature."
            },
            {
              "id": "D",
              "text": "It completely eliminates the need for any bulk fermentation period.",
              "why": "Fermentation remains essential regardless of hydration."
            }
          ],
          "correct": [
            "B"
          ],
          "explanation": "Higher hydration loosens the gluten network and traps steam during baking, yielding a more open and irregular crumb. Wetter dough is softer and requires gentle handling.",
          "best_practice": "Use wet hands or a bench scraper when handling high-hydration dough to avoid sticking.",
          "docs": [
            "https://example.com/baking/dough-hydration"
          ]
        },
        {
          "id": "proofing-indicators",
          "type": "multi",
          "domain": "Proofing",
          "question": "Which indicators show that a shaped sourdough loaf has finished its final proof and is ready to bake?",
          "options": [
            {
              "id": "A",
              "text": "The dough springs back slowly and leaves a shallow indentation when gently pressed.",
              "why": "A gentle poke that slowly and partially springs back demonstrates optimal gas retention and gluten relaxation."
            },
            {
              "id": "B",
              "text": "The dough feels aerated, puffy, and light to the touch.",
              "why": "Properly proofed loaves hold trapped fermentation gas and feel noticeably pillowy and light."
            },
            {
              "id": "C",
              "text": "The dough immediately snaps back completely with zero indentation left behind.",
              "why": "An immediate, springy bounce-back indicates that the loaf is still tight and underproofed."
            },
            {
              "id": "D",
              "text": "The dough completely deflates and collapses into a puddle upon contact.",
              "why": "Collapsing indicates that gluten has degraded due to severe overproofing."
            }
          ],
          "correct": [
            "A",
            "B"
          ],
          "explanation": "An optimally proofed loaf feels aerated and light. When pressed gently with a finger, the indentation springs back slowly while remaining slightly visible. Snapping back instantly indicates underproofing, while deflating indicates overproofing.",
          "best_practice": "Perform the poke test on the side of the dough rather than on the scored top surface.",
          "docs": [
            "https://example.com/baking/proofing-guide"
          ]
        }
      ]
    }
  ]
}
```

## Test Specification

Each test object has the following fields:

| Field | Required | Description |
|---|---|---|
| `id` | Yes (in single file) | Lowercase letters, numbers, and hyphens (`^[a-z0-9][a-z0-9-]*$`). |
| `title` | Yes | Non-empty string, at most 200 characters. |
| `description` | No | String, at most 1,000 characters. |
| `lang` | No | `"vi"` or `"en"`. Defaults to `"vi"`. Used for speech synthesis. |
| `time_limit_minutes` | No | Integer between `0` and `600`. `0` means untimed. Defaults to `0`. |
| `pass_percent` | No | Integer between `1` and `100`. Defaults to `70`. |
| `items` | Yes | Array of 1 to 200 question items. |

## Question Item Specification

Each item in `items` has the following fields:

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Lowercase letters, numbers, hyphens. Unique within the test. |
| `domain` | No | Primary knowledge domain for scoring breakdown. At most 100 characters. |
| `type` | Yes | `"single"` (single choice) or `"multi"` (multiple choice). |
| `question` | Yes | Markdown text, at most 4,000 characters. |
| `options` | Yes | Array of 2 to 8 choices. |
| `correct` | Yes | List of correct option IDs. Exactly 1 for `"single"`, at least 2 for `"multi"`. |
| `explanation` | Yes | Markdown explanation, at most 4,000 characters. |
| `best_practice` | No | Optional practical tip or rule of thumb, at most 1,000 characters. |
| `docs` | No | Array of at most 5 documentation URLs, each starting with `https://`. |
| `shuffle` | No | Boolean. Defaults to `true`. Set to `false` to preserve original choice order. |

Each option in `options`:
- `id`: A single uppercase letter (`"A"` through `"H"`).
- `text`: Choice text, non-empty, at most 1,000 characters.
- `why`: Optional explanation for why this specific choice is correct or incorrect, at most 1,000 characters.

## Important Authoring Rules

### Updating Correct Answers
To update or correct an answer, modify the `correct` array rather than swapping text between option IDs. The system tracks each question using an answer hash computed from option IDs and the `correct` list. Changing `correct` correctly resets the question's difficulty statistics and learners' wrong-answer review pools.

### Do Not Name Option Letters in Content
Options are shuffled randomly for learners on each attempt unless `shuffle: false`. Do not write "Option A", "Choice B", "Both A and B", or "All of the above" in questions, option texts, why fields, or explanations. Refer directly to the option content instead.

### Domains
Use concise domain names. Do not exceed 12 distinct domains per test to keep domain score breakdowns clear and helpful.

### Fair Options
Shuffling hides position, not length or detail. Do not make the correct option the longest or the most detailed one more often than the others; write wrong options that are as plausible and as long as the right one. In `multi` questions, vary how many options are correct.

### Explanations and Numbers
The checker does not require `why`, but write one for every option: learners read it after checking an answer. Work out every number in a question or answer by running the calculation, not in your head.

### Time Limit and Pass Mark
Leave `time_limit_minutes` out (untimed) unless the author gives a time, for example the real exam's. `pass_percent` defaults to 70; use the real exam's pass mark when the author gives one.

## Validation

Validate any practice test file before uploading:

```bash
python SKILL_DIR/scripts/learnpkg.py validate test.json
```

`SKILL_DIR` is the folder that holds the skill's `SKILL.md`; use its full path. A single `.json` file needs no `contract_version`; a zip's `package.json` does.
