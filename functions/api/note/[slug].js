/**
 * GET  /api/note/<slug> — the raw Markdown body, for the editor.
 * PUT  /api/note/<slug> — write a new body back.
 *
 * The body only. Frontmatter is never accepted from the client and never sent
 * back for editing: `vocab.py review` owns the srs block, and a phone holding a
 * stale copy of the whole file would silently undo a review recorded while the
 * editor was open. Instead the current frontmatter is re-read at save time and
 * carried over untouched, so the two writers can never collide.
 */

import {
  ApiError,
  fail,
  getFile,
  json,
  joinNote,
  putFile,
  readWord,
  sha256,
  slugify,
  splitNote,
} from "../../_lib/notes.js";

const MAX_BODY = 200000;

async function load(env, slug) {
  const clean = slugify(slug);
  if (!clean || clean !== String(slug)) {
    throw new ApiError(400, "That is not a valid note name.");
  }
  const path = `words/${clean}.md`;
  const file = await getFile(env, path);
  if (!file) throw new ApiError(404, "No note with that name.");

  const parsed = splitNote(file.text);
  if (!parsed) {
    throw new ApiError(500, `${path} has no frontmatter block; fix it by hand.`);
  }
  return { slug: clean, path, file, parsed };
}

export async function onRequestGet(context) {
  try {
    const { slug, parsed } = await load(context.env, context.params.slug);
    return json(200, {
      slug,
      word: readWord(parsed.frontmatter),
      body: parsed.body,
      bodyHash: await sha256(parsed.body),
    });
  } catch (error) {
    return fail(error);
  }
}

export async function onRequestPut(context) {
  const { request, env, params, data } = context;

  try {
    let payload;
    try {
      payload = await request.json();
    } catch {
      throw new ApiError(400, "Expected a JSON body.");
    }

    if (typeof payload.body !== "string") {
      throw new ApiError(400, "A body is required.");
    }
    const body = payload.body.replace(/\r\n/g, "\n");
    if (body.length > MAX_BODY) {
      throw new ApiError(400, "That note is too long.");
    }
    // A body starting with '---' would parse back as a second frontmatter block.
    if (/^\s*---/.test(body)) {
      throw new ApiError(400, "A note body cannot start with '---'.");
    }

    const { slug, path, file, parsed } = await load(env, params.slug);

    // Compare only the body. A review that landed while the editor was open
    // changed the frontmatter, and that must not read as a conflict.
    const currentHash = await sha256(parsed.body);
    if (payload.baseBodyHash && payload.baseBodyHash !== currentHash) {
      throw new ApiError(409, "This note was edited somewhere else since you opened it.", {
        conflict: true,
        body: parsed.body,
        bodyHash: currentHash,
      });
    }

    const next = joinNote(parsed.frontmatter, body);
    if (next === file.text) {
      return json(200, { slug, unchanged: true, bodyHash: currentHash });
    }

    const word = readWord(parsed.frontmatter) || slug;
    const author = (data.identity && data.identity.email) || "web";
    await putFile(env, path, next, `note: edit ${word} (${author})`, file.sha);

    // Hash what a subsequent GET would see, not what the client sent: joinNote
    // normalises the leading newlines, and a hash of the un-normalised text
    // would make the very next save look like a conflict.
    return json(200, { slug, unchanged: false, bodyHash: await sha256(splitNote(next).body) });
  } catch (error) {
    return fail(error);
  }
}
