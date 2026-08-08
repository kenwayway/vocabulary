# Vocabulary

A personal English vocabulary notebook. Each word is a single Markdown file
tracked in Git, scheduled for review by a small Python CLI, and published as a
static site that reads well on a phone.

[![Build and deploy site](https://github.com/kenwayway/vocabulary/actions/workflows/pages.yml/badge.svg)](https://github.com/kenwayway/vocabulary/actions/workflows/pages.yml)

📖 **[Read the notebook](https://kenwayway.github.io/vocabulary/)**

---

## How it works

The system has three parts, and only the first one is authoritative:

1. **The notes.** `words/<slug>.md` — one file per headword. YAML frontmatter
   holds the structured fields and the spaced-repetition state; the body holds
   notes written by hand.
2. **The CLI.** `scripts/vocab.py` creates notes from a template, reports what
   is due, records review outcomes, and validates the collection.
3. **Claude.** Runs the quiz rounds: selects words, asks questions, grades the
   answers, writes the results back, and archives each round.

Everything else — the published site, the review schedule, the statistics — is
derived from the Markdown files. Nothing is stored anywhere else.

## Requirements

Python 3.9 or later (CI runs 3.12) and a single dependency:

```bash
pip install pyyaml
```

Run all commands from the repository root.

## Adding a word

Generate the skeleton from the template:

```bash
python scripts/vocab.py new serendipity --pos noun --tags "literary,chance"
```

This writes `words/serendipity.md` with today's date and an initial review
state, so the word appears in the next quiz round. Then fill in the sections by
hand:

| Section | What goes in it |
| --- | --- |
| `## Definition` | An English definition in your own words, not a dictionary copy-paste |
| `## In the wild` | The sentence where you actually met the word, with its source |
| `## Etymology` | Roots and affixes — learn the root and you get a family of words |
| `## Word family` | Related forms: adjective, adverb, verb |
| `## Synonyms & nuance` | Not a list; spell out how each one differs |
| `## Collocations` | The words it habitually travels with |
| `## My sentences` | Your own sentences. Add one at every review |
| `## Notes` | Memory hooks, confusions, anything else |

Commit and push when the note is ready; the site rebuilds automatically.

From a phone, the published site does the same thing: the **+** button asks for
the headword and the sentence you met it in, commits `words/<slug>.md`, and
opens the editor on the body. See [Writing from the site](#writing-from-the-site).

Multi-word entries work too — `vocab.py new "give up"` creates
`words/give-up.md`. The filename is derived from the headword and must keep
matching it, so rename entries through the `word:` field rather than by moving
files.

`serendipity`, `equivocate` and `tenuous` ship as worked examples of the
intended depth. Delete them once they have served their purpose.

## Reviewing

Open a Claude Code session and ask to be quizzed. Each round:

1. Selects five words that are due, topping up with the least recently
   reviewed ones when fewer than five have come up.
2. Asks three kinds of question — **compose a sentence**, **infer the meaning
   from context**, and **discriminate between near synonyms**.
3. Grades each answer in Chinese, naming the specific problem: a wrong
   collocation, a register mismatch, a meaning that drifted.
4. Writes the outcome back into each word's review state and archives the
   round in `quizzes/YYYY-MM-DD.md`.

Note bodies belong to the owner and are left alone by default. To have a note
drafted, ask for it explicitly.

## Commands

```bash
python scripts/vocab.py new <word>              # create from the template
python scripts/vocab.py due                     # what is due today
python scripts/vocab.py due --limit 5 --fill    # top up to five words
python scripts/vocab.py review <word> --result correct|wrong
python scripts/vocab.py stats                   # totals, familiarity spread, accuracy
python scripts/vocab.py validate                # structural check; CI runs this too
python scripts/build_site.py                    # render site/index.html
```

`validate` must exit 0 before a push. It reports genuine structural problems as
errors — a filename that no longer matches its headword, a malformed date, an
out-of-range level — while incomplete notes are only warnings and never block a
build.

## Review schedule

Familiarity runs from level 0 to 6, mapping to intervals of
**1 / 3 / 7 / 14 / 30 / 60 / 120** days. A correct answer advances one level. A
wrong answer drops two levels and schedules the word for tomorrow.

Partial answers count as wrong. Half-remembering is precisely the signal the
scheduler needs, and grading it generously quietly breaks the spacing.

The `srs` block is maintained by `vocab.py review` and should not be edited by
hand.

## The site

`scripts/build_site.py` renders every note into a single self-contained
`site/index.html` — data inlined, no external requests — which Cloudflare Pages
publishes on every push to `main`. Once loaded, it works offline; add it to the
home screen for a reader that behaves like an app.

- **Browse** — search across definitions and notes, filter by due date, recency,
  weakest, or tag, and open any word for the full note.
- **Cards** — self-test on the English definition and a cloze-deleted example,
  then flip for the word.

The card tally is per-round and deliberately not saved. Review progress is
recorded only through the quiz flow.

`site/` is a build artifact and is gitignored; CI regenerates it. Never commit
it.

## Writing from the site

Built with `--api` (which Cloudflare Pages does and the local build does not),
the site can add words and edit note bodies. Both write straight to
`words/*.md` on `main` through the GitHub API, so the Markdown files stay the
only source of truth and `vocab.py` needs no changes.

**The API never touches frontmatter.** `GET /api/note/<slug>` returns the body
alone, and `PUT` re-reads the file at save time and carries the existing
frontmatter over untouched. This is what keeps the review state safe: an
editor opened at breakfast and saved at lunch cannot undo a `vocab.py review`
that landed in between, because the two writers never touch the same bytes.
Conflicts are detected on a hash of the body only, so a review landing mid-edit
is not reported as one.

If the body *did* change elsewhere, the save is refused and you choose: keep
what you typed, or load the other version. Nothing is discarded silently. Work
in progress is also mirrored to `localStorage`, so a phone killing the tab does
not lose the paragraph you were halfway through.

Saving commits to `main`; the site rebuilds and the new text appears about a
minute later.

### Deploying it

1. **Cloudflare Pages → Create → Connect to Git**, pick this repository.
   - Build command: `pip install pyyaml && python scripts/vocab.py validate && python scripts/build_site.py --api`
   - Build output directory: `site`
   - Environment variable: `PYTHON_VERSION` = `3.12`
2. **Lock it down before adding the token.** Zero Trust → Access → Applications
   → Self-hosted, covering the whole site. Add a policy allowing your own email
   only, and copy the **Application Audience (AUD) tag**.
3. **Create a GitHub token yourself** — fine-grained, this repository only,
   *Contents: Read and write*, and nothing else. Do not paste it anywhere but
   the Cloudflare dashboard.
4. **Settings → Variables and Secrets**, all in Production:

   | Name | Kind | Value |
   | --- | --- | --- |
   | `GITHUB_TOKEN` | Secret | the token from step 3 |
   | `GITHUB_REPO` | Text | `kenwayway/vocabulary` |
   | `GITHUB_BRANCH` | Text | `main` |
   | `CF_ACCESS_TEAM_DOMAIN` | Text | `<team>.cloudflareaccess.com` |
   | `CF_ACCESS_AUD` | Text | the AUD tag from step 2 |
   | `ALLOWED_EMAILS` | Text | your email |
   | `TIMEZONE` | Text | `Asia/Shanghai` |

Access is verified by the Function itself, not just at the edge, and with
`CF_ACCESS_TEAM_DOMAIN` or `CF_ACCESS_AUD` missing the API refuses every
request. A misconfiguration makes writing stop working; it does not make the
repository writable by strangers.

`TIMEZONE` decides what `added:` says. A Worker runs in UTC, so without it a
word added before 08:00 in Shanghai would be filed under the previous day and
come up due a day early.

GitHub Pages can stay switched on as a read-only mirror — its build has no
`--api`, so it shows no editing UI.

## Repository layout

| Path | Contents |
| --- | --- |
| `words/<slug>.md` | One note per headword. The only source of truth. |
| `templates/word.md` | The blank skeleton `vocab.py new` copies. |
| `quizzes/YYYY-MM-DD.md` | Archive of each round: questions, answers, grading. |
| `scripts/vocab.py` | CLI: `new` / `due` / `review` / `stats` / `validate`. |
| `scripts/build_site.py` | Renders `words/*.md` into `site/index.html`. |
| `functions/api/*` | The write API: create a note, read and save a body. |
| `functions/_lib/notes.js` | Note format helpers, mirroring `vocab.py`. |
| `.github/workflows/pages.yml` | Structural check on push to `main`. |

Nothing under `functions/` runs during a local build; it is invoked by
Cloudflare Pages, and only for `/api/*` (`site/_routes.json` keeps every other
request on static assets).

## Setup

Deployment and the write API are covered in
[Writing from the site](#writing-from-the-site). To keep the GitHub Pages
mirror as well, the repository must be public:

1. `Settings → General → Danger Zone → Change visibility` → **Public**
2. `Settings → Pages → Source` → **GitHub Actions**

The second step matters. With the source left on *Deploy from a branch*, GitHub
serves the repository root through its built-in Jekyll builder and publishes
`README.md` as the home page.
