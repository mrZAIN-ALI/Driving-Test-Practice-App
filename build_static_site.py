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
STATIC_DIR = ROOT / "static_site"


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


def copy_static_files() -> None:
    for path in STATIC_DIR.iterdir():
        if path.is_file():
            shutil.copy2(path, DOCS_DIR / path.name)


def build_static_site() -> None:
    state = ab.create_state()
    if DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    copy_static_files()
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

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
    (DATA_DIR / "questions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Built static site at {DOCS_DIR}")
    print(f"Questions: {len(state.questions)}")


if __name__ == "__main__":
    build_static_site()
