from __future__ import annotations

import json
import shutil
from pathlib import Path

import fitz

import ab


ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
ASSETS_DIR = DOCS_DIR / "assets" / "questions"
DATA_DIR = DOCS_DIR / "data"


STATIC_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Road Sign Practice</title>
  <style>
    :root {
      --bg: #f4f6f8;
      --panel: #ffffff;
      --ink: #1f2933;
      --muted: #64748b;
      --line: #d8dee6;
      --accent: #2563eb;
      --good: #147d4f;
      --good-bg: #e7f7ef;
      --bad: #b42318;
      --bad-bg: #fff1f0;
      --shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
    }

    button, select, input { font: inherit; }

    button {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--ink);
      cursor: pointer;
      min-height: 42px;
      padding: 0 16px;
    }

    button:disabled { cursor: not-allowed; opacity: 0.55; }

    select {
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--ink);
      padding: 0 12px;
    }

    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 24px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }

    h1 {
      margin: 0;
      font-size: 22px;
      line-height: 1.2;
    }

    .subtle {
      color: var(--muted);
      font-size: 14px;
      line-height: 1.35;
      margin: 4px 0 0;
    }

    .scorebox {
      display: grid;
      grid-template-columns: repeat(3, minmax(72px, 1fr));
      gap: 8px;
      min-width: 260px;
    }

    .scorebox div {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 10px;
      text-align: center;
      background: #fbfcfe;
    }

    .scorebox span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 3px;
    }

    .scorebox strong { font-size: 18px; }

    .shell {
      display: grid;
      grid-template-columns: 300px minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
      max-width: 1220px;
      margin: 0 auto;
    }

    .controls, .viewer {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }

    .controls {
      padding: 16px;
      align-self: start;
    }

    .mode-tabs {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
      margin-bottom: 16px;
    }

    .mode-tabs button {
      text-align: left;
      font-weight: 700;
    }

    .mode-tabs button.active {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }

    .field {
      display: grid;
      gap: 6px;
      margin-bottom: 12px;
    }

    .field label {
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }

    .primary {
      width: 100%;
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      font-weight: 700;
    }

    .progress {
      margin-top: 16px;
      border-top: 1px solid var(--line);
      padding-top: 14px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }

    .viewer {
      min-width: 0;
      padding: 18px;
    }

    .question-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 14px;
      margin-bottom: 16px;
    }

    .question-title {
      margin: 0;
      font-size: 18px;
      line-height: 1.3;
    }

    .question-meta {
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }

    .pdf-frame {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #f9fafb;
      overflow: auto;
      min-height: 310px;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding: 10px;
    }

    .pdf-frame img {
      display: block;
      width: min(100%, 920px);
      height: auto;
      background: #fff;
    }

    .answer-form {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 16px;
    }

    .option {
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 54px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      background: #fbfcfe;
      font-weight: 700;
      cursor: pointer;
    }

    .option input {
      width: 18px;
      height: 18px;
      margin: 0;
    }

    .option:has(input:checked) {
      border-color: var(--accent);
      box-shadow: inset 0 0 0 1px var(--accent);
    }

    .actions {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-top: 14px;
    }

    .feedback {
      border-radius: 8px;
      padding: 12px 14px;
      margin-top: 14px;
      font-weight: 700;
    }

    .feedback.correct {
      background: var(--good-bg);
      color: var(--good);
      border: 1px solid rgba(20, 125, 79, 0.25);
    }

    .feedback.wrong {
      background: var(--bad-bg);
      color: var(--bad);
      border: 1px solid rgba(180, 35, 24, 0.25);
    }

    .empty {
      display: grid;
      place-items: center;
      min-height: 460px;
      color: var(--muted);
      text-align: center;
      line-height: 1.5;
      padding: 24px;
    }

    [hidden] { display: none !important; }

    @media (max-width: 840px) {
      .topbar {
        align-items: stretch;
        flex-direction: column;
      }

      .scorebox { min-width: 0; }
      .shell {
        grid-template-columns: 1fr;
        padding: 12px;
      }
      .answer-form { grid-template-columns: 1fr; }
      .question-head { flex-direction: column; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div>
      <h1>Road Sign Practice</h1>
      <p class="subtle" id="bank-count">Loading question bank...</p>
    </div>
    <div class="scorebox" aria-label="Current score">
      <div><span>Correct</span><strong id="score-correct">0</strong></div>
      <div><span>Answered</span><strong id="score-answered">0</strong></div>
      <div><span>Total</span><strong id="score-total">0</strong></div>
    </div>
  </header>

  <main class="shell">
    <aside class="controls">
      <div class="mode-tabs" role="tablist" aria-label="Practice mode">
        <button type="button" data-mode="random" class="active">Random</button>
        <button type="button" data-mode="questionnaire">Questionnaire</button>
        <button type="button" data-mode="mistakes">Mistakes</button>
      </div>

      <div id="questionnaire-controls" hidden>
        <div class="field">
          <label for="test-select">PDF</label>
          <select id="test-select"></select>
        </div>
        <div class="field">
          <label for="set-select">Questionnaire</label>
          <select id="set-select"></select>
        </div>
      </div>

      <button type="button" class="primary" id="start-button">Start</button>

      <div class="progress">
        <div id="mode-label">Random practice</div>
        <div id="position-label">Question 0 of 0</div>
        <div id="status-label"></div>
      </div>
    </aside>

    <section class="viewer">
      <div id="question-view">
        <div class="question-head">
          <div>
            <h2 class="question-title" id="question-title">Question</h2>
            <div class="question-meta" id="question-meta"></div>
          </div>
        </div>

        <div class="pdf-frame">
          <img id="question-image" alt="Question screenshot from PDF">
        </div>

        <form class="answer-form" id="answer-form">
          <label class="option"><input type="radio" name="answer" value="1"> Option 1</label>
          <label class="option"><input type="radio" name="answer" value="2"> Option 2</label>
          <label class="option"><input type="radio" name="answer" value="3"> Option 3</label>
        </form>

        <div class="feedback" id="feedback" hidden></div>

        <div class="actions">
          <button type="button" id="submit-button" disabled>Submit</button>
          <button type="button" id="next-button" disabled>Next</button>
        </div>
      </div>

      <div class="empty" id="empty-view" hidden>
        <div id="empty-message">Choose a mode to begin.</div>
      </div>
    </section>
  </main>

  <script>
    const STORAGE_KEY = "road-sign-practice-history-v1";

    const app = {
      mode: "random",
      questions: [],
      questionById: new Map(),
      tests: [],
      sequence: [],
      index: 0,
      answered: false,
      score: { correct: 0, answered: 0 }
    };

    const els = {
      bankCount: document.getElementById("bank-count"),
      scoreCorrect: document.getElementById("score-correct"),
      scoreAnswered: document.getElementById("score-answered"),
      scoreTotal: document.getElementById("score-total"),
      modeButtons: Array.from(document.querySelectorAll("[data-mode]")),
      questionnaireControls: document.getElementById("questionnaire-controls"),
      testSelect: document.getElementById("test-select"),
      setSelect: document.getElementById("set-select"),
      startButton: document.getElementById("start-button"),
      modeLabel: document.getElementById("mode-label"),
      positionLabel: document.getElementById("position-label"),
      statusLabel: document.getElementById("status-label"),
      questionView: document.getElementById("question-view"),
      emptyView: document.getElementById("empty-view"),
      emptyMessage: document.getElementById("empty-message"),
      questionTitle: document.getElementById("question-title"),
      questionMeta: document.getElementById("question-meta"),
      questionImage: document.getElementById("question-image"),
      answerForm: document.getElementById("answer-form"),
      feedback: document.getElementById("feedback"),
      submitButton: document.getElementById("submit-button"),
      nextButton: document.getElementById("next-button")
    };

    function shuffle(values) {
      const copy = values.slice();
      for (let i = copy.length - 1; i > 0; i -= 1) {
        const j = Math.floor(Math.random() * (i + 1));
        [copy[i], copy[j]] = [copy[j], copy[i]];
      }
      return copy;
    }

    function sortedQuestions(questions) {
      return questions.slice().sort((a, b) => {
        return (
          a.test.localeCompare(b.test) ||
          a.questionnaire - b.questionnaire ||
          a.question - b.question
        );
      });
    }

    function loadHistory() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : [];
      } catch {
        return [];
      }
    }

    function saveAttempt(question, selectedAnswer, isCorrect) {
      const history = loadHistory();
      history.push({
        timestamp: new Date().toISOString(),
        mode: app.mode,
        question_id: question.id,
        test: question.test,
        questionnaire: question.questionnaire,
        question: question.question,
        description: question.description,
        selected_answer: selectedAnswer,
        correct_answer: question.correct_answer,
        result: isCorrect ? "correct" : "wrong"
      });
      localStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-1000)));
    }

    function latestMistakeIds() {
      const ids = [];
      const seen = new Set();
      for (const row of loadHistory().reverse()) {
        if (row.result !== "wrong" || seen.has(row.question_id)) {
          continue;
        }
        if (app.questionById.has(row.question_id)) {
          seen.add(row.question_id);
          ids.push(row.question_id);
        }
      }
      return ids;
    }

    function updateScore() {
      els.scoreCorrect.textContent = app.score.correct;
      els.scoreAnswered.textContent = app.score.answered;
      els.scoreTotal.textContent = app.sequence.length;
    }

    function setMode(mode) {
      app.mode = mode;
      els.modeButtons.forEach((button) => {
        button.classList.toggle("active", button.dataset.mode === mode);
      });
      els.questionnaireControls.hidden = mode !== "questionnaire";
      els.modeLabel.textContent = {
        random: "Random practice",
        questionnaire: "Questionnaire practice",
        mistakes: "Mistakes review"
      }[mode];
      startSession();
    }

    function populateSelectors() {
      els.testSelect.innerHTML = "";
      app.tests.forEach((test) => {
        const option = document.createElement("option");
        option.value = test.name;
        option.textContent = test.name;
        els.testSelect.appendChild(option);
      });
      populateSetSelect();
    }

    function populateSetSelect() {
      const selectedTest = app.tests.find((test) => test.name === els.testSelect.value);
      els.setSelect.innerHTML = "";
      if (!selectedTest) return;
      selectedTest.questionnaires.forEach((setNo) => {
        const option = document.createElement("option");
        option.value = String(setNo);
        option.textContent = `Questionnaire ${setNo}`;
        els.setSelect.appendChild(option);
      });
    }

    function startSession() {
      app.score = { correct: 0, answered: 0 };
      app.index = 0;
      app.answered = false;
      els.statusLabel.textContent = "";

      if (app.mode === "random") {
        app.sequence = shuffle(app.questions.map((question) => question.id));
      } else if (app.mode === "questionnaire") {
        const testName = els.testSelect.value;
        const setNo = Number(els.setSelect.value);
        app.sequence = sortedQuestions(
          app.questions.filter(
            (question) => question.test === testName && question.questionnaire === setNo
          )
        ).map((question) => question.id);
      } else {
        app.sequence = latestMistakeIds();
      }

      updateScore();
      renderCurrent();
    }

    function showEmpty(message) {
      els.questionView.hidden = true;
      els.emptyView.hidden = false;
      els.emptyMessage.textContent = message;
      els.positionLabel.textContent = "Question 0 of 0";
      els.statusLabel.textContent = "";
      updateScore();
    }

    function selectedAnswer() {
      const checked = els.answerForm.querySelector("input[name='answer']:checked");
      return checked ? checked.value : "";
    }

    function resetAnswerControls() {
      app.answered = false;
      els.answerForm.reset();
      els.answerForm.querySelectorAll("input").forEach((input) => {
        input.disabled = false;
      });
      els.feedback.hidden = true;
      els.feedback.className = "feedback";
      els.feedback.textContent = "";
      els.submitButton.disabled = true;
      els.nextButton.disabled = true;
      els.nextButton.textContent = "Next";
    }

    function renderCurrent() {
      if (!app.sequence.length) {
        const message =
          app.mode === "mistakes"
            ? "No saved mistakes yet in this browser."
            : "No questions found for this selection.";
        showEmpty(message);
        return;
      }

      const question = app.questionById.get(app.sequence[app.index]);
      if (!question) {
        showEmpty("Question not found.");
        return;
      }

      els.questionView.hidden = false;
      els.emptyView.hidden = true;
      els.questionTitle.textContent = question.description;
      els.questionMeta.textContent =
        `${question.test} | Questionnaire ${question.questionnaire} | ` +
        `Q${question.question} | Page ${question.page_number}`;
      els.questionImage.src = question.image_url;
      els.positionLabel.textContent = `Question ${app.index + 1} of ${app.sequence.length}`;
      els.statusLabel.textContent = "";
      resetAnswerControls();
      updateScore();
    }

    function submitAnswer() {
      if (app.answered) return;
      const answer = selectedAnswer();
      if (!answer) return;

      const question = app.questionById.get(app.sequence[app.index]);
      const isCorrect = answer === question.correct_answer;
      saveAttempt(question, answer, isCorrect);

      app.answered = true;
      app.score.answered += 1;
      if (isCorrect) app.score.correct += 1;

      els.feedback.hidden = false;
      els.feedback.classList.add(isCorrect ? "correct" : "wrong");
      els.feedback.textContent = isCorrect
        ? `Correct. Actual answer: ${question.correct_answer}.`
        : `Wrong. Actual answer: ${question.correct_answer}.`;

      els.answerForm.querySelectorAll("input").forEach((input) => {
        input.disabled = true;
      });
      els.submitButton.disabled = true;
      els.nextButton.disabled = false;
      els.nextButton.textContent =
        app.index + 1 >= app.sequence.length ? "Summary" : "Next";
      updateScore();
    }

    function showSummary() {
      els.questionView.hidden = true;
      els.emptyView.hidden = false;
      const percent = app.score.answered
        ? Math.round((app.score.correct / app.score.answered) * 100)
        : 0;
      els.emptyMessage.textContent =
        `Finished: ${app.score.correct}/${app.score.answered} correct (${percent}%).`;
      els.positionLabel.textContent = `Question ${app.sequence.length} of ${app.sequence.length}`;
      els.statusLabel.textContent = "Press Start for another round.";
      updateScore();
    }

    function nextQuestion() {
      if (app.index + 1 >= app.sequence.length) {
        showSummary();
        return;
      }
      app.index += 1;
      renderCurrent();
    }

    async function init() {
      const response = await fetch("./data/questions.json");
      const data = await response.json();
      app.questions = sortedQuestions(data.questions);
      app.questions.forEach((question) => app.questionById.set(question.id, question));
      app.tests = data.tests;
      els.bankCount.textContent =
        `${app.questions.length} questions extracted from ${app.tests.length} PDFs`;
      populateSelectors();
      startSession();
    }

    els.modeButtons.forEach((button) => {
      button.addEventListener("click", () => setMode(button.dataset.mode));
    });
    els.testSelect.addEventListener("change", () => {
      populateSetSelect();
      if (app.mode === "questionnaire") startSession();
    });
    els.setSelect.addEventListener("change", () => {
      if (app.mode === "questionnaire") startSession();
    });
    els.startButton.addEventListener("click", startSession);
    els.answerForm.addEventListener("change", () => {
      if (!app.answered) {
        els.submitButton.disabled = !selectedAnswer();
      }
    });
    els.submitButton.addEventListener("click", submitAnswer);
    els.nextButton.addEventListener("click", nextQuestion);

    init().catch((error) => {
      showEmpty(error.message);
      els.bankCount.textContent = "Could not load question bank";
    });
  </script>
