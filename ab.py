from __future__ import annotations

import csv
import json
import random
import re
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    import fitz  # PyMuPDF
except ModuleNotFoundError:
    raise SystemExit(
        "Missing dependency: PyMuPDF\n"
        "Install it with: python -m pip install pymupdf"
    )


BASE_DIR = Path(__file__).resolve().parent
PDF_GLOB = "road_sign_test*.pdf"
RESULTS_FILE = BASE_DIR / "practice_results.csv"
MISTAKES_FILE = BASE_DIR / "mistakes.csv"
QUESTION_EXPORT_FILE = BASE_DIR / "questions_with_answers.csv"
HOST = "127.0.0.1"
START_PORT = 8000
CSV_LOCK = threading.Lock()

HISTORY_FIELDS = [
    "timestamp",
    "mode",
    "question_id",
    "test",
    "questionnaire",
    "question",
    "description",
    "selected_answer",
    "correct_answer",
    "result",
]

QUESTION_EXPORT_FIELDS = [
    "question_id",
    "test",
    "questionnaire",
    "question",
    "description",
    "correct_answer",
    "page_number",
    "crop_x0",
    "crop_y0",
    "crop_x1",
    "crop_y1",
]


@dataclass(frozen=True)
class Question:
    question_id: str
    test: str
    pdf_path: Path
    questionnaire: int
    question: int
    description: str
    correct_answer: str
    page_index: int
    crop: tuple[float, float, float, float]

    @property
    def page_number(self) -> int:
        return self.page_index + 1

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.question_id,
            "test": self.test,
            "questionnaire": self.questionnaire,
            "question": self.question,
            "description": self.description,
            "page_number": self.page_number,
            "image_url": f"/image/{urllib.parse.quote(self.question_id)}.png",
        }

    def export_row(self) -> dict[str, Any]:
        x0, y0, x1, y1 = self.crop
        return {
            "question_id": self.question_id,
            "test": self.test,
            "questionnaire": self.questionnaire,
            "question": self.question,
            "description": self.description,
            "correct_answer": self.correct_answer,
            "page_number": self.page_number,
            "crop_x0": round(x0, 2),
            "crop_y0": round(y0, 2),
            "crop_x1": round(x1, 2),
            "crop_y1": round(y1, 2),
        }


@dataclass
class AppState:
    questions: dict[str, Question]
    ordered_ids: list[str]
    tests: list[dict[str, Any]]


def clean_text(value: str) -> str:
    replacements = {
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)

    value = value.replace("\n", " ")
    value = re.sub(r"\s+", " ", value).strip(" .")
    prefix = "tick the sign of"
    if value.lower().startswith(prefix):
        value = value[len(prefix) :].strip()
    return value.strip(' "')


def block_text(block: dict[str, Any]) -> str:
    lines = block.get("lines", [])
    return " ".join(
        span.get("text", "")
        for line in lines
        for span in line.get("spans", [])
    )


def make_question_id(test_name: str, questionnaire: int, question: int) -> str:
    stem = Path(test_name).stem
    stem = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").lower()
    return f"{stem}_set{questionnaire}_q{question}"


def extract_question_descriptions(doc: fitz.Document) -> dict[int, dict[int, str]]:
    questionnaires: dict[int, dict[int, str]] = {}

    for page_index in range(len(doc) - 1):
        set_no = page_index // 5 + 1
        questionnaires.setdefault(set_no, {})
        lines = [line.strip() for line in doc[page_index].get_text("text").splitlines()]
        current_q: int | None = None
        prompt_lines: list[str] = []

        def save_prompt() -> None:
            if current_q is not None and prompt_lines:
                questionnaires[set_no][current_q] = clean_text(" ".join(prompt_lines))

        for line in lines:
            q_match = re.fullmatch(r"Q(\d+):", line)
            option_match = re.fullmatch(r"\d+-", line)

            if q_match:
                save_prompt()
                current_q = int(q_match.group(1))
                prompt_lines = []
                continue

            if option_match:
                save_prompt()
                current_q = None
                prompt_lines = []
                continue

            if current_q is not None and line:
                prompt_lines.append(line)

        save_prompt()

    return questionnaires


def extract_answer_key(doc: fitz.Document) -> dict[int, dict[int, str]]:
    text = doc[-1].get_text("text")
    answer_key: dict[int, dict[int, str]] = {}
    matches = list(re.finditer(r"Questionnaire No\.\s*(\d+)", text))

    for index, match in enumerate(matches):
        set_no = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = text[start:end]
        answers = {
            int(q_no): answer
            for q_no, answer in re.findall(r"\((\d+)\)\s*(\d+)", chunk)
        }
        if answers:
            answer_key[set_no] = answers

    return answer_key


