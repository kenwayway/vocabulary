/**
 * Shared helpers for the note-writing API.
 *
 * The rules here mirror scripts/vocab.py exactly — the slug a note lives under,
 * the frontmatter key order, the YAML quoting. A file written from the phone
 * has to be indistinguishable from one written by `vocab.py new`, or
 * `vocab.py validate` will reject it on the next push.
 *
 * Nothing in this file is routed: Pages only invokes Functions for the paths
 * listed in site/_routes.json.
 */

// Mirrors FRONTMATTER_RE in vocab.py.
const FRONTMATTER_RE = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*\r?\n?([\s\S]*)$/;

const SRS_FIELDS = ["level", "due", "last_reviewed", "correct", "wrong"];

// --------------------------------------------------------------------------
// note text
// --------------------------------------------------------------------------

/** Turn a headword into a filename stem: 'give up' -> 'give-up'. */
export function slugify(word) {
  return String(word || "")
    .normalize("NFKD")
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, "-")
    .replace(/[^a-z0-9\-']/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Split a note into its raw frontmatter text and its Markdown body. */
export function splitNote(raw) {
  const match = FRONTMATTER_RE.exec(raw);
  if (!match) return null;
  return { frontmatter: match[1], body: match[2] };
}

/** Reassemble a note. Matches write_note() in vocab.py, trailing newline and all. */
export function joinNote(frontmatter, body) {
  return `---\n${frontmatter}\n---\n\n${String(body).replace(/^\n+/, "")}`;
}

/**
 * Serialise a string the way dump_frontmatter would.
 *
 * Plain (unquoted) whenever that is unambiguous, so diffs keep looking like the
 * ones vocab.py produces. Anything that YAML 1.1 would read as a bool, a null
 * or a number gets quoted — a headword really can be `no` or `on`.
 */
const PLAIN_SAFE = /^[A-Za-z][A-Za-z0-9 '\-]*$/;
const RESERVED = /^(y|yes|n|no|true|false|on|off|null|none|~)$/i;

export function yamlString(value) {
  const text = String(value == null ? "" : value);
  if (text === "") return "''";
  if (PLAIN_SAFE.test(text) && !RESERVED.test(text) && !/\s$/.test(text)) return text;
  return `'${text.replace(/'/g, "''")}'`;
}

export function yamlList(values) {
  if (!values || !values.length) return "[]";
  return `[${values.map(yamlString).join(", ")}]`;
}

/** Build the frontmatter block for a brand new note, in META_ORDER. */
export function newFrontmatter(fields, todayIso) {
  return [
    `word: ${yamlString(fields.word)}`,
    `pos: ${yamlString(fields.pos)}`,
    `pronunciation: ${yamlString(fields.pronunciation)}`,
    `tags: ${yamlList(fields.tags)}`,
    `added: ${todayIso}`,
    "srs:",
    // A brand new word is due immediately so it turns up in the next quiz.
    `  level: 0`,
    `  due: ${todayIso}`,
    `  last_reviewed: null`,
    `  correct: 0`,
    `  wrong: 0`,
  ].join("\n");
}

/** Read the headword out of a frontmatter block without a full YAML parser. */
export function readWord(frontmatter) {
  const match = /^word:[ \t]*(.*)$/m.exec(frontmatter || "");
  if (!match) return "";
  let value = match[1].trim();
  if (/^'.*'$/.test(value)) return value.slice(1, -1).replace(/''/g, "'");
  if (/^".*"$/.test(value)) return value.slice(1, -1).replace(/\\"/g, '"');
  return value;
}

/**
 * Drop the sentence the word was met in into the '## In the wild' section.
 *
 * The template leaves a bare '>' for the quote and a bare '—' for the source;
 * fill those in place rather than appending, so the section keeps its shape.
 */
export function fillInTheWild(body, sentence, source) {
  if (!sentence && !source) return body;
  const lines = body.split("\n");
  let inSection = false;
  let quoteDone = false;
  let sourceDone = false;

  for (let i = 0; i < lines.length; i++) {
    const heading = /^##\s+(.*?)\s*$/.exec(lines[i]);
    if (heading) {
      if (inSection) break;
      inSection = heading[1] === "In the wild";
      continue;
    }
    if (!inSection) continue;
    const stripped = lines[i].trim();
    if (!quoteDone && stripped === ">" && sentence) {
      lines[i] = `> ${sentence}`;
      quoteDone = true;
    } else if (!sourceDone && stripped === "—" && source) {
      lines[i] = `— ${source}`;
      sourceDone = true;
    }
  }
  return lines.join("\n");
}

// --------------------------------------------------------------------------
// the pending round
// --------------------------------------------------------------------------

/*
 * Mirrors parse_pending / ANSWER_MARKER in vocab.py. A round is set on a laptop
 * and answered on a phone, and the split is the '**A**' line: above it is the
 * question and belongs to whoever set it, below it is the answer. This side
 * only ever rewrites what is below — same discipline as the note editor, which
 * only ever rewrites the body.
 */
const QUIZ_HEADING_RE = /^##\s+(\d+)\.\s+(.+?)\s*·\s*(compose|infer|discriminate)\s*$/i;
const ANSWER_MARKER = "**A**";

/**
 * Split a pending round into its questions, answers and the lines between.
 *
 * Splits on either line ending. getFile already normalises what comes back from
 * GitHub, but a helper that leaves a stray '\r' on every line when handed a CRLF
 * file is a trap, and it would show up as the phone silently rewording the
 * question it was asked.
 */
export function parsePending(body) {
  const lines = String(body).split(/\r?\n/);
  const questions = [];
  let current = null;
  let inAnswer = false;

  lines.forEach((line, i) => {
    const heading = QUIZ_HEADING_RE.exec(line);
    if (heading) {
      current = {
        n: Number(heading[1]),
        word: heading[2].trim(),
        format: heading[3].toLowerCase(),
        question: [],
        // Where this question's answer lives, as a half open line range.
        answerStart: -1,
        answerEnd: -1,
      };
      questions.push(current);
      inAnswer = false;
      return;
    }
    if (!current) return;
    if (line.trim() === ANSWER_MARKER) {
      inAnswer = true;
      current.answerStart = i + 1;
      current.answerEnd = i + 1;
      return;
    }
    if (inAnswer) current.answerEnd = i + 1;
    else current.question.push(line);
  });

  return questions.map((q) => ({
    n: q.n,
    word: q.word,
    format: q.format,
    question: q.question.join("\n").trim(),
    answer: q.answerStart < 0 ? "" : lines.slice(q.answerStart, q.answerEnd).join("\n").trim(),
    answerStart: q.answerStart,
    answerEnd: q.answerEnd,
  }));
}

/**
 * Rewrite only the answer slots, leaving every other byte alone.
 *
 * Splices from the bottom up so the earlier ranges stay valid as the line count
 * changes underneath them.
 */
export function writeAnswers(body, questions, answers) {
  const lines = String(body).split(/\r?\n/);
  for (let i = questions.length - 1; i >= 0; i--) {
    const q = questions[i];
    const answer = String(answers[i] == null ? "" : answers[i]).replace(/\r\n/g, "\n").trim();
    if (q.answerStart < 0) continue;
    lines.splice(q.answerStart, q.answerEnd - q.answerStart, ...(answer ? answer.split("\n") : []));
  }
  return lines.join("\n");
}

/**
 * Stamp `answered:` in the frontmatter.
 *
 * The one place the web side touches frontmatter, and deliberately: without it
 * a rebuilt page cannot tell an unanswered round from a finished one. It writes
 * nothing else, and never touches a note's frontmatter at all.
 */
export function stampAnswered(frontmatter, dayIso) {
  if (/^answered:/m.test(frontmatter)) {
    return frontmatter.replace(/^answered:.*$/m, `answered: ${dayIso}`);
  }
  return `${frontmatter.replace(/\s+$/, "")}\nanswered: ${dayIso}`;
}

// --------------------------------------------------------------------------
// dates
// --------------------------------------------------------------------------

/**
 * Today's date where the owner actually is.
 *
 * A Worker runs in UTC, so without this a word added at 08:00 in Shanghai would
 * be filed under yesterday and come up due a day early.
 */
export function todayIso(env) {
  const zone = (env && env.TIMEZONE) || "Asia/Shanghai";
  // en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

// --------------------------------------------------------------------------
// base64 / hashing
// --------------------------------------------------------------------------

export function encodeBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  // Chunked: String.fromCharCode blows the stack on a long enough note.
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

export function decodeBase64(value) {
  const binary = atob(String(value).replace(/\s/g, ""));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

/** Hex SHA-256, used to tell whether the body changed under the editor. */
export async function sha256(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// --------------------------------------------------------------------------
// GitHub contents API
// --------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(status, message, extra) {
    super(message);
    this.status = status;
    this.extra = extra || {};
  }
}

function repo(env) {
  if (!env.GITHUB_REPO) {
    throw new ApiError(503, "GITHUB_REPO is not configured on this deployment.");
  }
  return env.GITHUB_REPO;
}

function branch(env) {
  return env.GITHUB_BRANCH || "main";
}

async function github(env, path, init) {
  if (!env.GITHUB_TOKEN) {
    throw new ApiError(503, "GITHUB_TOKEN is not configured on this deployment.");
  }
  const response = await fetch(`https://api.github.com/repos/${repo(env)}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "vocabulary-notebook",
      "Content-Type": "application/json",
      ...((init && init.headers) || {}),
    },
  });
  return response;
}

function contentsPath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

/** Fetch a file, or null when it does not exist. */
export async function getFile(env, path) {
  const url = `/contents/${contentsPath(path)}?ref=${encodeURIComponent(branch(env))}`;
  const response = await github(env, url, { method: "GET" });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new ApiError(502, `GitHub refused to read ${path} (${response.status}).`);
  }
  const data = await response.json();
  if (data.type !== "file" || typeof data.content !== "string") {
    throw new ApiError(502, `${path} is not a regular file.`);
  }
  // Blobs are LF (vocab.py writes '\n' and git normalises on commit), but
  // normalise anyway so a stray CRLF file can never produce mixed endings when
  // joinNote reassembles it.
  return { sha: data.sha, text: decodeBase64(data.content).replace(/\r\n/g, "\n") };
}

/**
 * Commit a file. Pass `sha` to update, omit it to create.
 *
 * GitHub rejects a stale sha with 409, which is the backstop against two
 * writers racing between our read and our write.
 */
export async function putFile(env, path, text, message, sha) {
  const payload = {
    message,
    content: encodeBase64(text),
    branch: branch(env),
  };
  if (sha) payload.sha = sha;

  const response = await github(env, `/contents/${contentsPath(path)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });

  if (response.status === 409 || response.status === 422) {
    throw new ApiError(409, "The file changed on the server while you were editing.");
  }
  if (!response.ok) {
    throw new ApiError(502, `GitHub refused to write ${path} (${response.status}).`);
  }
  const data = await response.json();
  return { sha: data.content && data.content.sha, commit: data.commit && data.commit.sha };
}

// --------------------------------------------------------------------------

export function json(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

/** Turn a thrown ApiError into a response; anything else is a 500. */
export function fail(error) {
  if (error instanceof ApiError) {
    return json(error.status, { error: error.message, ...error.extra });
  }
  return json(500, { error: "Unexpected error handling the request." });
}

export { SRS_FIELDS };
