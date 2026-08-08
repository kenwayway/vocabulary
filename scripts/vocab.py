#!/usr/bin/env python3
"""Command line tool for the vocabulary note system.

Every word lives in ``words/<slug>.md`` as a Markdown file whose YAML
frontmatter holds the structured fields (part of speech, tags, spaced
repetition state) and whose body holds the hand written notes.

Subcommands:
    new       create a new word file from templates/word.md
    due       list words that are due for review
    review    record the outcome of a review and advance the SRS state
    stats     summarise the collection
    validate  check every word file for structural problems
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
TEMPLATE_PATH = ROOT / "templates" / "word.md"

# Interval in days for each familiarity level. Answering correctly moves the
# word one level up, getting it wrong drops it two levels and schedules it for
# tomorrow.
SRS_INTERVALS = [1, 3, 7, 14, 30, 60, 120]
MAX_LEVEL = len(SRS_INTERVALS) - 1

SRS_FIELDS = ("level", "due", "last_reviewed", "correct", "wrong")
META_ORDER = ("word", "pos", "pronunciation", "tags", "added", "srs")

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL)

# Sections the template defines. Missing ones are reported as warnings so that
# a half finished note never blocks the site build.
EXPECTED_SECTIONS = (
    "Definition",
    "In the wild",
    "Etymology",
    "Word family",
    "Synonyms & nuance",
    "Collocations",
    "My sentences",
    "Notes",
)


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
    return 0


def cmd_due(args) -> int:
    ref = today()
    entries = load_all()
    due = [e for e in entries if overdue_days(e, ref) >= 0]
    due.sort(key=lambda e: sort_key_for_review(e, ref))

    selected = due[: args.limit] if args.limit else due

    if args.fill and args.limit and len(selected) < args.limit:
        chosen = {e["path"] for e in selected}
        rest = [e for e in entries if e["path"] not in chosen]
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


def cmd_review(args) -> int:
    entry = find_note(args.word)
    meta, body, path = entry["meta"], entry["body"], entry["path"]
    srs = meta["srs"]

    if args.result == "correct":
        srs["level"] = min(MAX_LEVEL, srs["level"] + 1)
        srs["correct"] += 1
        srs["due"] = today() + dt.timedelta(days=SRS_INTERVALS[srs["level"]])
    else:
        srs["level"] = max(0, srs["level"] - 2)
        srs["wrong"] += 1
        srs["due"] = today() + dt.timedelta(days=1)
    srs["last_reviewed"] = today()

    write_note(path, meta, body)
    print(f"{meta['word']}: {args.result} -> level {srs['level']}, next due {srs['due']}")
    return 0


def cmd_stats(args) -> int:
    ref = today()
    entries = load_all()
    if not entries:
        print("No words yet. Add one with: python scripts/vocab.py new <word>")
        return 0

    due_count = sum(1 for e in entries if overdue_days(e, ref) >= 0)
    recent = sum(1 for e in entries if (ref - e["meta"]["added"]).days < 7)
    correct = sum(e["meta"]["srs"]["correct"] for e in entries)
    wrong = sum(e["meta"]["srs"]["wrong"] for e in entries)
    reviewed = sum(1 for e in entries if e["meta"]["srs"]["last_reviewed"])

    print(f"words          {len(entries)}")
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

        sections = split_sections(body)
        for name in EXPECTED_SECTIONS:
            if name not in sections:
                warnings.append(f"{rel}: no '## {name}' section")
        if not sections.get("Definition", "").strip():
            warnings.append(f"{rel}: 'Definition' is empty")

    for message in warnings:
        print(f"warning: {message}")
    for message in errors:
        print(f"error: {message}", file=sys.stderr)

    print(
        f"\nchecked {len(paths)} file(s): {len(errors)} error(s), {len(warnings)} warning(s)"
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
    p_new.add_argument("--pronunciation", default="", help="IPA, e.g. /ˌsɛrənˈdɪpɪti/")
    p_new.add_argument("--tags", default="", help="comma separated tags")
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

    p_review = sub.add_parser("review", help="record a review result")
    p_review.add_argument("word", help="the headword to update")
    p_review.add_argument(
        "--result", required=True, choices=("correct", "wrong"), help="review outcome"
    )
    p_review.set_defaults(func=cmd_review)

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