def extract_question_crops(
    doc: fitz.Document,
) -> dict[int, dict[int, dict[str, Any]]]:
    crops: dict[int, dict[int, dict[str, Any]]] = {}

    for page_index in range(len(doc) - 1):
        page = doc[page_index]
        set_no = page_index // 5 + 1
        q_labels: list[tuple[int, fitz.Rect]] = []

        for word in page.get_text("words"):
            match = re.fullmatch(r"Q(\d+):", word[4])
            if match:
                q_labels.append((int(match.group(1)), fitz.Rect(word[:4])))

        q_labels.sort(key=lambda item: (item[1].y0, item[1].x0))
        if len(q_labels) != 2:
            raise ValueError(
                f"{doc.name} page {page_index + 1}: expected 2 question labels, "
                f"found {len(q_labels)}"
            )

        page_blocks = page.get_text("dict").get("blocks", [])
        for label_index, (q_no, q_rect) in enumerate(q_labels):
            top = max(0.0, q_rect.y0 - 10.0)
            raw_bottom = (
                q_labels[label_index + 1][1].y0 - 8.0
                if label_index + 1 < len(q_labels)
                else page.rect.height - 36.0
            )
            max_bottom = q_rect.y1

            for block in page_blocks:
                bbox = fitz.Rect(block["bbox"])
                if bbox.y1 < top or bbox.y0 > raw_bottom:
                    continue
                if block.get("type") == 0 and not block_text(block).strip():
                    continue
                max_bottom = max(max_bottom, bbox.y1)

            bottom = min(raw_bottom, max_bottom + 18.0)
            bottom = max(bottom, min(raw_bottom, top + 130.0))
            crops.setdefault(set_no, {})[q_no] = {
                "page_index": page_index,
                "crop": (
                    18.0,
                    round(top, 2),
                    round(page.rect.width - 18.0, 2),
                    round(bottom, 2),
                ),
            }

    return crops


def load_question_bank() -> dict[str, Question]:
    questions: dict[str, Question] = {}
    pdf_paths = sorted(BASE_DIR.glob(PDF_GLOB))
    if not pdf_paths:
        raise SystemExit(f"No PDFs matching {PDF_GLOB} were found in {BASE_DIR}.")

    for pdf_path in pdf_paths:
        with fitz.open(pdf_path) as doc:
            descriptions = extract_question_descriptions(doc)
            answer_key = extract_answer_key(doc)
            crop_data = extract_question_crops(doc)

        for set_no in sorted(answer_key):
            for question_no in range(1, 11):
                try:
                    description = descriptions[set_no][question_no]
                    correct_answer = answer_key[set_no][question_no]
                    crop_info = crop_data[set_no][question_no]
                except KeyError as exc:
                    raise ValueError(
                        f"Missing data in {pdf_path.name}: "
                        f"questionnaire {set_no}, question {question_no}"
                    ) from exc

                question_id = make_question_id(pdf_path.name, set_no, question_no)
                questions[question_id] = Question(
                    question_id=question_id,
                    test=pdf_path.name,
                    pdf_path=pdf_path,
                    questionnaire=set_no,
                    question=question_no,
                    description=description,
                    correct_answer=correct_answer,
                    page_index=crop_info["page_index"],
                    crop=crop_info["crop"],
                )

    if len(questions) != 100:
        raise ValueError(f"Expected 100 extracted questions, found {len(questions)}.")

    return questions


def build_tests(questions: dict[str, Question]) -> list[dict[str, Any]]:
    grouped: dict[str, set[int]] = {}
    for question in questions.values():
        grouped.setdefault(question.test, set()).add(question.questionnaire)

    return [
        {"name": test, "questionnaires": sorted(questionnaires)}
        for test, questionnaires in sorted(grouped.items())
    ]


def ordered_question_ids(questions: dict[str, Question]) -> list[str]:
    return [
        question.question_id
        for question in sorted(
            questions.values(),
            key=lambda item: (item.test, item.questionnaire, item.question),
        )
    ]


def export_question_bank(questions: dict[str, Question]) -> None:
    rows = [
        questions[question_id].export_row()
        for question_id in ordered_question_ids(questions)
    ]
    with QUESTION_EXPORT_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=QUESTION_EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def normalize_history_row(row: dict[str, Any]) -> dict[str, str]:
    test_name = str(row.get("test", "") or "")
    questionnaire = str(row.get("questionnaire", "") or "")
    question = str(row.get("question", "") or "")
    question_id = str(row.get("question_id", "") or "")

    if not question_id and test_name and questionnaire.isdigit() and question.isdigit():
        question_id = make_question_id(test_name, int(questionnaire), int(question))

    return {
        "timestamp": str(row.get("timestamp", "") or ""),
        "mode": str(row.get("mode", "") or "imported"),
        "question_id": question_id,
        "test": test_name,
        "questionnaire": questionnaire,
        "question": question,
        "description": str(row.get("description", "") or row.get("topic", "") or ""),
        "selected_answer": str(
            row.get("selected_answer", "") or row.get("your_answer", "") or ""
        ),
        "correct_answer": str(row.get("correct_answer", "") or ""),
        "result": str(row.get("result", "") or ""),
    }