</body>
</html>
"""


def question_payload(question: ab.Question) -> dict[str, object]:
    return {
        "id": question.question_id,
        "test": question.test,
        "questionnaire": question.questionnaire,
        "question": question.question,
        "description": question.description,
        "correct_answer": question.correct_answer,
        "page_number": question.page_number,
        "image_url": f"./assets/questions/{question.question_id}.png",
    }


def write_question_image(question: ab.Question) -> None:
    output_path = ASSETS_DIR / f"{question.question_id}.png"
    with fitz.open(question.pdf_path) as doc:
        page = doc[question.page_index]
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(2.2, 2.2),
            clip=fitz.Rect(question.crop),
            alpha=False,
        )
        pixmap.save(output_path)


def build_static_site() -> None:
    state = ab.create_state()
    if DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for question_id in state.ordered_ids:
        write_question_image(state.questions[question_id])

    payload = {
        "questions": [
            question_payload(state.questions[question_id])
            for question_id in state.ordered_ids
        ],
        "tests": state.tests,
        "total": len(state.questions),
    }

    (DOCS_DIR / "index.html").write_text(STATIC_HTML, encoding="utf-8")
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (DATA_DIR / "questions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Built static site at {DOCS_DIR}")
    print(f"Questions: {len(state.questions)}")


if __name__ == "__main__":
    build_static_site()
