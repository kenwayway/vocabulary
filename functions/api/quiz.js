/**
 * GET /api/quiz — the open round's questions, and whatever has been answered.
 * PUT /api/quiz — write answers back.
 *
 * The answers only. A round is set at a keyboard and answered on a phone, and
 * the two writers never touch the same bytes: questions and frontmatter are
 * re-read at save time and carried over untouched, exactly as the note editor
 * carries a note's frontmatter over. The one exception is `answered:`, which
 * this endpoint stamps so a rebuilt page can tell a finished round from an open
 * one — see stampAnswered.
 *
 * Grading stays on the laptop. Nothing here judges an answer.
 */

import {
  ApiError,
  fail,
  getFile,
  json,
  joinNote,
  parsePending,
  putFile,
  sha256,
  splitNote,
  stampAnswered,
  todayIso,
  writeAnswers,
} from "../_lib/notes.js";

const PENDING_PATH = "quizzes/pending.md";
const MAX_ANSWER = 20000;

async function load(env) {
  const file = await getFile(env, PENDING_PATH);
  if (!file) return null;
  const parsed = splitNote(file.text);
  if (!parsed) {
    throw new ApiError(500, `${PENDING_PATH} has no frontmatter block; fix it by hand.`);
  }
  return { file, parsed, questions: parsePending(parsed.body) };
}

function shape(questions) {
  return questions.map((q) => ({
    n: q.n,
    word: q.word,
    format: q.format,
    question: q.question,
    answer: q.answer,
  }));
}

export async function onRequestGet(context) {
  try {
    const round = await load(context.env);
    if (!round) return json(200, { pending: false });

    return json(200, {
      pending: true,
      questions: shape(round.questions),
      // Hashing the answers alone: a question reworded on the laptop while the
      // phone had the page open is not a conflict with what was typed.
      answersHash: await sha256(JSON.stringify(round.questions.map((q) => q.answer))),
    });
  } catch (error) {
    return fail(error);
  }
}

export async function onRequestPut(context) {
  const { request, env, data } = context;

  try {
    let payload;
    try {
      payload = await request.json();
    } catch {
      throw new ApiError(400, "Expected a JSON body.");
    }
    if (!Array.isArray(payload.answers)) {
      throw new ApiError(400, "An array of answers is required.");
    }

    const round = await load(env);
    if (!round) throw new ApiError(404, "There is no round open right now.");

    if (payload.answers.length !== round.questions.length) {
      throw new ApiError(
        409,
        `This round has ${round.questions.length} questions, but ${payload.answers.length} answers arrived. Reload the page.`
      );
    }

    const answers = payload.answers.map((a) => String(a == null ? "" : a));
    if (answers.some((a) => a.length > MAX_ANSWER)) {
      throw new ApiError(400, "That answer is too long.");
    }

    const currentHash = await sha256(JSON.stringify(round.questions.map((q) => q.answer)));
    if (payload.baseAnswersHash && payload.baseAnswersHash !== currentHash) {
      throw new ApiError(409, "These answers were changed somewhere else since you opened them.", {
        conflict: true,
        questions: shape(round.questions),
        answersHash: currentHash,
      });
    }

    const body = writeAnswers(round.parsed.body, round.questions, answers);
    const answeredAny = answers.some((a) => a.trim());
    const frontmatter = answeredAny
      ? stampAnswered(round.parsed.frontmatter, todayIso(env))
      : round.parsed.frontmatter;

    const next = joinNote(frontmatter, body);
    const nextQuestions = parsePending(splitNote(next).body);
    const nextHash = await sha256(JSON.stringify(nextQuestions.map((q) => q.answer)));

    if (next === round.file.text) {
      return json(200, { unchanged: true, answersHash: nextHash });
    }

    const author = (data.identity && data.identity.email) || "web";
    await putFile(env, PENDING_PATH, next, `quiz: answers (${author})`, round.file.sha);

    return json(200, { unchanged: false, answersHash: nextHash });
  } catch (error) {
    return fail(error);
  }
}