def ensure_csv_schema(path: Path, fieldnames: list[str]) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return

    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        current_fields = reader.fieldnames or []
        rows = list(reader)

    if current_fields == fieldnames:
        return

    normalized_rows = [normalize_history_row(row) for row in rows]
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(normalized_rows)
    tmp_path.replace(path)


def append_history(path: Path, row: dict[str, Any]) -> None:
    normalized = {field: str(row.get(field, "") or "") for field in HISTORY_FIELDS}
    with CSV_LOCK:
        ensure_csv_schema(path, HISTORY_FIELDS)
        write_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=HISTORY_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow(normalized)


def history_row(question: Question, selected_answer: str, mode: str, result: str) -> dict[str, Any]:
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "question_id": question.question_id,
        "test": question.test,
        "questionnaire": question.questionnaire,
        "question": question.question,
        "description": question.description,
        "selected_answer": selected_answer,
        "correct_answer": question.correct_answer,
        "result": result,
    }


def latest_mistake_questions(
    questions: dict[str, Question], limit: int = 50
) -> list[dict[str, Any]]:
    if not MISTAKES_FILE.exists() or MISTAKES_FILE.stat().st_size == 0:
        return []

    with CSV_LOCK:
        ensure_csv_schema(MISTAKES_FILE, HISTORY_FIELDS)
        with MISTAKES_FILE.open(newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in reversed(rows):
        normalized = normalize_history_row(row)
        question_id = normalized["question_id"]
        if question_id in seen or question_id not in questions:
            continue
        seen.add(question_id)
        public_question = questions[question_id].public_dict()
        public_question["last_selected_answer"] = normalized["selected_answer"]
        public_question["last_attempted_at"] = normalized["timestamp"]
        items.append(public_question)
        if len(items) >= limit:
            break

    return items


def create_state() -> AppState:
    questions = load_question_bank()
    export_question_bank(questions)
    return AppState(
        questions=questions,
        ordered_ids=ordered_question_ids(questions),
        tests=build_tests(questions),
    )


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Road Sign Practice</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --ink: #1f2933;
      --muted: #64748b;
      --line: #d8dee6;
      --accent: #2563eb;
      --accent-ink: #ffffff;
      --good: #147d4f;
      --good-bg: #e7f7ef;
      --bad: #b42318;
      --bad-bg: #fff1f0;
      --shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
    }

    button,
    select,
    input {
      font: inherit;
    }

    button {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--ink);
      cursor: pointer;
      min-height: 42px;
      padding: 0 16px;
    }

    button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }

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

    .scorebox strong {
      font-size: 18px;
    }

    .shell {
      display: grid;
      grid-template-columns: 300px minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
      max-width: 1220px;
      margin: 0 auto;
    }

    .controls,
    .viewer {
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
      color: var(--accent-ink);
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
      color: var(--accent-ink);
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
      background: #ffffff;
    }

    .answer-form {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 16px;
    }

    .option {
      position: relative;
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

    [hidden] {
      display: none !important;
    }

    @media (max-width: 840px) {
      .topbar {
        align-items: stretch;
        flex-direction: column;
      }

      .scorebox {
        min-width: 0;
      }

      .shell {
        grid-template-columns: 1fr;
        padding: 12px;
      }

      .answer-form {
        grid-template-columns: 1fr;
      }

      .question-head {
        flex-direction: column;
      }
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

    async function fetchJson(url, options = {}) {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Request failed");
      }
      return data;
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
      if (!selectedTest) {
        return;
      }
      selectedTest.questionnaires.forEach((setNo) => {
        const option = document.createElement("option");
        option.value = String(setNo);
        option.textContent = `Questionnaire ${setNo}`;
        els.setSelect.appendChild(option);
      });
    }

    async function startSession() {
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
        const data = await fetchJson("/api/mistakes");
        app.sequence = data.questions.map((question) => question.id);
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
            ? "No saved mistakes yet."
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
      els.questionImage.src = `${question.image_url}?t=${Date.now()}`;
      els.positionLabel.textContent = `Question ${app.index + 1} of ${app.sequence.length}`;
      els.statusLabel.textContent = "";
      resetAnswerControls();
      updateScore();
    }

    async function submitAnswer() {
      if (app.answered) {
        return;
      }
      const answer = selectedAnswer();
      if (!answer) {
        return;
      }

      const questionId = app.sequence[app.index];
      const data = await fetchJson("/api/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question_id: questionId,
          selected_answer: answer,
          mode: app.mode
        })
      });

      app.answered = true;
      app.score.answered += 1;
      if (data.correct) {
        app.score.correct += 1;
      }

      els.feedback.hidden = false;
      els.feedback.classList.add(data.correct ? "correct" : "wrong");
      els.feedback.textContent = data.correct
        ? `Correct. Actual answer: ${data.correct_answer}.`
        : `Wrong. Actual answer: ${data.correct_answer}.`;

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
      const data = await fetchJson("/api/bootstrap");
      app.questions = sortedQuestions(data.questions);
      app.questions.forEach((question) => app.questionById.set(question.id, question));
      app.tests = data.tests;
      els.bankCount.textContent = `${app.questions.length} questions extracted from ${app.tests.length} PDFs`;
      populateSelectors();
      startSession();
    }

    els.modeButtons.forEach((button) => {
      button.addEventListener("click", () => setMode(button.dataset.mode));
    });
    els.testSelect.addEventListener("change", () => {
      populateSetSelect();
      if (app.mode === "questionnaire") {
        startSession();
      }
    });
    els.setSelect.addEventListener("change", () => {
      if (app.mode === "questionnaire") {
        startSession();
      }
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


class RoadSignRequestHandler(BaseHTTPRequestHandler):
    state: AppState

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_bytes(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_bytes(
            status,
            body,
            "application/json; charset=utf-8",
            {"Cache-Control": "no-store"},
        )

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json(status, {"error": message})

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in {"/", "/index.html"}:
            self.send_bytes(
                HTTPStatus.OK,
                HTML.encode("utf-8"),
                "text/html; charset=utf-8",
                {"Cache-Control": "no-store"},
            )
            return

        if path == "/api/bootstrap":
            questions = [
                self.state.questions[question_id].public_dict()
                for question_id in self.state.ordered_ids
            ]
            self.send_json(
                HTTPStatus.OK,
                {
                    "questions": questions,
                    "tests": self.state.tests,
                    "total": len(questions),
                },
            )
            return

        if path == "/api/mistakes":
            self.send_json(
                HTTPStatus.OK,
                {"questions": latest_mistake_questions(self.state.questions)},
            )
            return

        if path.startswith("/image/") and path.endswith(".png"):
            question_id = urllib.parse.unquote(path.removeprefix("/image/")[:-4])
            self.serve_question_image(question_id)
            return

        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/answer":
            self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return

        question_id = str(payload.get("question_id", ""))
        selected_answer = str(payload.get("selected_answer", "")).strip()
        mode = str(payload.get("mode", "practice")).strip() or "practice"

        if selected_answer not in {"1", "2", "3"}:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Choose option 1, 2, or 3")
            return

        question = self.state.questions.get(question_id)
        if question is None:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Question not found")
            return

        is_correct = selected_answer == question.correct_answer
        result = "correct" if is_correct else "wrong"
        row = history_row(question, selected_answer, mode, result)
        append_history(RESULTS_FILE, row)
        if not is_correct:
            append_history(MISTAKES_FILE, row)

        self.send_json(
            HTTPStatus.OK,
            {
                "correct": is_correct,
                "correct_answer": question.correct_answer,
                "result": result,
                "description": question.description,
            },
        )

    def serve_question_image(self, question_id: str) -> None:
        question = self.state.questions.get(question_id)
        if question is None:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Question not found")
            return

        with fitz.open(question.pdf_path) as doc:
            page = doc[question.page_index]
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(2.2, 2.2),
                clip=fitz.Rect(question.crop),
                alpha=False,
            )
            png_bytes = pixmap.tobytes("png")

        self.send_bytes(
            HTTPStatus.OK,
            png_bytes,
            "image/png",
            {"Cache-Control": "public, max-age=3600"},
        )


class FallbackThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False


def create_handler(state: AppState) -> type[RoadSignRequestHandler]:
    class BoundRoadSignRequestHandler(RoadSignRequestHandler):
        pass

    BoundRoadSignRequestHandler.state = state
    return BoundRoadSignRequestHandler


def create_server(state: AppState) -> tuple[FallbackThreadingHTTPServer, int]:
    handler = create_handler(state)
    last_error: OSError | None = None
    for port in range(START_PORT, START_PORT + 50):
        try:
            server = FallbackThreadingHTTPServer((HOST, port), handler)
            return server, port
        except OSError as exc:
            last_error = exc

    raise OSError(f"No free port found from {START_PORT} to {START_PORT + 49}") from last_error


def run() -> None:
    state = create_state()
    server, port = create_server(state)
    url = f"http://{HOST}:{port}/"
    print(f"Extracted {len(state.questions)} questions.", flush=True)
    print(f"Exported {QUESTION_EXPORT_FILE.name}.", flush=True)
    print(f"Open {url}", flush=True)
    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
