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
| `quizzes/pending.md` | The one round currently out for answering. Absent means none. |
| `quizzes/YYYY-MM-DD.md` | Archive of each quiz round: questions, answers, grading. |
| `scripts/vocab.py` | CLI: `new` / `due` / `inbox` / `review` / `quiz` / `stats` / `validate`. |
| `scripts/build_site.py` | Renders `words/*.md` into a single `site/index.html`. |
| `functions/` | Cloudflare Pages Functions: the write API behind the site. |
| `.github/workflows/pages.yml` | Runs `validate` on push to `main`. |

Run everything from the repo root. The only dependency is PyYAML.

**The owner can add and edit notes from their phone**, through the published
site. Those commits land on `main` directly. So: `git pull` before starting a
quiz round or you will grade a stale copy and push a conflicting `srs` block.

Adding a word there is a *capture*: the form stays open for the next one and
writes only the headword and the sentence it came from. Expect a stream of
half-empty notes on `main` — that is the design, not a mess to tidy.

The web editor only ever writes the note *body* — it re-reads the file at save
time and carries the existing frontmatter over untouched. That is deliberate,
and it is what stops a phone editor from clobbering a review you just recorded.
Keep it that way if you touch `functions/`.

The same discipline governs `quizzes/pending.md`: the phone rewrites only the
answer slots. Its one exception is stamping `answered:`, which it needs so a
rebuilt page can tell an open round from a finished one. Nothing else in any
frontmatter is ever written from the web.

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

### Two sections are required, the rest is depth

`## Definition` and `## In the wild` are what make a note usable. The other
six headings — etymology, word family, synonyms, collocations, own sentences,
notes — are added when the owner feels like it, and `validate` says nothing
about their absence. Do not treat a note without them as unfinished, and do
not add empty headings to "complete" a note.

`templates/word.md` therefore ships with the two required sections only;
`vocab.py new <word> --full` lays all eight out for when the owner means to
write the whole thing in one sitting.

### A note with no definition is not in the review queue

Capturing a word takes seconds on a phone; writing it up wants a keyboard.
So a note whose `## Definition` is still empty and which has never been
quizzed counts as **unwritten**: `due` skips it (as `--fill` padding too),
the site badges it *needs a note*, and `vocab.py inbox` lists them oldest
first. Writing the definition is all it takes to join the rotation — the
state is derived (`is_unwritten` in `vocab.py`), not a flag to remember.

This means the review queue can be empty while the notebook is full. If
`due` reports nothing, check `inbox` before concluding there is no work.

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

   Words with no definition never appear here, so a round can come back
   short — or empty — while `words/` is full. `due` prints how many are
   waiting on stderr; if that is where the work actually is, say so and
   offer `inbox` instead of quizzing on thin notes.

2. **Ask the questions.** Three formats, described below. Mix them — one
   word gets one question. Put every question in a single message and let
   the owner answer them all at once; do not drip-feed one at a time.

   In the chat, that is one message. If they want to answer on their phone
   later, write the round to `quizzes/pending.md` instead and push — see
   [Asking asynchronously](#asking-asynchronously).

3. **Grade.** Go through the answers one by one, in Chinese, quoting what
   they wrote. Be specific about *why* something is off — a wrong
   collocation, a register mismatch, a meaning that drifted. Praise that
   does not identify what was good is noise.

4. **Record and archive.** One command does both:
   ```bash
   python scripts/vocab.py quiz close serendipity=correct equivocate=wrong ...
   ```
   It advances every `srs` block, appends the round to `quizzes/YYYY-MM-DD.md`
   in the format `quizzes/README.md` documents, and deletes `pending.md`. A
   result is required for every question — a round is recorded whole or not
   at all, so a crash cannot leave half a round applied.

   Without a `pending.md` (a round asked and answered in chat), record each
   word directly and write the archive entry by hand:
   ```bash
   python scripts/vocab.py review <word> --result correct|wrong
   ```

5. **Write the grading in.** `quiz close` leaves each `**评**` line as a
   placeholder comment. Edit the archive file and replace them with what you
   said in step 3 — that commentary is the reason the archive is worth
   keeping.

6. **Commit** the changed `words/*.md` and the quiz file together, with a
   message like `quiz: 2026-08-08 round (3 correct, 2 wrong)`.

### Asking asynchronously

The owner's commute is good reviewing time and their laptop is not there. So
a round can be handed over: you set it on the laptop, they answer it on the
phone, you grade it back on the laptop.

Write `quizzes/pending.md` — its presence *is* the open round — and push:

```markdown
---
round: 2026-08-08-1
asked: 2026-08-08
answered: null
---

## 1. serendipity · Compose

描述一次你在整理旧硬盘时翻到了别的东西的经历。用这个词写一句话。

**A**

## 2. equivocate · Infer

Pressed three times on whether the factory would close, the minister
equivocated until the moderator gave up.

**A**
```

The rules that matter:

- One `## <n>. <word> · <Format>` heading per question, numbered from 1, one
  question per word. Format is Compose, Infer or Discriminate.
- `**A**` on its own line is where the answer goes. **Everything above it in
  a section is yours, everything below it is theirs.** The web side rewrites
  only what is below, and stamps `answered:`; it touches nothing else.
- `vocab.py validate` checks all of this, and CI runs it. A malformed
  heading would otherwise become a question that silently never reaches the
  phone.

Then, next session: `git pull`, and

```bash
python scripts/vocab.py quiz status    # is it answered yet
python scripts/vocab.py quiz answers   # the round as JSON, for grading
```

Grade from that JSON exactly as you would grade a round answered in chat,
then `quiz close`. **Never fill in an `**A**` yourself** — an answer the
owner did not write teaches nothing and corrupts the record.

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
(floored at 0) and due tomorrow. `vocab.py review` and `vocab.py quiz close`
both go through `apply_review`, which is the only place the schedule lives —
do not hand-edit the `srs` block, and do not reimplement the arithmetic.

A word with no definition is not in the schedule at all; see
[A note with no definition is not in the review
queue](#a-note-with-no-definition-is-not-in-the-review-queue).

## Before you push

```bash
python scripts/vocab.py validate   # must exit 0; CI runs this too
python scripts/build_site.py       # sanity check the site still builds
```

`site/` is a build artifact and is gitignored — CI rebuilds it. Never commit it.
