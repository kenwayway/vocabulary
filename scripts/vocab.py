#!/usr/bin/env python3
"""Command line tool for the vocabulary note system.

Every word lives in ``words/<slug>.md`` as a Markdown file whose YAML
frontmatter holds the structured fields (part of speech, tags, spaced
repetition state) and whose body holds the hand written notes.

Subcommands:
    new       create a new word file from templates/word.md
    due       list words that are due for review
    inbox     list words captured but not yet written up
    review    record the outcome of a review and advance the SRS state
    quiz      inspect, read and close the round in quizzes/pending.md
    stats     summarise the collection
    validate  check every word file for structural problems

Capturing a word and writing it up are separate steps: a note with no
definition stays out of the review queue until it has one. See ``is_unwritten``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORDS_DIR = ROOT / "words"
QUIZZES_DIR = ROOT / "quizzes"
TEMPLATE_PATH = ROOT / "templates" / "word.md"

# The round currently out for answering. Exists only while one is open: writing
# it starts a round, `quiz close` removes it.
PENDING_PATH = QUIZZES_DIR / "pending.md"

# Interval in days for each familiarity level. Answering correctly moves the
# word one level up, getting it wrong drops it two levels and schedules it for
# tomorrow.
SRS_INTERVALS = [1, 3, 7, 14, 30, 60, 120]
MAX_LEVEL = len(SRS_INTERVALS) - 1

SRS_FIELDS = ("level", "due", "last_reviewed", "correct", "wrong")
META_ORDER = ("word", "pos", "pronunciation", "tags", "added", "srs")

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL)

COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# The menu of optional headings the short template carries. `new --full`
# replaces it with the headings themselves.
MORE_RE = re.compile(r"<!--\s*MORE:.*?-->\s*", re.DOTALL)

# Lines the template leaves behind as empty slots: a blockquote marker with no
# quote, an em dash with no source, a bullet with no item. A section holding
# nothing but these has not been written yet.
PLACEHOLDER_LINES = {">", "—", "-", "*"}

# The only two sections worth nagging about. A note with a definition and the
# sentence you met the word in is already a usable note; everything else is
# depth you add when you feel like it. Eight compulsory headings is how a note
# ends up with none of them filled in.
REQUIRED_SECTIONS = ("Definition", "In the wild")

# Heading -> the hint that goes under it. `new --full` lays these out; the
# short template just lists their names.
OPTIONAL_SECTIONS = (
    ("Etymology", "Roots, affixes, the story of how the word got here."),
    ("Word family", "Related forms: adjective, adverb, verb..."),
    ("Synonyms & nuance", "Not just a list: say how each one differs."),
    ("Collocations", "The words it habitually travels with."),
    ("My sentences", "Sentences you wrote yourself. Add to this every time you review."),
    ("Notes", "Memory hooks, confusions, anything else."),
)

# One question in quizzes/pending.md: '## 1. serendipity · Compose', the same
# heading shape the archive already uses (see quizzes/README.md). Spacing around
# the separator is loose because these headings are written by hand.
QUIZ_FORMATS = ("compose", "infer", "discriminate")
QUIZ_HEADING_RE = re.compile(
    r"^##\s+(\d+)\.\s+(.+?)\s*·\s*(" + "|".join(QUIZ_FORMATS) + r")\s*$",
    re.IGNORECASE,
)
# The line that separates a question from the slot its answer goes in.
ANSWER_MARKER = "**A**"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def today() -> dt.date:
    return dt.date.today()


def slugify(word: str) -> str:
    """Turn a headword into a filename stem: 'give up' -> 'give-up'."""
    text = unicodedata.normalize("NFKD", word).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9\-']", "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def as_date(value) -> dt.date | None:
    """Coerce a frontmatter value into a date, or None. Raises on garbage."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value).strip())


def as_date_or(value, fallback: dt.date | None) -> dt.date | None:
    """Like as_date, but a malformed value degrades to the fallback.

    These files are hand edited, so a typo in a date must not take down every
    command. `validate` is the place that reports the problem loudly.
    """
    try:
        parsed = as_date(value)
    except (ValueError, TypeError):
        return fallback
    return fallback if parsed is None else parsed


