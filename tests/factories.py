"""Tiny builders for tests (no fixtures library)."""

from app.extensions import db
from app.models.question_bank import AnswerOption, Question
from app.models.sessions import StudySession
from app.models.taxonomy import ContentArea, QuestionType, Section, Subtopic


def make_section(code="QR"):
    section = Section.query.filter_by(code=code).first()
    if section is None:
        section = Section(code=code, name=f"Section {code}", order={"QR": 0, "VR": 1, "DI": 2}.get(code, 0))
        db.session.add(section)
        db.session.flush()
    return section


def make_subtopic(code="qr_test_sub", section_code="QR", area_code=None):
    section = make_section(section_code)
    area_code = area_code or f"{section_code.lower()}_area"
    area = ContentArea.query.filter_by(code=area_code).first()
    if area is None:
        area = ContentArea(section_id=section.id, code=area_code, name=f"Area {area_code}")
        db.session.add(area)
        db.session.flush()
    subtopic = Subtopic(content_area_id=area.id, code=code, name=f"Subtopic {code}")
    db.session.add(subtopic)
    db.session.commit()
    return subtopic


def make_question(subtopic, difficulty=1, qtype="multiple_choice"):
    question_type = QuestionType.query.filter_by(code=qtype).first()
    if question_type is None:
        question_type = QuestionType(code=qtype, name=qtype)
        db.session.add(question_type)
        db.session.flush()
    question = Question(
        slug=f"test-{subtopic.code}-{difficulty}-{Question.query.count()}",
        subtopic_id=subtopic.id,
        question_type_id=question_type.id,
        difficulty=difficulty,
        stem_text="What is 1 + 1?",
        correct_answer_json={"single": "A"},
        explanation_text="Because.",
    )
    db.session.add(question)
    db.session.flush()
    db.session.add(AnswerOption(question_id=question.id, option_label="A", option_text="2", is_correct=True, order=0))
    db.session.add(AnswerOption(question_id=question.id, option_label="B", option_text="3", is_correct=False, order=1))
    db.session.commit()
    return question


def correct_option_id(question):
    return next(o.id for o in question.options if o.is_correct)


def wrong_option_id(question):
    return next(o.id for o in question.options if not o.is_correct)


def make_session(mode="study"):
    session = StudySession(mode=mode)
    db.session.add(session)
    db.session.commit()
    return session
