from app.extensions import db
from app.timeutils import utcnow


SECTION_TIME_LIMIT_SECONDS = 45 * 60
SECTION_QUESTION_COUNTS = {"QR": 21, "VR": 23, "DI": 20}
MAX_ANSWER_EDITS_PER_SECTION = 3
BREAK_SECONDS = 10 * 60


class MockExam(db.Model):
    __tablename__ = "mock_exams"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("study_sessions.id"), nullable=True)
    kind = db.Column(db.String(10), nullable=False, default="full")  # full | section
    started_at = db.Column(db.DateTime, default=utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="in_progress")  # in_progress|completed|abandoned
    break_used = db.Column(db.Boolean, nullable=False, default=False)
    pause_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")  # >0: not exam conditions

    sections = db.relationship("MockExamSection", back_populates="mock_exam", order_by="MockExamSection.order")
    result = db.relationship("MockExamResult", back_populates="mock_exam", uselist=False)


class MockExamSection(db.Model):
    __tablename__ = "mock_exam_sections"

    id = db.Column(db.Integer, primary_key=True)
    mock_exam_id = db.Column(db.Integer, db.ForeignKey("mock_exams.id"), nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=False)
    order = db.Column(db.Integer, nullable=False)
    time_limit_seconds = db.Column(db.Integer, nullable=False, default=SECTION_TIME_LIMIT_SECONDS)
    questions_planned = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    paused_at = db.Column(db.DateTime, nullable=True)  # set while the section clock is frozen
    paused_seconds = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    edits_used = db.Column(db.Integer, nullable=False, default=0)
    scaled_score = db.Column(db.Integer, nullable=True)  # 60-90
    theta = db.Column(db.Float, nullable=True)

    mock_exam = db.relationship("MockExam", back_populates="sections")
    section = db.relationship("Section")
    attempts = db.relationship(
        "MockExamAttempt", back_populates="mock_exam_section", order_by="MockExamAttempt.sequence_number"
    )


class MockExamAttempt(db.Model):
    """Logs every step of the adaptive algorithm for transparency and review."""

    __tablename__ = "mock_exam_attempts"

    id = db.Column(db.Integer, primary_key=True)
    mock_exam_section_id = db.Column(db.Integer, db.ForeignKey("mock_exam_sections.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    sequence_number = db.Column(db.Integer, nullable=False)
    difficulty_presented = db.Column(db.Integer, nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    selected_answer_json = db.Column(db.JSON, nullable=False)
    time_spent_seconds = db.Column(db.Integer, nullable=True)
    running_ability_estimate = db.Column(db.Float, nullable=False)
    bookmarked = db.Column(db.Boolean, nullable=False, default=False)
    edited = db.Column(db.Boolean, nullable=False, default=False)

    mock_exam_section = db.relationship("MockExamSection", back_populates="attempts")
    question = db.relationship("Question")


class MockExamResult(db.Model):
    """Source of the score-history chart. Section-only mocks fill just one
    section score and leave total NULL."""

    __tablename__ = "mock_exam_results"

    id = db.Column(db.Integer, primary_key=True)
    mock_exam_id = db.Column(db.Integer, db.ForeignKey("mock_exams.id"), unique=True, nullable=False)
    total_scaled_score = db.Column(db.Integer, nullable=True)  # 205-805
    qr_scaled_score = db.Column(db.Integer, nullable=True)
    vr_scaled_score = db.Column(db.Integer, nullable=True)
    di_scaled_score = db.Column(db.Integer, nullable=True)
    completed_at = db.Column(db.DateTime, default=utcnow)

    mock_exam = db.relationship("MockExam", back_populates="result")