def as_int(value, fallback: int) -> int:
    """Coerce to int, degrading to the fallback rather than raising."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return fallback


def yaml_scalar(value) -> str:
    """Serialise a single value the way PyYAML would, without a trailing doc marker.

    Dumping ``{"_": value}`` in flow style and slicing off the wrapper gives us
    correct quoting for awkward strings (IPA, colons, URLs) while keeping short
    lists inline as ``[a, b]``.
    """
    dumped = yaml.safe_dump(
        {"_": value}, default_flow_style=True, allow_unicode=True, sort_keys=False
    ).strip()
    if dumped.startswith("{_: ") and dumped.endswith("}"):
        return dumped[4:-1]
    # Fall back to a conservative quoted form.
    return json.dumps(value, ensure_ascii=False)


def parse_note(path: Path) -> tuple[dict, str]:
    """Split a note into its frontmatter mapping and Markdown body."""
    raw = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(raw)
    if not match:
        raise ValueError("file does not start with a '---' YAML frontmatter block")
    meta = yaml.safe_load(match.group(1))
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise ValueError("frontmatter must be a mapping")
    return meta, match.group(2)


def default_srs(due: dt.date | None = None) -> dict:
    return {
        "level": 0,
        "due": due if due is not None else today(),
        "last_reviewed": None,
        "correct": 0,
        "wrong": 0,
    }


def normalise_meta(meta: dict) -> dict:
    """Fill in missing keys and coerce dates so callers can rely on the shape."""
    meta.setdefault("word", "")
    meta.setdefault("pos", "")
    meta.setdefault("pronunciation", "")
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    meta["tags"] = list(tags)
    meta["added"] = as_date_or(meta.get("added"), today())

    srs = meta.get("srs")
    if not isinstance(srs, dict):
        srs = {}
    merged = default_srs(meta["added"])
    merged.update({k: v for k, v in srs.items() if k in SRS_FIELDS})
    merged["level"] = max(0, min(MAX_LEVEL, as_int(merged.get("level"), 0)))
    merged["due"] = as_date_or(merged.get("due"), meta["added"])
    merged["last_reviewed"] = as_date_or(merged.get("last_reviewed"), None)
    merged["correct"] = max(0, as_int(merged.get("correct"), 0))
    merged["wrong"] = max(0, as_int(merged.get("wrong"), 0))
    meta["srs"] = merged
    return meta


def dump_frontmatter(meta: dict) -> str:
    """Render frontmatter with a stable key order so diffs stay readable."""
    lines = ["---"]
    for key in META_ORDER:
        if key == "srs":
            continue
        if key not in meta:
            continue
        lines.append(f"{key}: {yaml_scalar(meta[key])}")
    srs = meta.get("srs") or {}
    if srs:
        lines.append("srs:")
        for key in SRS_FIELDS:
            lines.append(f"  {key}: {yaml_scalar(srs.get(key))}")
    for key in sorted(k for k in meta if k not in META_ORDER):
        lines.append(f"{key}: {yaml_scalar(meta[key])}")
    lines.append("---")
    return "\n".join(lines)


def write_note(path: Path, meta: dict, body: str) -> None:
    body = body.lstrip("\n")
    path.write_text(f"{dump_frontmatter(meta)}\n\n{body}", encoding="utf-8")


def note_paths() -> list[Path]:
    if not WORDS_DIR.is_dir():
        return []
    return sorted(WORDS_DIR.glob("*.md"))


def load_all(strict: bool = False) -> list[dict]:
    """Load every note. Broken files are skipped with a warning unless strict."""
    entries = []
    for path in note_paths():
        try:
            meta, body = parse_note(path)
            meta = normalise_meta(meta)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            message = f"{path.relative_to(ROOT)}: {exc}"
            if strict:
                raise ValueError(message) from exc
            print(f"warning: skipping {message}", file=sys.stderr)
            continue
        entries.append({"path": path, "meta": meta, "body": body})
    return entries


def find_note(word: str) -> dict:
    slug = slugify(word)
    for entry in load_all():
        if entry["path"].stem == slug or slugify(str(entry["meta"]["word"])) == slug:
            return entry
    raise SystemExit(f"error: no note found for '{word}' (looked for words/{slug}.md)")


def split_sections(body: str) -> dict[str, str]:
    """Map '## Heading' -> the text beneath it."""
    sections: dict[str, str] = {}
    heading = None
    buffer: list[str] = []
    for line in body.splitlines():
        match = re.match(r"^##\s+(.*?)\s*$", line)
        if match:
            if heading is not None:
                sections[heading] = "\n".join(buffer).strip()
            heading = match.group(1)
            buffer = []
        elif heading is not None:
            buffer.append(line)
    if heading is not None:
        sections[heading] = "\n".join(buffer).strip()
    return sections


def clean_section(raw: str) -> str:
    """What a section actually says, with the template's leftovers removed.

    ``split_sections`` returns whatever sits under the heading, and for a fresh
    note that is the template's HTML hint plus an empty slot or two. Those must
    not count as content: a Definition still reading ``<!-- ... -->`` has not
    been written, and noticing that is the whole job of ``inbox``.
    """
    stripped = COMMENT_RE.sub("", raw or "")
    kept = [
        line
        for line in stripped.splitlines()
        if line.strip() and line.strip() not in PLACEHOLDER_LINES
    ]
    return "\n".join(kept).strip()


def is_unwritten(entry: dict) -> bool:
    """True while a note is still just a captured headword.

    Adding a word and writing it up are two different jobs: one takes thirty
    seconds on a phone, the other wants a keyboard and a dictionary. A note
    with no definition that has never been quizzed is waiting for the second
    job, and until it arrives the word stays out of the review queue — there is
    nothing in the file to be quizzed on yet.

    Derived rather than stored, so writing the definition is all it takes to
    join the rotation. There is no flag to remember to flip.
    """
    if entry["meta"]["srs"]["last_reviewed"] is not None:
        return False
    return not clean_section(split_sections(entry["body"]).get("Definition", ""))


def expand_body(body: str, full: bool) -> str:
    """Turn the template body into the skeleton `new` should write.

    The template ships with the two required sections and a comment naming the
    optional ones. ``--full`` swaps that comment for the headings themselves,
    for when you are at a keyboard and mean to write the whole thing in one go.
    """
    if not full:
        return body
    laid_out = "\n".join(f"## {name}\n<!-- {hint} -->\n" for name, hint in OPTIONAL_SECTIONS)
    return f"{MORE_RE.sub('', body).rstrip()}\n\n{laid_out}"


# --------------------------------------------------------------------------
# the pending round
# --------------------------------------------------------------------------


def parse_pending(path: Path | None = None) -> dict | None:
    """Read quizzes/pending.md, or None when no round is open.

    A round is written on a laptop and answered on a phone, so this file is the
    handover between them. Questions and answers are kept apart by a single
    ``**A**`` line: everything above it in a section is the question and belongs
    to whoever set it, everything below is the answer and belongs to the owner.
    The web side only ever rewrites what is below.
    """
    path = path or PENDING_PATH
    if not path.exists():
        return None

    meta, body = parse_note(path)
    questions: list[dict] = []
    current: dict | None = None
    in_answer = False

    for line in body.splitlines():
        heading = QUIZ_HEADING_RE.match(line)
        if heading:
            current = {
                "n": int(heading.group(1)),
                "word": heading.group(2).strip(),
                "format": heading.group(3).lower(),
                "has_marker": False,
                "_question": [],
                "_answer": [],
            }
            questions.append(current)
            in_answer = False
            continue
        if current is None:
            continue
        if line.strip() == ANSWER_MARKER:
            current["has_marker"] = True
            in_answer = True
            continue
        current["_answer" if in_answer else "_question"].append(line)

    for question in questions:
        question["question"] = "\n".join(question.pop("_question")).strip()
        question["answer"] = "\n".join(question.pop("_answer")).strip()

    return {
        "path": path,
        "round": str(meta.get("round") or "").strip(),
        "asked": as_date_or(meta.get("asked"), None),
        "answered": as_date_or(meta.get("answered"), None),
        "questions": questions,
    }


def pending_problems(pending: dict) -> list[str]:
    """Structural complaints about a pending round, worst first.

    Worth checking because the file is hand written on one machine and parsed on
    two others: a typo in a heading would otherwise surface as a question that
    silently vanishes from the phone.
    """
    problems: list[str] = []
    if not pending["round"]:
        problems.append("frontmatter has no 'round'")
    if pending["asked"] is None:
        problems.append("frontmatter has no valid 'asked' date")

    questions = pending["questions"]
    if not questions:
        problems.append("no '## <n>. <word> · <Format>' headings found")
        return problems

    known = {path.stem for path in note_paths()}
    for question in questions:
        label = f"question {question['n']} ({question['word']})"
        if slugify(question["word"]) not in known:
            problems.append(f"{label}: there is no note in words/ for this headword")
        if not question["has_marker"]:
            problems.append(f"{label}: no '{ANSWER_MARKER}' line, so there is nowhere to answer")
        if not question["question"]:
            problems.append(f"{label}: the question itself is empty")

    numbers = [q["n"] for q in questions]
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(f"questions are numbered {numbers}, expected 1..{len(numbers)}")

    slugs = [slugify(q["word"]) for q in questions]
    repeated = sorted({s for s in slugs if slugs.count(s) > 1})
    if repeated:
        problems.append(f"one word gets one question, but these repeat: {', '.join(repeated)}")

    return problems


def apply_review(meta: dict, result: str) -> tuple[int, int]:
    """Advance the srs block for one outcome. Returns (level before, after).

    Shared by `review` and `quiz close` so the two cannot drift: the schedule
    lives here and nowhere else.
    """
    srs = meta["srs"]
    before = srs["level"]
    if result == "correct":
        srs["level"] = min(MAX_LEVEL, srs["level"] + 1)
        srs["correct"] += 1
        srs["due"] = today() + dt.timedelta(days=SRS_INTERVALS[srs["level"]])
    else:
        srs["level"] = max(0, srs["level"] - 2)
        srs["wrong"] += 1
        srs["due"] = today() + dt.timedelta(days=1)
    srs["last_reviewed"] = today()
    return before, srs["level"]


def overdue_days(entry: dict, ref: dt.date) -> int:
    return (ref - entry["meta"]["srs"]["due"]).days


def sort_key_for_review(entry: dict, ref: dt.date):
    """Most overdue first; among equals, never-reviewed and lower level first."""
    srs = entry["meta"]["srs"]
    return (
        -overdue_days(entry, ref),
        srs["last_reviewed"] is not None,
        srs["level"],
        entry["meta"]["word"],
    )


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def cmd_new(args) -> int:
    word = args.word.strip()
    if not word:
        raise SystemExit("error: word must not be empty")
    slug = slugify(word)
    if not slug:
        raise SystemExit(f"error: '{word}' does not produce a usable filename")

    path = WORDS_DIR / f"{slug}.md"
    if path.exists() and not args.force:
        raise SystemExit(f"error: {path.relative_to(ROOT)} already exists (use --force to overwrite)")

    if not TEMPLATE_PATH.exists():
        raise SystemExit(f"error: template not found at {TEMPLATE_PATH.relative_to(ROOT)}")
    meta, body = parse_note(TEMPLATE_PATH)
    meta = normalise_meta(meta)
    body = expand_body(body, args.full)

    meta["word"] = word
    meta["pos"] = args.pos or ""
    meta["pronunciation"] = args.pronunciation or ""
    meta["tags"] = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    meta["added"] = today()
    # A brand new word is due immediately so it shows up in the first quiz.
    meta["srs"] = default_srs(today())

    WORDS_DIR.mkdir(parents=True, exist_ok=True)
    write_note(path, meta, body)
    print(f"created {path.relative_to(ROOT)}")
    print("It joins the review queue once '## Definition' says something.")
    return 0


def cmd_due(args) -> int:
    ref = today()
    entries = load_all()

    # A captured headword with no definition is not quizzable, so it never
    # reaches a round — not as a due word, and not as --fill padding either.
    ready = [e for e in entries if not is_unwritten(e)]
    waiting = len(entries) - len(ready)
    if waiting:
        print(
            f"note: {waiting} word(s) still waiting for a definition "
            f"(python scripts/vocab.py inbox)",
            file=sys.stderr,
        )

    due = [e for e in ready if overdue_days(e, ref) >= 0]
    due.sort(key=lambda e: sort_key_for_review(e, ref))

    selected = due[: args.limit] if args.limit else due

    if args.fill and args.limit and len(selected) < args.limit:
        chosen = {e["path"] for e in selected}
        rest = [e for e in ready if e["path"] not in chosen]
        # Prefer words never reviewed, then the ones reviewed longest ago.
        rest.sort(
            key=lambda e: (
                e["meta"]["srs"]["last_reviewed"] is not None,
                e["meta"]["srs"]["last_reviewed"] or dt.date.min,
                e["meta"]["srs"]["level"],
            )
        )
        selected = selected + rest[: args.limit - len(selected)]

    if args.json:
        payload = [
            {
                "word": e["meta"]["word"],
                "file": str(e["path"].relative_to(ROOT)),
                "pos": e["meta"]["pos"],
                "tags": e["meta"]["tags"],
                "level": e["meta"]["srs"]["level"],
                "due": e["meta"]["srs"]["due"].isoformat(),
                # With --fill the list can include words that are not actually
                # due yet, so callers need this flag rather than overdue_days.
                "is_due": overdue_days(e, ref) >= 0,
                "overdue_days": max(0, overdue_days(e, ref)),
                "correct": e["meta"]["srs"]["correct"],
                "wrong": e["meta"]["srs"]["wrong"],
            }
            for e in selected
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not selected:
        if waiting:
            print(
                "Nothing due today, but there are notes to write:\n"
                "  python scripts/vocab.py inbox"
            )
        else:
            print("Nothing due today. Add a word with: python scripts/vocab.py new <word>")
        return 0

    for entry in selected:
        srs = entry["meta"]["srs"]
        late = overdue_days(entry, ref)
        if late > 0:
            when = f"{late}d overdue"
        elif late == 0:
            when = "due today"
        else:
            when = f"in {-late}d"
        print(f"{str(entry['meta']['word']):<24} lvl {srs['level']}  due {srs['due']}  ({when})")
    return 0


def cmd_inbox(args) -> int:
    """The words that have been captured but not yet written up."""
    ref = today()
    entries = [e for e in load_all() if is_unwritten(e)]
    entries.sort(key=lambda e: (e["meta"]["added"], str(e["meta"]["word"])))

    def context_of(entry: dict) -> str:
        return clean_section(split_sections(entry["body"]).get("In the wild", ""))

    if args.json:
        payload = [
            {
                "word": str(e["meta"]["word"]),
                "file": str(e["path"].relative_to(ROOT)),
                "added": e["meta"]["added"].isoformat(),
                "waiting_days": (ref - e["meta"]["added"]).days,
                # The sentence you met it in is what you write the note from,
                # so it is worth knowing which of these have one.
                "has_context": bool(context_of(e)),
            }
            for e in entries
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not entries:
        print("Every word has a definition. Nothing waiting.")
        return 0

    for entry in entries:
        added = entry["meta"]["added"]
        mark = "has the sentence" if context_of(entry) else "no sentence either"
        print(
            f"{str(entry['meta']['word']):<24} added {added}  "
            f"({(ref - added).days}d)  {mark}"
        )
    print(f"\n{len(entries)} note(s) to write, and out of the review queue until written.")
    return 0


def cmd_review(args) -> int:
    entry = find_note(args.word)
    meta, body, path = entry["meta"], entry["body"], entry["path"]

    apply_review(meta, args.result)
    write_note(path, meta, body)
    srs = meta["srs"]
    print(f"{meta['word']}: {args.result} -> level {srs['level']}, next due {srs['due']}")
    return 0


def cmd_quiz_status(args) -> int:
    pending = parse_pending()
    if pending is None:
        print("No round open. Write quizzes/pending.md to start one.")
        return 0

    questions = pending["questions"]
    answered = [q for q in questions if q["answer"]]
    print(f"round {pending['round'] or '(unnamed)'}  asked {pending['asked']}")
    for question in questions:
        state = "answered" if question["answer"] else "blank"
        print(f"  {question['n']}. {question['word']:<20} {question['format']:<14} {state}")
    print(f"\n{len(answered)}/{len(questions)} answered")

    problems = pending_problems(pending)
    if problems:
        print("\nproblems with this round:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    if questions and len(answered) == len(questions):
        print("Ready to grade:  python scripts/vocab.py quiz answers")
    return 0


def cmd_quiz_answers(args) -> int:
    pending = parse_pending()
    if pending is None:
        raise SystemExit("error: no round is open (quizzes/pending.md does not exist)")

    payload = {
        "round": pending["round"],
        "asked": pending["asked"].isoformat() if pending["asked"] else None,
        "answered": pending["answered"].isoformat() if pending["answered"] else None,
        "questions": [
            {
                "n": q["n"],
                "word": q["word"],
                "format": q["format"],
                "question": q["question"],
                "answer": q["answer"],
            }
            for q in pending["questions"]
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def archive_path(day: dt.date) -> Path:
    return QUIZZES_DIR / f"{day.isoformat()}.md"


def cmd_quiz_close(args) -> int:
    """Record a whole round: every srs block, the archive entry, then the file."""
    pending = parse_pending()
    if pending is None:
        raise SystemExit("error: no round is open (quizzes/pending.md does not exist)")

    problems = pending_problems(pending)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        raise SystemExit("error: fix quizzes/pending.md before closing the round")

    results: dict[str, str] = {}
    for pair in args.results:
        word, sep, result = pair.rpartition("=")
        if not sep or result not in ("correct", "wrong"):
            raise SystemExit(
                f"error: expected <word>=correct or <word>=wrong, got '{pair}'"
            )
        results[slugify(word)] = result

    questions = pending["questions"]
    asked_slugs = [slugify(q["word"]) for q in questions]
    missing = [q["word"] for q in questions if slugify(q["word"]) not in results]
    if missing:
        raise SystemExit(
            "error: no result given for " + ", ".join(missing) + "\n"
            "       a round goes into the archive whole or not at all"
        )
    unexpected = sorted(set(results) - set(asked_slugs))
    if unexpected:
        raise SystemExit(
            "error: these were not in this round: " + ", ".join(unexpected)
        )

    # An unanswered question marked correct is a slip, not a judgement, and it
    # would quietly push the word out to a longer interval than it has earned.
    wrongly_credited = [
        q["word"] for q in questions
        if not q["answer"] and results[slugify(q["word"])] == "correct"
    ]
    if wrongly_credited:
        raise SystemExit(
            "error: nothing was answered for " + ", ".join(wrongly_credited) + ", so it\n"
            "       cannot be correct. Record it as wrong, or reopen the round."
        )
    blank = [q["word"] for q in questions if not q["answer"]]
    if blank:
        print(f"note: recording {', '.join(blank)} with no answer given", file=sys.stderr)

    # Resolve every note before touching any of them, so a typo cannot leave a
    # round half recorded.
    plan = [(q, find_note(q["word"]), results[slugify(q["word"])]) for q in questions]

    day = today()
    path = archive_path(day)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    round_number = existing.count("\n## Round ") + existing.startswith("## Round ") + 1

    blocks = [f"## Round {round_number} — {dt.datetime.now().strftime('%H:%M')}\n"]
    tally = {"correct": 0, "wrong": 0}

    for question, entry, result in plan:
        before, after = apply_review(entry["meta"], result)
        write_note(entry["path"], entry["meta"], entry["body"])
        tally[result] += 1
        due = entry["meta"]["srs"]["due"]
        when = "明天再考" if result == "wrong" else f"{SRS_INTERVALS[after]} 天后（{due}）"
        blocks.append(
            f"### {question['n']}. {question['word']}  ·  {question['format'].title()}\n"
            f"**Q** {question['question']}\n"
            f"**A** {question['answer'] or '(没有作答)'}\n"
            f"**评** <!-- 补上讲评：为什么对/错，搭配、语域、词义偏移 -->\n"
            f"`level {before} → {after}，{when}`\n"
        )

    blocks.append(f"---\n**本轮**：{tally['correct']} correct / {tally['wrong']} wrong\n")

    QUIZZES_DIR.mkdir(parents=True, exist_ok=True)
    header = "" if existing else f"# {day.isoformat()}\n\n"
    separator = "\n" if existing and not existing.endswith("\n\n") else ""
    path.write_text(existing + header + separator + "\n".join(blocks), encoding="utf-8")

    pending["path"].unlink()

    for question, entry, result in plan:
        srs = entry["meta"]["srs"]
        print(f"{question['word']}: {result} -> level {srs['level']}, next due {srs['due']}")
    print(f"\narchived round {round_number} to {path.relative_to(ROOT)}")
    print("The **评** lines are placeholders — write the grading into that file.")
    return 0


def cmd_stats(args) -> int:
    ref = today()
    entries = load_all()
    if not entries:
        print("No words yet. Add one with: python scripts/vocab.py new <word>")
        return 0

    ready = [e for e in entries if not is_unwritten(e)]
    waiting = len(entries) - len(ready)
    due_count = sum(1 for e in ready if overdue_days(e, ref) >= 0)
    recent = sum(1 for e in entries if (ref - e["meta"]["added"]).days < 7)
    correct = sum(e["meta"]["srs"]["correct"] for e in entries)
    wrong = sum(e["meta"]["srs"]["wrong"] for e in entries)
    reviewed = sum(1 for e in entries if e["meta"]["srs"]["last_reviewed"])

    print(f"words          {len(entries)}")
    if waiting:
        print(f"no note yet    {waiting}  (python scripts/vocab.py inbox)")
    print(f"due today      {due_count}")
    print(f"added <7d      {recent}")
    print(f"ever reviewed  {reviewed}")
    if correct + wrong:
        print(f"accuracy       {correct}/{correct + wrong} ({correct * 100 // (correct + wrong)}%)")
    else:
        print("accuracy       no reviews yet")

    print("\nfamiliarity")
    counts = [0] * (MAX_LEVEL + 1)
    for entry in entries:
        counts[entry["meta"]["srs"]["level"]] += 1
    for level, count in enumerate(counts):
        bar = "#" * count
        print(f"  lvl {level} ({SRS_INTERVALS[level]:>3}d)  {count:>3} {bar}")

    tags: dict[str, int] = {}
    for entry in entries:
        for tag in entry["meta"]["tags"]:
            tags[str(tag)] = tags.get(str(tag), 0) + 1
    if tags:
        print("\ntags")
        for tag, count in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {tag:<20} {count}")
    return 0


def cmd_validate(args) -> int:
    errors: list[str] = []
    warnings: list[str] = []
    unwritten = 0

    paths = note_paths()
    if not paths:
        print("no word files found in words/ - nothing to validate")
        return 0

    seen: dict[str, Path] = {}
    for path in paths:
        rel = path.relative_to(ROOT)
        try:
            raw_meta, body = parse_note(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel}: {exc}")
            continue

        for field in ("word", "added", "srs"):
            if field not in raw_meta:
                errors.append(f"{rel}: missing required frontmatter field '{field}'")

        word = str(raw_meta.get("word") or "").strip()
        if not word:
            errors.append(f"{rel}: 'word' is empty")
        elif slugify(word) != path.stem:
            errors.append(
                f"{rel}: word '{word}' should live in words/{slugify(word)}.md"
            )

        if word:
            key = slugify(word)
            if key in seen:
                errors.append(f"{rel}: duplicate of {seen[key].relative_to(ROOT)}")
            else:
                seen[key] = path

        for field in ("added",):
            try:
                if as_date(raw_meta.get(field)) is None:
                    errors.append(f"{rel}: '{field}' is missing or empty")
            except ValueError:
                errors.append(f"{rel}: '{field}' is not a valid ISO date: {raw_meta.get(field)!r}")

        srs = raw_meta.get("srs")
        if srs is not None and not isinstance(srs, dict):
            errors.append(f"{rel}: 'srs' must be a mapping")
        elif isinstance(srs, dict):
            for field in SRS_FIELDS:
                if field not in srs:
                    warnings.append(f"{rel}: srs is missing '{field}' (will default)")
            try:
                level = int(srs.get("level") or 0)
                if not 0 <= level <= MAX_LEVEL:
                    errors.append(f"{rel}: srs.level {level} outside 0..{MAX_LEVEL}")
            except (TypeError, ValueError):
                errors.append(f"{rel}: srs.level is not an integer: {srs.get('level')!r}")
            for field in ("due", "last_reviewed"):
                try:
                    as_date(srs.get(field))
                except ValueError:
                    errors.append(f"{rel}: srs.{field} is not a valid ISO date: {srs.get(field)!r}")
            for field in ("correct", "wrong"):
                try:
                    if int(srs.get(field) or 0) < 0:
                        errors.append(f"{rel}: srs.{field} must not be negative")
                except (TypeError, ValueError):
                    errors.append(f"{rel}: srs.{field} is not an integer: {srs.get(field)!r}")

        tags = raw_meta.get("tags")
        if tags is not None and not isinstance(tags, (list, str)):
            errors.append(f"{rel}: 'tags' must be a list")

        # Only the required sections are checked. The optional ones are depth,
        # and nagging about six headings nobody asked for is how the warnings
        # stop being read at all.
        sections = split_sections(body)
        ever_reviewed = bool(isinstance(srs, dict) and srs.get("last_reviewed"))
        if not clean_section(sections.get("Definition", "")) and not ever_reviewed:
            # A capture, not a half-finished note. It is *meant* to be empty at
            # this point, so it gets counted once at the end rather than
            # producing two warnings per word every time CI runs.
            unwritten += 1
        else:
            for name in REQUIRED_SECTIONS:
                if name not in sections:
                    warnings.append(f"{rel}: no '## {name}' section")
                elif not clean_section(sections[name]):
                    warnings.append(f"{rel}: '{name}' is still empty")

    # An open round is checked too. It is written by hand on one machine and
    # parsed on two others, so a malformed heading should fail here rather than
    # turn into a question that silently never reaches the phone.
    pending = None
    try:
        pending = parse_pending()
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        errors.append(f"quizzes/pending.md: {exc}")
    if pending is not None:
        errors.extend(f"quizzes/pending.md: {p}" for p in pending_problems(pending))

    for message in warnings:
        print(f"warning: {message}")
    for message in errors:
        print(f"error: {message}", file=sys.stderr)

    print(
        f"\nchecked {len(paths)} file(s): {len(errors)} error(s), {len(warnings)} warning(s)"
    )
    if unwritten:
        print(
            f"{unwritten} of them are captures waiting for a definition "
            f"(python scripts/vocab.py inbox)"
        )
    return 1 if errors else 0


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vocab.py", description="Manage the vocabulary notes in words/."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="create a new word note from the template")
    p_new.add_argument("word", help="the headword, e.g. serendipity or 'give up'")
    p_new.add_argument("--pos", default="", help="part of speech, e.g. noun")
    p_new.add_argument("--pronunciation", default="", help="IPA, e.g. /ËŒsÉ›rÉ™nËˆdÉªpÉªti/")
    p_new.add_argument("--tags", default="", help="comma separated tags")
    p_new.add_argument(
        "--full",
        action="store_true",
        help="lay out the optional sections too, instead of just the required two",
    )
    p_new.add_argument("--force", action="store_true", help="overwrite an existing file")
    p_new.set_defaults(func=cmd_new)

    p_due = sub.add_parser("due", help="list words due for review")
    p_due.add_argument("--limit", type=int, default=0, help="show at most N words")
    p_due.add_argument(
        "--fill",
        action="store_true",
        help="if fewer than --limit are due, top up with the least recently reviewed",
    )
    p_due.add_argument("--json", action="store_true", help="machine readable output")
    p_due.set_defaults(func=cmd_due)

    p_inbox = sub.add_parser("inbox", help="words captured but not yet written up")
    p_inbox.add_argument("--json", action="store_true", help="machine readable output")
    p_inbox.set_defaults(func=cmd_inbox)

    p_review = sub.add_parser("review", help="record a review result")
    p_review.add_argument("word", help="the headword to update")
    p_review.add_argument(
        "--result", required=True, choices=("correct", "wrong"), help="review outcome"
    )
    p_review.set_defaults(func=cmd_review)

    p_quiz = sub.add_parser("quiz", help="the round currently out for answering")
    quiz_sub = p_quiz.add_subparsers(dest="quiz_command", required=True)

    q_status = quiz_sub.add_parser("status", help="is a round open, and is it answered yet")
    q_status.set_defaults(func=cmd_quiz_status)

    q_answers = quiz_sub.add_parser(
        "answers", help="the round as JSON, for grading (questions and answers)"
    )
    q_answers.set_defaults(func=cmd_quiz_answers)

    q_close = quiz_sub.add_parser(
        "close", help="record the whole round: every srs block, the archive, then pending.md"
    )
    q_close.add_argument(
        "results",
        nargs="+",
        metavar="WORD=correct|wrong",
        help="one for every question in the round",
    )
    q_close.set_defaults(func=cmd_quiz_close)

    p_stats = sub.add_parser("stats", help="summarise the collection")
    p_stats.set_defaults(func=cmd_stats)

    p_validate = sub.add_parser("validate", help="check every word file")
    p_validate.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
