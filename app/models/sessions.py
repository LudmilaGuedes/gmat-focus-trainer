from app.extensions import db
from app.timeutils import utcnow

# Attempt/StudySession modes. Only PRACTICE_MODES feed automatic level
# promotion; ABILITY_MODES feed the score estimate (review attempts are
# excluded from both: re-answering a question you've already seen the
# solution to says little about ability).
PRACTICE_MODES = ("study", "checkpoint")
ABILITY_MODES = ("study", "checkpoint", "mock_exam")


class StudySession(db.Model):
    __tablename__ = "study_sessions"

    id = db.Column(db.Integer, primary_key=True)
    mode = db.Column(db.String(20), nullable=False)  # study | review | checkpoint | mock_exam
    started_at = db.Column(db.DateTime, default=utcnow)
    ended_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    attempts = db.relationship("Attempt", back_populates="session")


class Attempt(db.Model):
    """Every answered question, in any mode, is logged here."""

    __tablename__ = "attempts"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("study_sessions.id"), nullable=False)
    mode = db.Column(db.String(20), nullable=False)  # study | review | checkpoint | mock_exam
    selected_answer_json = db.Column(db.JSON, nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    difficulty_at_attempt = db.Column(db.Integer, nullable=False)
    time_spent_seconds = db.Column(db.Integer, nullable=True)
    guessed = db.Column(db.Boolean, nullable=False, default=False)
    answered_at = db.Column(db.DateTime, default=utcnow)

    question = db.relationship("Question")
    session = db.relationship("StudySession", back_populates="attempts")


class LessonView(db.Model):
    """Log of lesson reads / theory reviews (for the daily plan and study-time stats)."""

    __tablename__ = "lesson_views"

    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id"), nullable=False)
    kind = db.Column(db.String(12), nullable=False, default="study")  # study | review
    viewed_at = db.Column(db.DateTime, default=utcnow)

    lesson = db.relationship("Lesson")


class SessionReport(db.Model):
    """Cached snapshot of a session's report. Always re-derivable from
    `attempts` — never the sole source of truth."""

    __tablename__ = "session_reports"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("study_sessions.id"), unique=True, nullable=False)
    generated_at = db.Column(db.DateTime, default=utcnow)
    summary_json = db.Column(db.JSON, nullable=False)

    session = db.relationship("StudySession")
