"""Imports/curates the content bank from YAML:

  <content bank>/questions/**/*.yaml  -> QuestionSet / Question / AnswerOption
  <content bank>/lessons/*.yaml       -> Lesson / Flashcard

The content bank is app.config["CONTENT_BANK_DIR"] (see config.py): the private
content_bank/ when present, otherwise the sample_bank/ shipped with the repo.

Idempotent upsert by `slug`: editing a YAML file and re-running this script
never duplicates rows, it just updates the matching rows. This is the
intended way to expand the bank — see sample_bank/README.md for the schema.
(Flask-Admin at /admin is the alternative, GUI-based way to edit the same
tables; YAML wins on the next import.)
"""

import glob
import os
import sys

import yaml
from flask import current_app

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.levels import normalize_difficulty  # noqa: E402
from app.models.question_bank import AnswerOption, Flashcard, Lesson, Question, QuestionSet  # noqa: E402
from app.models.taxonomy import QuestionType, Section, Subtopic  # noqa: E402


def questions_dir():
    return os.path.join(current_app.config["CONTENT_BANK_DIR"], "questions")


def lessons_dir():
    return os.path.join(current_app.config["CONTENT_BANK_DIR"], "lessons")


def _load_yaml_files(directory):
    for path in sorted(glob.glob(os.path.join(directory, "**", "*.yaml"), recursive=True)):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        yield path, data


def import_question_sets(data, path):
    for qs in data.get("question_sets", []):
        section = Section.query.filter_by(code=qs["section"]).first()
        if section is None:
            raise ValueError(f"{path}: unknown section code '{qs['section']}'")
        row = QuestionSet.query.filter_by(slug=qs["slug"]).first()
        if row is None:
            row = QuestionSet(slug=qs["slug"])
            db.session.add(row)
        row.section_id = section.id
        row.set_type = qs.get("set_type")
        row.stimulus_text = qs.get("stimulus")
        row.tabs_json = qs.get("tabs")
    db.session.flush()


def import_questions(data, path):
    count = 0
    for q in data.get("questions", []):
        subtopic = Subtopic.query.filter_by(code=q["subtopic"]).first()
        if subtopic is None:
            raise ValueError(f"{path}: unknown subtopic code '{q['subtopic']}' ({q.get('slug')})")
        question_type = QuestionType.query.filter_by(code=q["question_type"]).first()
        if question_type is None:
            raise ValueError(f"{path}: unknown question_type code '{q['question_type']}' ({q.get('slug')})")

        set_id, set_order = None, None
        if q.get("question_set"):
            question_set = QuestionSet.query.filter_by(slug=q["question_set"]).first()
            if question_set is None:
                raise ValueError(f"{path}: unknown question_set slug '{q['question_set']}'")
            set_id, set_order = question_set.id, q.get("set_order")

        try:
            difficulty = normalize_difficulty(q["difficulty"])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{path}: {q.get('slug')}: {exc}") from exc

        question = Question.query.filter_by(slug=q["slug"]).first()
        if question is None:
            question = Question(slug=q["slug"])
            db.session.add(question)

        question.subtopic_id = subtopic.id
        question.question_type_id = question_type.id
        question.set_id = set_id
        question.set_order = set_order
        question.difficulty = difficulty
        question.stem_text = q["stem"]
        question.stimulus_text = q.get("stimulus")
        question.media_json = q.get("media")
        question.explanation_text = q["explanation"]
        question.source = q.get("source", "original")
        question.source_ref = q.get("source_ref")
        question.status = q.get("status", "active")
        question.author = q.get("author")

        correct_summary = {}
        for opt in q.get("options", []):
            if opt.get("correct"):
                correct_summary[opt.get("group") or "single"] = opt["label"]
        question.correct_answer_json = correct_summary

        db.session.flush()  # ensure question.id exists before writing options

        # Keep option ids stable across re-imports when the options didn't change,
        # so answers stored in attempts still point at the right option.
        existing = AnswerOption.query.filter_by(question_id=question.id).order_by(AnswerOption.order).all()
        wanted = q.get("options", [])
        if len(existing) == len(wanted):
            for order, (row, opt) in enumerate(zip(existing, wanted)):
                row.group_key = opt.get("group")
                row.option_label = opt["label"]
                row.option_text = str(opt["text"])
                row.is_correct = bool(opt.get("correct", False))
                row.order = order
        else:
            for row in existing:
                db.session.delete(row)
            db.session.flush()
            for order, opt in enumerate(wanted):
                db.session.add(AnswerOption(
                    question_id=question.id,
                    group_key=opt.get("group"),
                    option_label=opt["label"],
                    option_text=str(opt["text"]),
                    is_correct=bool(opt.get("correct", False)),
                    order=order,
                ))
        count += 1
    return count


def import_lessons():
    count = 0
    for path, data in _load_yaml_files(lessons_dir()):
        for lesson in data.get("lessons", []):
            subtopic = Subtopic.query.filter_by(code=lesson["subtopic"]).first()
            if subtopic is None:
                raise ValueError(f"{path}: unknown subtopic code '{lesson['subtopic']}'")
            row = Lesson.query.filter_by(slug=lesson["slug"]).first()
            if row is None:
                row = Lesson(slug=lesson["slug"])
                db.session.add(row)
            row.subtopic_id = subtopic.id
            row.title = lesson["title"]
            row.content_markdown = lesson["content"]
            row.key_points_markdown = lesson.get("key_points")
            row.estimated_minutes = int(lesson.get("minutes", 15))
            db.session.flush()
            for order, card in enumerate(lesson.get("flashcards", []) or []):
                slug = f"{lesson['slug']}-fc{order + 1}"
                fc = Flashcard.query.filter_by(slug=slug).first()
                if fc is None:
                    fc = Flashcard(slug=slug)
                    db.session.add(fc)
                fc.lesson_id = row.id
                fc.subtopic_id = subtopic.id
                fc.front = card["front"]
                fc.back = card["back"]
                fc.order = order
            count += 1
    return count


def import_all():
    total = 0
    for path, data in _load_yaml_files(questions_dir()):
        import_question_sets(data, path)
        total += import_questions(data, path)
    lessons = import_lessons()
    db.session.commit()
    return total, lessons


def main():
    app = create_app()
    with app.app_context():
        total, lessons = import_all()
        print(f"Importação concluída: {total} questões, {lessons} lições "
              f"({current_app.config['CONTENT_BANK_DIR']}).")


if __name__ == "__main__":
    main()
