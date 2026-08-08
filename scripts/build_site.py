#!/usr/bin/env python3
"""Build the browsable site from words/*.md.

Produces a single self contained ``site/index.html`` with the note data
inlined as JSON. No network requests at runtime, so the page keeps working
offline once the phone has loaded it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
from pathlib import Path

from vocab import (
    MAX_LEVEL,
    ROOT,
    SRS_INTERVALS,
    load_all,
    split_sections,
    today,
)

OUTPUT_DIR = ROOT / "site"

COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BARE_URL_RE = re.compile(r"(?<!href=\")(?<!\">)(https?://[^\s<>\"]+)")
CODE_RE = re.compile(r"`([^`]+)`")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")


# --------------------------------------------------------------------------
# a deliberately small Markdown subset: enough for the note template
# --------------------------------------------------------------------------


SAFE_SCHEMES = ("http://", "https://", "mailto:", "#", "/")


def link(url: str, label: str) -> str:
    """Build an anchor from text that has *already* been HTML escaped.

    Escaping the URL again here would turn an existing ``&amp;`` into
    ``&amp;amp;`` and break the link, so only the quote character still needs
    handling for the attribute.
    """
    if not url.lower().startswith(SAFE_SCHEMES):
        return label
    href = url.replace('"', "&quot;")
    return f'<a href="{href}" target="_blank" rel="noopener">{label}</a>'


def render_inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)
    out = ITALIC_RE.sub(lambda m: f"<em>{m.group(1)}</em>", out)
    out = LINK_RE.sub(lambda m: link(m.group(2), m.group(1)), out)
    out = BARE_URL_RE.sub(lambda m: link(m.group(1), m.group(1)), out)
    return out


def render_markdown(text: str) -> str:
    """Render blockquotes, bullet lists and paragraphs. Comments are dropped."""
    text = COMMENT_RE.sub("", text or "")
    lines = [line.rstrip() for line in text.splitlines()]

    blocks: list[str] = []
    paragraph: list[str] = []
    bullets: list[str] = []
    quote: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{render_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_bullets() -> None:
        if bullets:
            items = "".join(f"<li>{render_inline(b)}</li>" for b in bullets)
            blocks.append(f"<ul>{items}</ul>")
            bullets.clear()

    def flush_quote() -> None:
        if quote:
            # Line breaks inside a quote come from how the note was wrapped in
            # the source file, not from the quoted text, so reflow them.
            blocks.append(f"<blockquote>{render_inline(' '.join(quote))}</blockquote>")
            quote.clear()

    def flush_all() -> None:
        flush_paragraph()
        flush_bullets()
        flush_quote()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_all()
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            flush_bullets()
            content = stripped[1:].strip()
            if content:
                quote.append(content)
            continue
        if re.match(r"^[-*]\s+", stripped):
            flush_paragraph()
            flush_quote()
            bullets.append(re.sub(r"^[-*]\s+", "", stripped))
            continue
        flush_bullets()
        flush_quote()
        paragraph.append(stripped)

    flush_all()
    return "".join(blocks)


def mask_word(text: str, word: str) -> str:
    """Blank out the headword (and its inflections) so a card can be a quiz."""
    stems = []
    for part in re.findall(r"[A-Za-z']{3,}", word or ""):
        stems.append(part[: max(3, int(len(part) * 0.65))])
    if not stems:
        return text
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(s) for s in stems) + r")[A-Za-z']*", re.IGNORECASE
    )
    pieces = []
    for token in re.split(r"(\s+)", text or ""):
        # Leave URLs alone so links survive the blanking.
        if "://" in token or token.startswith("www."):
            pieces.append(token)
        else:
            pieces.append(pattern.sub("————", token))
    return "".join(pieces)


# --------------------------------------------------------------------------


def collect() -> list[dict]:
    ref = today()
    words = []
    for entry in load_all():
        meta = entry["meta"]
        slug = entry["path"].stem
        sections = split_sections(entry["body"])
        rendered = {}
        for name, raw in sections.items():
            cleaned = COMMENT_RE.sub("", raw).strip()
            if cleaned:
                rendered[name] = render_markdown(cleaned)

        definition_raw = COMMENT_RE.sub("", sections.get("Definition", "")).strip()
        wild_raw = COMMENT_RE.sub("", sections.get("In the wild", "")).strip()
        srs = meta["srs"]

        words.append(
            {
                "word": str(meta["word"]),
                # The editor addresses notes by filename, not by headword.
                "slug": slug,
                "pos": str(meta.get("pos") or ""),
                "pronunciation": str(meta.get("pronunciation") or ""),
                "tags": [str(t) for t in meta["tags"]],
                "added": meta["added"].isoformat(),
                "level": srs["level"],
                "due": srs["due"].isoformat(),
                "lastReviewed": srs["last_reviewed"].isoformat() if srs["last_reviewed"] else None,
                "correct": srs["correct"],
                "wrong": srs["wrong"],
                "isDue": (ref - srs["due"]).days >= 0,
                "summary": re.sub(r"\s+", " ", definition_raw).strip(),
                "sections": rendered,
                "sectionOrder": [n for n in sections if n in rendered],
                # Pre-masked variants power the flashcard side of the app.
                "quizDefinition": render_markdown(mask_word(definition_raw, str(meta["word"]))),
                "quizContext": render_markdown(mask_word(wild_raw, str(meta["word"]))),
                "searchBlob": " ".join(
                    [
                        str(meta["word"]),
                        str(meta.get("pos") or ""),
                        " ".join(str(t) for t in meta["tags"]),
                        definition_raw,
                        wild_raw,
                        " ".join(sections.values()),
                    ]
                ).lower(),
            }
        )

    words.sort(key=lambda w: w["word"].lower())
    return words


def build_html(words: list[dict], api: bool = False) -> str:
    payload = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "today": today().isoformat(),
        "intervals": SRS_INTERVALS,
        "maxLevel": MAX_LEVEL,
        # Only the Cloudflare deployment serves /api/*, so the editing UI is
        # baked in there and left out of the GitHub Pages build entirely.
        "api": api,
        "words": words,
    }
    # Guard against a note body containing a literal </script>.
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__DATA__", data)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>Vocabulary</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#128218;</text></svg>">
<style>
:root {
  --bg: #fbfaf8;
  --surface: #ffffff;
  --surface-2: #f3f1ec;
  --border: #e3ded4;
  --text: #22201d;
  --muted: #6d6862;
  --accent: #9a5b2c;
  --accent-soft: #f0e4d8;
  --due: #b4541f;
  --shadow: 0 1px 2px rgba(31,27,22,.06), 0 6px 18px rgba(31,27,22,.05);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #16151a;
    --surface: #1e1d23;
    --surface-2: #26252c;
    --border: #34323b;
    --text: #eceaf0;
    --muted: #9d99a6;
    --accent: #e0a071;
    --accent-soft: #33291f;
    --due: #f0a97a;
    --shadow: 0 1px 2px rgba(0,0,0,.3), 0 6px 18px rgba(0,0,0,.25);
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 16px/1.6 ui-serif, Georgia, "Iowan Old Style", "Songti SC", serif;
  overflow-x: hidden;
}
.wrap { max-width: 860px; margin: 0 auto; padding: 0 16px 96px; }

header { padding: 28px 0 12px; }
h1 {
  margin: 0;
  font-size: 28px;
  letter-spacing: -.02em;
}
.sub { color: var(--muted); font-size: 14px; margin-top: 4px; }
.sub b { color: var(--due); font-weight: 600; }

.toolbar {
  position: sticky; top: 0; z-index: 20;
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  padding: 10px 0;
  margin: 0 -16px;
  padding-left: 16px; padding-right: 16px;
  border-bottom: 1px solid transparent;
}
.toolbar.stuck { border-bottom-color: var(--border); }
.row { display: flex; gap: 8px; align-items: center; }
input[type=search] {
  flex: 1; min-width: 0;
  font: inherit; font-size: 16px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text);
  -webkit-appearance: none;
}
input[type=search]:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
.modes { display: flex; background: var(--surface-2); border-radius: 999px; padding: 3px; flex: none; }
.modes button {
  font: inherit; font-size: 14px;
  border: 0; background: transparent; color: var(--muted);
  padding: 7px 14px; border-radius: 999px; cursor: pointer;
  white-space: nowrap;
}
.modes button[aria-pressed=true] { background: var(--surface); color: var(--text); box-shadow: var(--shadow); }

.chips { display: flex; gap: 6px; overflow-x: auto; padding: 10px 0 2px; scrollbar-width: none; }
.chips::-webkit-scrollbar { display: none; }
.chip {
  font: inherit; font-size: 13px;
  flex: none; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface);
  color: var(--muted);
  padding: 5px 12px; border-radius: 999px;
}
.chip[aria-pressed=true] { background: var(--accent-soft); border-color: var(--accent); color: var(--text); }

.cards { display: grid; gap: 10px; margin-top: 14px; }
@media (min-width: 640px) { .cards { grid-template-columns: 1fr 1fr; } }

.card {
  text-align: left; width: 100%; font: inherit; color: inherit;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px 16px;
  cursor: pointer;
  box-shadow: var(--shadow);
  display: flex; flex-direction: column; gap: 5px;
}
.card:hover { border-color: var(--accent); }
.card-top { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.card h2 { margin: 0; font-size: 19px; letter-spacing: -.01em; }
.pos { font-size: 12px; color: var(--muted); font-style: italic; }
.card p { margin: 0; font-size: 14px; color: var(--muted); line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card-foot { display: flex; align-items: center; gap: 8px; margin-top: 3px; }
.dots { display: flex; gap: 3px; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--border); }
.dot.on { background: var(--accent); }
.badge { font-size: 11px; color: var(--due); border: 1px solid currentColor;
  border-radius: 999px; padding: 1px 7px; font-family: system-ui, sans-serif; }
.tag { font-size: 11px; color: var(--muted); background: var(--surface-2);
  border-radius: 999px; padding: 1px 8px; font-family: system-ui, sans-serif; }

.empty { text-align: center; color: var(--muted); padding: 60px 20px; font-size: 15px; }
.empty code { background: var(--surface-2); padding: 2px 6px; border-radius: 4px; font-size: 13px; }

/* ---- detail sheet ---- */
.sheet {
  position: fixed; inset: 0; z-index: 50;
  background: rgba(0,0,0,.4);
  display: flex; align-items: flex-end; justify-content: center;
  opacity: 0; pointer-events: none; transition: opacity .18s;
}
.sheet.open { opacity: 1; pointer-events: auto; }
.sheet-inner {
  background: var(--bg);
  width: 100%; max-width: 720px;
  max-height: 92vh; overflow-y: auto;
  border-radius: 18px 18px 0 0;
  padding: 0 20px calc(32px + env(safe-area-inset-bottom));
  transform: translateY(14px); transition: transform .18s;
  -webkit-overflow-scrolling: touch;
}
.sheet.open .sheet-inner { transform: none; }
@media (min-width: 700px) {
  .sheet { align-items: center; }
  .sheet-inner { border-radius: 18px; max-height: 84vh; }
}
.sheet-bar {
  position: sticky; top: 0; background: var(--bg);
  padding: 14px 0 10px; display: flex; justify-content: space-between;
  align-items: flex-start; gap: 12px; border-bottom: 1px solid var(--border);
}
.sheet-bar h2 { margin: 0; font-size: 26px; letter-spacing: -.02em; }
.ipa { font-size: 13px; color: var(--muted); font-family: system-ui, sans-serif; }
.close {
  flex: none; font: inherit; cursor: pointer; line-height: 1;
  border: 1px solid var(--border); background: var(--surface); color: var(--muted);
  border-radius: 50%; width: 32px; height: 32px; font-size: 18px;
}
.meta-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 12px 0 4px; }
section h3 {
  font-size: 12px; text-transform: uppercase; letter-spacing: .09em;
  color: var(--accent); margin: 22px 0 6px; font-family: system-ui, sans-serif; font-weight: 600;
}
section p { margin: 0 0 8px; }
section ul { margin: 0 0 8px; padding-left: 20px; }
section li { margin-bottom: 5px; }
blockquote {
  margin: 0 0 8px; padding: 10px 14px;
  border-left: 3px solid var(--accent);
  background: var(--surface-2); border-radius: 0 8px 8px 0;
  font-style: italic;
}
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em; }
a { color: var(--accent); }
.stat-line { font-size: 12px; color: var(--muted); font-family: system-ui, sans-serif;
  border-top: 1px solid var(--border); margin-top: 26px; padding-top: 12px; }

/* ---- flashcards ---- */
.deck { margin-top: 18px; }
.flash {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 16px; box-shadow: var(--shadow);
  padding: 26px 22px; min-height: 320px;
  display: flex; flex-direction: column;
}
.flash-label { font-size: 11px; text-transform: uppercase; letter-spacing: .09em;
  color: var(--muted); font-family: system-ui, sans-serif; margin-bottom: 14px; }
.flash-body { flex: 1; }
.flash-body p { margin: 0 0 10px; }
.flash-answer { font-size: 30px; letter-spacing: -.02em; margin: 0 0 2px; }
.blank, .flash-body em.blank { color: var(--accent); }
.flash-actions { display: flex; gap: 8px; margin-top: 20px; }
.btn {
  font: inherit; font-size: 15px; cursor: pointer; flex: 1;
  padding: 12px 16px; border-radius: 11px;
  border: 1px solid var(--border); background: var(--surface-2); color: var(--text);
}
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--bg); }
.tally { text-align: center; font-size: 13px; color: var(--muted);
  font-family: system-ui, sans-serif; margin-top: 14px; }
.note { font-size: 12px; color: var(--muted); font-family: system-ui, sans-serif;
  text-align: center; margin-top: 8px; line-height: 1.5; }

/* ---- writing ---- */
.fab {
  position: fixed; right: 18px; z-index: 30;
  bottom: calc(18px + env(safe-area-inset-bottom));
  width: 54px; height: 54px; border-radius: 50%;
  border: 0; background: var(--accent); color: var(--bg);
  font-size: 30px; line-height: 1; cursor: pointer;
  box-shadow: 0 4px 16px rgba(31,27,22,.28);
}
.field { margin: 14px 0; }
.field label {
  display: block; font-size: 12px; text-transform: uppercase; letter-spacing: .09em;
  color: var(--accent); font-family: system-ui, sans-serif; font-weight: 600; margin-bottom: 5px;
}
.field .hint { text-transform: none; letter-spacing: 0; color: var(--muted); font-weight: 400; }
.field input, .field textarea {
  width: 100%; font: inherit; font-size: 16px;
  padding: 10px 12px; border-radius: 10px;
  border: 1px solid var(--border); background: var(--surface); color: var(--text);
  -webkit-appearance: none;
}
.field textarea { resize: vertical; line-height: 1.55; }
.field input:focus, .field textarea:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
#editor-body {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 14px; min-height: 58vh;
}
.form-actions { display: flex; gap: 8px; margin-top: 20px; }
.status {
  font-size: 13px; font-family: system-ui, sans-serif;
  margin-top: 12px; padding: 10px 12px; border-radius: 10px;
  background: var(--surface-2); color: var(--muted); line-height: 1.5;
}
.status.bad { color: var(--due); border: 1px solid currentColor; background: transparent; }
.status[hidden] { display: none; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Vocabulary</h1>
    <div class="sub" id="subtitle"></div>
  </header>

  <div class="toolbar" id="toolbar">
    <div class="row">
      <input type="search" id="q" placeholder="Search words, definitions, notes…" autocomplete="off">
      <div class="modes">
        <button id="mode-browse" aria-pressed="true">Browse</button>
        <button id="mode-cards" aria-pressed="false">Cards</button>
      </div>
    </div>
    <div class="chips" id="chips"></div>
  </div>

  <div id="browse"><div class="cards" id="cards"></div></div>
  <div id="deck" class="deck" hidden></div>
</div>

<button class="fab" id="add" hidden aria-label="Add a word">+</button>

<div class="sheet" id="sheet" role="dialog" aria-modal="true">
  <div class="sheet-inner" id="sheet-inner"></div>
</div>

<div class="sheet" id="form-sheet" role="dialog" aria-modal="true">
  <div class="sheet-inner" id="form-inner"></div>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("data").textContent);
  var WORDS = DATA.words;

  var state = { query: "", filter: "all", mode: "browse", deck: [], idx: 0, revealed: false, hit: 0, miss: 0 };

  var el = {
    subtitle: document.getElementById("subtitle"),
    q: document.getElementById("q"),
    chips: document.getElementById("chips"),
    cards: document.getElementById("cards"),
    browse: document.getElementById("browse"),
    deck: document.getElementById("deck"),
    sheet: document.getElementById("sheet"),
    sheetInner: document.getElementById("sheet-inner"),
    formSheet: document.getElementById("form-sheet"),
    formInner: document.getElementById("form-inner"),
    add: document.getElementById("add"),
    toolbar: document.getElementById("toolbar"),
    modeBrowse: document.getElementById("mode-browse"),
    modeCards: document.getElementById("mode-cards")
  };

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var dueCount = WORDS.filter(function (w) { return w.isDue; }).length;
  el.subtitle.innerHTML = WORDS.length + " words · " +
    (dueCount ? "<b>" + dueCount + " due for review</b>" : "nothing due today") +
    " · built " + esc(DATA.generated);

  // ---- filters -----------------------------------------------------------
  var tags = {};
  WORDS.forEach(function (w) { w.tags.forEach(function (t) { tags[t] = (tags[t] || 0) + 1; }); });
  var tagNames = Object.keys(tags).sort(function (a, b) { return tags[b] - tags[a] || a.localeCompare(b); });

  var filters = [
    { id: "all", label: "All " + WORDS.length },
    { id: "due", label: "Due " + dueCount },
    { id: "recent", label: "Recent" },
    { id: "weak", label: "Weakest" }
  ].concat(tagNames.map(function (t) { return { id: "tag:" + t, label: t }; }));

  filters.forEach(function (f) {
    var b = document.createElement("button");
    b.className = "chip";
    b.textContent = f.label;
    b.setAttribute("aria-pressed", f.id === state.filter);
    b.addEventListener("click", function () {
      state.filter = f.id;
      Array.prototype.forEach.call(el.chips.children, function (c) { c.setAttribute("aria-pressed", "false"); });
      b.setAttribute("aria-pressed", "true");
      render();
    });
    el.chips.appendChild(b);
  });

  function visible() {
    var q = state.query.trim().toLowerCase();
    var list = WORDS.filter(function (w) {
      if (q && w.searchBlob.indexOf(q) === -1) return false;
      if (state.filter === "due") return w.isDue;
      if (state.filter === "recent" || state.filter === "weak" || state.filter === "all") return true;
      if (state.filter.indexOf("tag:") === 0) return w.tags.indexOf(state.filter.slice(4)) !== -1;
      return true;
    });
    if (state.filter === "recent") {
      list = list.slice().sort(function (a, b) { return b.added.localeCompare(a.added) || a.word.localeCompare(b.word); });
    } else if (state.filter === "weak") {
      list = list.slice().sort(function (a, b) {
        return a.level - b.level || b.wrong - a.wrong || a.word.localeCompare(b.word);
      });
    }
    return list;
  }

  // ---- browse ------------------------------------------------------------
  function dots(level) {
    var out = "";
    for (var i = 0; i <= DATA.maxLevel; i++) out += '<span class="dot' + (i < level ? " on" : "") + '"></span>';
    return '<span class="dots" title="familiarity ' + level + "/" + DATA.maxLevel + '">' + out + "</span>";
  }

  function renderCards(list) {
    if (!list.length) {
      el.cards.innerHTML = '<div class="empty">Nothing here yet.<br><br>' +
        'Add a word with <code>python scripts/vocab.py new &lt;word&gt;</code>, ' +
        'fill in the note, and push.</div>';
      return;
    }
    el.cards.innerHTML = "";
    list.forEach(function (w) {
      var b = document.createElement("button");
      b.className = "card";
      b.innerHTML =
        '<div class="card-top"><h2>' + esc(w.word) + "</h2>" +
        (w.pos ? '<span class="pos">' + esc(w.pos) + "</span>" : "") + "</div>" +
        (w.summary ? "<p>" + esc(w.summary) + "</p>" : '<p><em>no definition yet</em></p>') +
        '<div class="card-foot">' + dots(w.level) +
        (w.isDue ? '<span class="badge">due</span>' : "") +
        w.tags.map(function (t) { return '<span class="tag">' + esc(t) + "</span>"; }).join("") +
        "</div>";
      b.addEventListener("click", function () { openSheet(w); });
      el.cards.appendChild(b);
    });
  }

  // ---- detail sheet ------------------------------------------------------
  function openSheet(w) {
    var parts = w.sectionOrder.map(function (name) {
      return "<section><h3>" + esc(name) + "</h3>" + w.sections[name] + "</section>";
    }).join("");

    el.sheetInner.innerHTML =
      '<div class="sheet-bar"><div><h2>' + esc(w.word) + "</h2>" +
      (w.pronunciation ? '<div class="ipa">' + esc(w.pronunciation) + "</div>" : "") +
      "</div><div class=\"row\">" +
      (DATA.api ? '<button class="chip" id="edit-note">Edit</button>' : "") +
      '<button class="close" aria-label="Close">&times;</button></div></div>' +
      '<div class="meta-row">' + dots(w.level) +
      (w.isDue ? '<span class="badge">due</span>' : "") +
      (w.pos ? '<span class="tag">' + esc(w.pos) + "</span>" : "") +
      w.tags.map(function (t) { return '<span class="tag">' + esc(t) + "</span>"; }).join("") +
      "</div>" + parts +
      '<div class="stat-line">added ' + esc(w.added) +
      " · next review " + esc(w.due) +
      " · level " + w.level + "/" + DATA.maxLevel +
      (w.correct + w.wrong ? " · " + w.correct + " right / " + w.wrong + " wrong" : " · never quizzed") +
      "</div>";

    el.sheetInner.querySelector(".close").addEventListener("click", closeSheet);
    var edit = document.getElementById("edit-note");
    if (edit) edit.addEventListener("click", function () { openEditor(w.slug, w.word); });
    el.sheet.classList.add("open");
    el.sheetInner.scrollTop = 0;
    document.body.style.overflow = "hidden";
  }

  function closeSheet() {
    el.sheet.classList.remove("open");
    document.body.style.overflow = "";
  }

  el.sheet.addEventListener("click", function (e) { if (e.target === el.sheet) closeSheet(); });
  document.addEventListener("keydown", function (e) {
    var editing = el.formSheet.classList.contains("open");
    if (e.key === "Escape") {
      // Close the topmost layer only.
      if (editing) closeForm(); else closeSheet();
      return;
    }
    if (state.mode === "cards" && !editing && !el.sheet.classList.contains("open")) {
      if (e.key === " " || e.key === "Enter") { e.preventDefault(); flashPrimary(); }
    }
  });

  // ---- flashcards --------------------------------------------------------
  function shuffle(a) {
    a = a.slice();
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }

  function startDeck() {
    state.deck = shuffle(visible());
    state.idx = 0; state.revealed = false; state.hit = 0; state.miss = 0;
    renderDeck();
  }

  function flashPrimary() {
    if (!state.revealed) { state.revealed = true; renderDeck(); }
  }

  function answer(ok) {
    if (ok) state.hit++; else state.miss++;
    state.idx++; state.revealed = false;
    renderDeck();
  }

  function renderDeck() {
    var total = state.deck.length;
    if (!total) {
      el.deck.innerHTML = '<div class="empty">No words match this filter.</div>';
      return;
    }
    if (state.idx >= total) {
      el.deck.innerHTML =
        '<div class="flash"><div class="flash-label">Round complete</div>' +
        '<div class="flash-body"><p class="flash-answer">' + state.hit + " / " + total + "</p>" +
        "<p>" + (state.miss ? state.miss + " to come back to." : "Clean sweep.") + "</p></div>" +
        '<div class="flash-actions"><button class="btn primary" id="again">Go again</button></div></div>' +
        '<div class="note">This tally is just for this round and is not saved.<br>' +
        "Real review progress is recorded when Claude quizzes you.</div>";
      document.getElementById("again").addEventListener("click", startDeck);
      return;
    }

    var w = state.deck[state.idx];
    var front = w.quizDefinition || w.quizContext ||
      "<p><em>This note has no definition yet — flip to see the word.</em></p>";
    var body, actions;

    if (!state.revealed) {
      body = '<div class="flash-label">What word is this? · ' + (state.idx + 1) + " / " + total + "</div>" +
        '<div class="flash-body">' + front +
        (w.quizContext && w.quizDefinition ? w.quizContext : "") + "</div>";
      actions = '<button class="btn primary" id="reveal">Reveal</button>';
    } else {
      var extra = w.sections["Synonyms &amp; nuance"] || w.sections["Synonyms & nuance"] || "";
      body = '<div class="flash-label">' + (state.idx + 1) + " / " + total + "</div>" +
        '<div class="flash-body"><p class="flash-answer">' + esc(w.word) + "</p>" +
        (w.pronunciation ? '<div class="ipa">' + esc(w.pronunciation) + "</div>" : "") +
        (w.sections["Definition"] || "") +
        (w.sections["In the wild"] || "") + extra + "</div>";
      actions = '<button class="btn" id="miss">Forgot</button>' +
        '<button class="btn primary" id="hit">Knew it</button>';
    }

    el.deck.innerHTML = '<div class="flash">' + body +
      '<div class="flash-actions">' + actions + "</div></div>" +
      '<div class="tally">' + state.hit + " known · " + state.miss + " forgotten</div>" +
      '<div class="note">Tap the card text to open the full note.</div>';

    var reveal = document.getElementById("reveal");
    if (reveal) reveal.addEventListener("click", flashPrimary);
    var hit = document.getElementById("hit");
    if (hit) hit.addEventListener("click", function () { answer(true); });
    var miss = document.getElementById("miss");
    if (miss) miss.addEventListener("click", function () { answer(false); });
    el.deck.querySelector(".flash-body").addEventListener("click", function () { openSheet(w); });
  }

  // ---- writing -----------------------------------------------------------
  // Present only on the Cloudflare deployment, where /api/* is served by a
  // Function that commits to the repository. The static build has DATA.api
  // false and none of this is reachable.

  function request(path, options) {
    return fetch(path, Object.assign({
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin"
    }, options || {})).then(function (res) {
      var type = res.headers.get("Content-Type") || "";
      var expired = "Your session expired. Reload the page to sign in again.";

      // An expired Access session is answered with the login page, not with an
      // error status. Anything that is not JSON means we never reached the
      // Function, so it must never be read as a successful empty response.
      if (type.indexOf("application/json") === -1) {
        throw Object.assign(new Error(expired), { status: res.status, payload: {} });
      }

      return res.json().catch(function () { return {}; }).then(function (payload) {
        if (res.ok) return payload;
        var message = payload.error ||
          (res.status === 401 || res.status === 403
            ? expired
            : "Could not reach the server (" + res.status + ").");
        throw Object.assign(new Error(message), { status: res.status, payload: payload });
      });
    });
  }

  function openForm(html) {
    el.formInner.innerHTML = html;
    el.formInner.querySelector(".close").addEventListener("click", closeForm);
    el.formSheet.classList.add("open");
    el.formInner.scrollTop = 0;
    document.body.style.overflow = "hidden";
  }

  function closeForm() {
    el.formSheet.classList.remove("open");
    // The detail sheet may still be underneath.
    if (!el.sheet.classList.contains("open")) document.body.style.overflow = "";
  }

  el.formSheet.addEventListener("click", function (e) { if (e.target === el.formSheet) closeForm(); });

  function setStatus(text, bad) {
    var box = document.getElementById("form-status");
    if (!box) return;
    box.hidden = !text;
    box.className = "status" + (bad ? " bad" : "");
    box.innerHTML = text || "";
  }

  function bar(title) {
    return '<div class="sheet-bar"><div><h2>' + esc(title) + "</h2></div>" +
      '<button class="close" aria-label="Close">&times;</button></div>';
  }

  function field(id, label, hint, tag, attrs) {
    return '<div class="field"><label for="' + id + '">' + esc(label) +
      (hint ? ' <span class="hint">' + esc(hint) + "</span>" : "") + "</label>" +
      (tag === "textarea"
        ? '<textarea id="' + id + '" ' + (attrs || "") + "></textarea>"
        : '<input id="' + id + '" ' + (attrs || "") + ">") + "</div>";
  }

  // ---- add ---------------------------------------------------------------
  function openAdd() {
    openForm(
      bar("New word") +
      field("f-word", "Headword", "", "input", 'autocapitalize="none" autocomplete="off"') +
      field("f-wild", "In the wild", "the sentence you met it in", "textarea", 'rows="3"') +
      field("f-source", "Source", "where it came from", "input", 'autocomplete="off"') +
      field("f-pos", "Part of speech", "optional", "input", 'autocomplete="off"') +
      field("f-ipa", "Pronunciation", "optional", "input", 'autocomplete="off"') +
      field("f-tags", "Tags", "comma separated", "input", 'autocapitalize="none" autocomplete="off"') +
      '<div class="form-actions"><button class="btn" id="f-cancel">Cancel</button>' +
      '<button class="btn primary" id="f-save">Add</button></div>' +
      '<div class="status" id="form-status" hidden></div>' +
      '<div class="note">The rest of the note is written in the editor that opens next.</div>'
    );

    document.getElementById("f-cancel").addEventListener("click", closeForm);
    var save = document.getElementById("f-save");
    save.addEventListener("click", function () {
      var word = document.getElementById("f-word").value.trim();
      if (!word) { setStatus("A headword is required.", true); return; }
      save.disabled = true;
      setStatus("Saving…");
      request("/api/note", {
        method: "POST",
        body: JSON.stringify({
          word: word,
          wild: document.getElementById("f-wild").value,
          source: document.getElementById("f-source").value,
          pos: document.getElementById("f-pos").value,
          pronunciation: document.getElementById("f-ipa").value,
          tags: document.getElementById("f-tags").value
        })
      }).then(function (res) {
        openEditor(res.slug, res.word);
      }).catch(function (err) {
        save.disabled = false;
        setStatus(esc(err.message), true);
      });
    });
    document.getElementById("f-word").focus();
  }

  // ---- edit --------------------------------------------------------------
  // Drafts survive the phone killing the tab mid-sentence.
  function draftKey(slug) { return "vocab-draft:" + slug; }

  function readDraft(slug) {
    try { return window.localStorage.getItem(draftKey(slug)); } catch (e) { return null; }
  }

  function writeDraft(slug, text) {
    try {
      if (text === null) window.localStorage.removeItem(draftKey(slug));
      else window.localStorage.setItem(draftKey(slug), text);
    } catch (e) { /* private mode, or the quota is full; not worth surfacing */ }
  }

  function openEditor(slug, word) {
    openForm(bar(word || slug) + '<div class="status" id="form-status">Loading…</div>');

    request("/api/note/" + encodeURIComponent(slug)).then(function (note) {
      var base = note.bodyHash;
      openForm(
        bar(note.word || slug) +
        field("editor-body", "Note", "Markdown, ## headings", "textarea",
          'spellcheck="false" autocapitalize="sentences"') +
        '<div class="form-actions"><button class="btn" id="e-cancel">Close</button>' +
        '<button class="btn primary" id="e-save">Save</button></div>' +
        '<div class="status" id="form-status" hidden></div>' +
        '<div class="note">Saved straight to the repository. The page here updates ' +
        "after the rebuild, about a minute later.</div>"
      );

      var box = document.getElementById("editor-body");
      box.value = note.body;

      var draft = readDraft(slug);
      if (draft !== null && draft !== note.body) {
        setStatus('An unsaved draft from this device is different from what is on the ' +
          'server. <button class="chip" id="e-draft">Restore the draft</button>');
        document.getElementById("e-draft").addEventListener("click", function () {
          box.value = draft;
          setStatus("Draft restored. It is not saved until you press Save.");
        });
      }

      box.addEventListener("input", function () { writeDraft(slug, box.value); });
      document.getElementById("e-cancel").addEventListener("click", closeForm);

      var save = document.getElementById("e-save");
      function commit(hash) {
        save.disabled = true;
        setStatus("Saving…");
        request("/api/note/" + encodeURIComponent(slug), {
          method: "PUT",
          body: JSON.stringify({ body: box.value, baseBodyHash: hash })
        }).then(function (res) {
          base = res.bodyHash;
          save.disabled = false;
          writeDraft(slug, null);
          setStatus(res.unchanged
            ? "Nothing had changed."
            : "Saved. It shows up here after the rebuild.");
        }).catch(function (err) {
          save.disabled = false;
          if (err.status === 409 && err.payload && err.payload.conflict) {
            // Keep their text in the box either way; nothing is thrown away
            // without them pressing something.
            setStatus("This note changed elsewhere since you opened it. " +
              '<button class="chip" id="e-force">Keep mine</button> ' +
              '<button class="chip" id="e-theirs">Use the other version</button>', true);
            var theirs = err.payload.body;
            var theirHash = err.payload.bodyHash;
            document.getElementById("e-force").addEventListener("click", function () {
              commit(theirHash);
            });
            document.getElementById("e-theirs").addEventListener("click", function () {
              box.value = theirs;
              base = theirHash;
              writeDraft(slug, null);
              setStatus("Loaded the other version.");
            });
            return;
          }
          setStatus(esc(err.message), true);
        });
      }
      save.addEventListener("click", function () { commit(base); });
    }).catch(function (err) {
      setStatus(esc(err.message), true);
    });
  }

  if (DATA.api) {
    el.add.hidden = false;
    el.add.addEventListener("click", openAdd);
  }

  // ---- modes -------------------------------------------------------------
  function setMode(mode) {
    state.mode = mode;
    el.modeBrowse.setAttribute("aria-pressed", mode === "browse");
    el.modeCards.setAttribute("aria-pressed", mode === "cards");
    el.browse.hidden = mode !== "browse";
    el.deck.hidden = mode !== "cards";
    if (mode === "cards") startDeck();
  }

  el.modeBrowse.addEventListener("click", function () { setMode("browse"); });
  el.modeCards.addEventListener("click", function () { setMode("cards"); });

  el.q.addEventListener("input", function () { state.query = el.q.value; render(); });

  window.addEventListener("scroll", function () {
    el.toolbar.classList.toggle("stuck", window.scrollY > 8);
  }, { passive: true });

  function render() {
    if (state.mode === "browse") renderCards(visible());
    else startDeck();
  }

  render();
})();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build site/index.html from words/*.md")
    parser.add_argument(
        "--out", default=str(OUTPUT_DIR), help="output directory (default: site/)"
    )
    parser.add_argument(
        "--api",
        action="store_true",
        default=os.environ.get("VOCAB_API") == "1",
        help="include the add/edit UI (Cloudflare deployment only; env VOCAB_API=1)",
    )
    args = parser.parse_args()

    words = collect()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "index.html"
    out_file.write_text(build_html(words, api=args.api), encoding="utf-8")

    # Keep static assets away from the Functions runtime; without this every
    # request for the page would be billed and delayed by a Worker invocation.
    (out_dir / "_routes.json").write_text(
        json.dumps({"version": 1, "include": ["/api/*"], "exclude": []}, indent=2) + "\n",
        encoding="utf-8",
    )

    size_kb = out_file.stat().st_size / 1024
    mode = "with editing" if args.api else "read only"
    print(f"wrote {out_file} — {len(words)} word(s), {size_kb:.1f} KB, {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
