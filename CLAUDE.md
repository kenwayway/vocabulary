# Project conventions

A personal English vocabulary notebook. Notes live as Markdown in `words/`,
a small Python CLI maintains the spaced-repetition state, and a static site
built from the same files is what gets read on a phone.

The owner is a Chinese speaker learning English. **Talk to them in Chinese**,
but keep all quiz material, definitions and note content in English — the
whole point of the notebook is English-in-English.

## Layout

| Path | What it is |
| --- | --- |
| `words/<slug>.md` | One note per headword. The only source of truth. |
| `templates/word.md` | The blank skeleton `vocab.py new` copies. |
| `quizzes/YYYY-MM-DD.md` | Archive of each quiz round: questions, answers, grading. |
| `scripts/vocab.py` | CLI: `new` / `due` / `review` / `stats` / `validate`. |
| `scripts/build_site.py` | Renders `words/*.md` into a single `site/index.html`. |
| `.github/workflows/pages.yml` | Validates and publishes the site on push to `main`. |

Run everything from the repo root. The only dependency is PyYAML.

## Writing notes — read this before you touch `words/`

**The note bodies belong to the owner.** They write them by hand; that is
how the words stick. Do not fill in, rewrite, tidy or "improve" the prose
under any `##` heading unless you are explicitly asked to.

What you *may* always do without asking:

- create the file skeleton (`python scripts/vocab.py new <word>`)
- update the `srs:` block via `python scripts/vocab.py review`
- fix a genuine structural problem `vocab.py validate` reports

What needs an explicit request ("帮我补全 / 帮我写"):

- writing the definition, etymology, synonym nuance, collocations, examples

When you *are* asked to draft a note, aim at the standard the seed words
(`serendipity`, `equivocate`, `tenuous`) set: an English definition in plain
words rather than a dictionary copy-paste, a real etymology with the cognates
that make the root memorable, synonyms with the *difference* spelled out
rather than a bare list, and collocations that are actually attested. Never
invent a citation for `## In the wild` — that section is for a sentence the
owner genuinely met. Leave it alone if they have not supplied one.

## Running a quiz

This is the main thing you do here. The flow:

1. **Pick the words.**
   ```bash
   python scripts/vocab.py due --limit 5 --fill --json
   ```
   `--fill` tops the list up with the least recently reviewed words when
   fewer than five are actually due, so a round is never empty. Check the
   `is_due` flag if you want to tell the two apart.

2. **Ask the questions.** Three formats, described below. Mix them — one
   word gets one question. Put every question in a single message and let
   the owner answer them all at once; do not drip-feed one at a time.

3. **Grade.** Go through the answers one by one, in Chinese, quoting what
   they wrote. Be specific about *why* something is off — a wrong
   collocation, a register mismatch, a meaning that drifted. Praise that
   does not identify what was good is noise.

4. **Record.** For each word:
   ```bash
   python scripts/vocab.py review <word> --result correct|wrong
   ```

5. **Archive.** Append the round to `quizzes/YYYY-MM-DD.md` (create it if
   this is the day's first round): the questions, their answers verbatim,
   your grading, and the resulting level changes.

6. **Commit** the changed `words/*.md` and the quiz file together, with a
   message like `quiz: 2026-08-08 round (3 correct, 2 wrong)`.

### Question formats

**A. Compose (自己造句)** — Give a concrete situation, not a bare
instruction: "描述一次你没准备好的面试" beats "用这个词造句". Ask them to
write one sentence using the word. Grade naturalness, collocation and
register, not grammar alone. A grammatically perfect sentence that no
native speaker would produce is *wrong*, and you should say so and show the
version a native speaker would write.

**B. Infer in context (语境推义)** — You write an English sentence using
the word, and ask what it means there. The sentence must supply enough
context to make the meaning recoverable, but must not gloss the word. Do
not reuse the sentence from the note's `## In the wild` — write a fresh
one, in a different domain if you can.

**C. Discriminate (近义词辨析)** — Give one English sentence with a gap and
three or four near synonyms (pull them from the note's `## Synonyms &
nuance` where possible). Ask which fits best *and why the others do not*.
The "why" is the part being tested; an answer with the right pick and no
reasoning is at best a partial credit.

### Grading standard

- **correct** — the meaning is right and the usage is idiomatic. Small
  grammar slips unrelated to the target word do not count against it.
- **wrong** — the meaning is off, the collocation is not idiomatic, the
  register is wrong for the context, or (format C) the right option was
  picked for the wrong reason.
- **Partial answers count as `wrong`.** Half-remembering is exactly the
  signal the scheduler needs; being generous here quietly breaks the
  spacing. Say plainly that you are recording it as wrong and why.

## The spaced repetition state

`srs` in each file's frontmatter. Levels 0–6 map to intervals
`[1, 3, 7, 14, 30, 60, 120]` days. Correct → level + 1. Wrong → level − 2
(floored at 0) and due tomorrow. `vocab.py review` handles all of this —
do not hand-edit the `srs` block.

## Before you push

```bash
python scripts/vocab.py validate   # must exit 0; CI runs this too
python scripts/build_site.py       # sanity check the site still builds
```

`site/` is a build artifact and is gitignored — CI rebuilds it. Never commit it.
