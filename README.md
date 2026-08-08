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
`site/index.html` — data inlined, no external requests — which GitHub Actions
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

## Repository layout

| Path | Contents |
| --- | --- |
| `words/<slug>.md` | One note per headword. The only source of truth. |
| `templates/word.md` | The blank skeleton `vocab.py new` copies. |
| `quizzes/YYYY-MM-DD.md` | Archive of each round: questions, answers, grading. |
| `scripts/vocab.py` | CLI: `new` / `due` / `review` / `stats` / `validate`. |
| `scripts/build_site.py` | Renders `words/*.md` into `site/index.html`. |
| `.github/workflows/pages.yml` | Validates and publishes on push to `main`. |

## Setup

Publishing requires the repository to be public:

1. `Settings → General → Danger Zone → Change visibility` → **Public**
2. `Settings → Pages → Source` → **GitHub Actions**

The second step matters. With the source left on *Deploy from a branch*, GitHub
serves the repository root through its built-in Jekyll builder and publishes
`README.md` as the home page — the build workflow runs, but nothing it produces
is ever deployed.
