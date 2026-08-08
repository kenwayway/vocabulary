/**
 * POST /api/note — create words/<slug>.md from templates/word.md.
 *
 * The equivalent of `vocab.py new`, plus the one thing that cannot wait until
 * you are back at a keyboard: the sentence you actually met the word in.
 */

import {
  ApiError,
  fail,
  fillInTheWild,
  getFile,
  json,
  joinNote,
  newFrontmatter,
  putFile,
  slugify,
  splitNote,
  todayIso,
} from "../_lib/notes.js";

const MAX_FIELD = 2000;

function text(value, label) {
  const out = String(value == null ? "" : value).replace(/\r\n/g, "\n").trim();
  if (out.length > MAX_FIELD) {
    throw new ApiError(400, `${label} is too long.`);
  }
  return out;
}

export async function onRequestPost(context) {
  const { request, env, data } = context;

  try {
    let payload;
    try {
      payload = await request.json();
    } catch {
      throw new ApiError(400, "Expected a JSON body.");
    }

    const word = text(payload.word, "The headword");
    if (!word) throw new ApiError(400, "A headword is required.");

    const slug = slugify(word);
    if (!slug) {
      throw new ApiError(400, `'${word}' does not produce a usable filename.`);
    }

    const tags = (Array.isArray(payload.tags)
      ? payload.tags
      : String(payload.tags || "").split(",")
    )
      .map((t) => String(t).trim())
      .filter(Boolean);

    const path = `words/${slug}.md`;
    if (await getFile(env, path)) {
      throw new ApiError(409, `${word} is already in the notebook.`);
    }

    const template = await getFile(env, "templates/word.md");
    if (!template) {
      throw new ApiError(500, "templates/word.md is missing from the repository.");
    }
    const parsed = splitNote(template.text);
    if (!parsed) {
      throw new ApiError(500, "templates/word.md has no frontmatter block.");
    }

    const body = fillInTheWild(
      parsed.body,
      text(payload.wild, "The sentence"),
      text(payload.source, "The source")
    );

    const frontmatter = newFrontmatter(
      {
        word,
        pos: text(payload.pos, "Part of speech"),
        pronunciation: text(payload.pronunciation, "The pronunciation"),
        tags,
      },
      todayIso(env)
    );

    const author = (data.identity && data.identity.email) || "web";
    await putFile(env, path, joinNote(frontmatter, body), `note: add ${word} (${author})`);

    return json(201, { slug, word, path });
  } catch (error) {
    return fail(error);
  }
}
