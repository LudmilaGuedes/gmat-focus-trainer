"""
THE CURATABLE QUESTION BANK
===========================
These are the tables to expand/curate over time. New questions should NOT be
inserted here by hand-editing the database directly — instead:

  1. Add/edit YAML files under sample_bank/questions/<section>/<content_area>.yaml
     and sample_bank/lessons/*.yaml (schema documented in
     sample_bank/README.md), then run `python scripts/import_questions.py`
     (idempotent upsert by `slug`).
  2. Or use the Flask-Admin panel at /admin, which edits these same tables
     through a web UI.

Everything below is intentionally generic across all 6 GMAT Focus question
types (multiple_choice, data_sufficiency, table_analysis,
graphics_interpretation, two_part_analysis, multi_source_reasoning) so no
per-type tables are needed: `question_type_id` + `answer_options.group_key` +
`media_json` are enough to represent all of them.
"""

from app.extensions import db
from app.levels import level_name
from app.timeutils import utcnow


class QuestionSet(db.Model):
    """Groups several questions under one shared stimulus
    (a Reading Comprehension passage, or a Multi-Source Reasoning tab set)."""

    __tablename__ = "question_sets"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=False)
    set_type = db.Column(db.String(40), nullable=True)  # 'reading_passage', 'multi_source_reasoning'
    stimulus_text = db.Column(db.Text, nullable=True)
    tabs_json = db.Column(db.JSON, nullable=True)  # MSR: list of {title, content}
    created_at = db.Column(db.DateTime, default=utcnow)

    section = db.relationship("Section")
    questions = db.relationship("Question", back_populates="question_set", order_by="Question.set_order")


class Question(db.Model):
    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), unique=True, nullable=False)

    subtopic_id = db.Column(db.Integer, db.ForeignKey("subtopics.id"), nullable=False)
    question_type_id = db.Column(db.Integer, db.ForeignKey("question_types.id"), nullable=False)
    set_id = db.Column(db.Integer, db.ForeignKey("question_sets.id"), nullable=True)
    set_order = db.Column(db.Integer, nullable=True)

    difficulty = db.Column(db.Integer, nullable=False)  # 1..5, see app/levels.py

    stem_text = db.Column(db.Text, nullable=False)
    stimulus_text = db.Column(db.Text, nullable=True)  # per-question stimulus (e.g. DS statements)
    media_json = db.Column(db.JSON, nullable=True)  # chart data (Graphics Interp.), table data (Table Analysis)

    correct_answer_json = db.Column(db.JSON, nullable=False)  # {group_key: label}
    explanation_text = db.Column(db.Text, nullable=False)  # always shown on "ver solução"

    source = db.Column(db.String(20), nullable=False, default="original")  # original | official | external
    source_ref = db.Column(db.String(200), nullable=True)  # e.g. "OG 2024-25, PS #112" for official items you own
    status = db.Column(db.String(10), nullable=False, default="active")  # draft | active | retired
    author = db.Column(db.String(120), nullable=True)
    # "Reportar erro": a flagged question is not served until you fix/unflag it.
    flagged = db.Column(db.Boolean, nullable=False, default=False)
    flag_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    subtopic = db.relationship("Subtopic")
    question_type = db.relationship("QuestionType")
    question_set = db.relationship("QuestionSet", back_populates="questions")
    options = db.relationship(
        "AnswerOption", back_populates="question", order_by="AnswerOption.order",
        cascade="all, delete-orphan",
    )

    @property
    def content_area(self):
        return self.subtopic.content_area

    @property
    def section(self):
        return self.subtopic.content_area.section

    @property
    def level_name(self):
        return level_name(self.difficulty)

    def __repr__(self):
        return f"<Question {self.slug} (N{self.difficulty})>"


class AnswerOption(db.Model):
    __tablename__ = "answer_options"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    group_key = db.Column(db.String(40), nullable=True)  # e.g. 'part1'/'part2', 'row1'/'row2'
    option_label = db.Column(db.String(10), nullable=False)  # 'A', 'B', 'C', ...
    option_text = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    order = db.Column(db.Integer, nullable=False, default=0)

    question = db.relationship("Question", back_populates="options")


class Lesson(db.Model):
    """Full theory lesson for one subtopic (the "Aprender" step of the track):
    concept, worked examples, traps. `key_points_markdown` is the short
    version shown on spaced theory reviews and after repeated mistakes."""

    __tablename__ = "lessons"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    subtopic_id = db.Column(db.Integer, db.ForeignKey("subtopics.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content_markdown = db.Column(db.Text, nullable=False)
    key_points_markdown = db.Column(db.Text, nullable=True)
    estimated_minutes = db.Column(db.Integer, nullable=False, default=15)
    created_at = db.Column(db.DateTime, default=utcnow)

    subtopic = db.relationship("Subtopic")
    flashcards = db.relationship("Flashcard", back_populates="lesson", order_by="Flashcard.order")


class Flashcard(db.Model):
    """Formula/rule/concept card, reviewed with spaced repetition."""

    __tablename__ = "flashcards"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id"), nullable=False)
    subtopic_id = db.Column(db.Integer, db.ForeignKey("subtopics.id"), nullable=False)
    front = db.Column(db.Text, nullable=False)
    back = db.Column(db.Text, nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)

    lesson = db.relationship("Lesson", back_populates="flashcards")
    subtopic = db.relationship("Subtopic")
