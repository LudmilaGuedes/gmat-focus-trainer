from app.extensions import db
from app.timeutils import utcnow


class SubtopicProgress(db.Model):
    """One row per subtopic: where the user is on the study track for this
    skill. `level` (1..5) is the single source of truth for what difficulty
    to serve in study-mode practice of this subtopic."""

    __tablename__ = "subtopic_progress"

    subtopic_id = db.Column(db.Integer, db.ForeignKey("subtopics.id"), primary_key=True)
    level = db.Column(db.Integer, nullable=False, default=1)
    manually_locked = db.Column(db.Boolean, nullable=False, default=False)

    lesson_completed_at = db.Column(db.DateTime, nullable=True)
    checkpoint_passed_at = db.Column(db.DateTime, nullable=True)
    checkpoint_attempts = db.Column(db.Integer, nullable=False, default=0)
    # Spaced review of the theory itself (key points), see services/srs.py.
    lesson_review_step = db.Column(db.Integer, nullable=False, default=0)
    lesson_next_review_at = db.Column(db.DateTime, nullable=True)

    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    subtopic = db.relationship("Subtopic")

    @property
    def status(self):
        if self.lesson_completed_at is None:
            return "new"
        if self.checkpoint_passed_at is None:
            return "checkpoint"
        return "practicing"


class SubtopicLevelStat(db.Model):
    """Rollup of practice attempts per (subtopic, level), used for automatic
    promotion/demotion. `recent_json` keeps the last 10 results so the
    decision reflects current skill, not the whole history."""

    __tablename__ = "subtopic_level_stats"
    __table_args__ = (db.UniqueConstraint("subtopic_id", "level"),)

    id = db.Column(db.Integer, primary_key=True)
    subtopic_id = db.Column(db.Integer, db.ForeignKey("subtopics.id"), nullable=False)
    level = db.Column(db.Integer, nullable=False)
    attempts_count = db.Column(db.Integer, nullable=False, default=0)
    correct_count = db.Column(db.Integer, nullable=False, default=0)
    recent_json = db.Column(db.JSON, nullable=False, default=list)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    subtopic = db.relationship("Subtopic")

    @property
    def accuracy(self):
        return self.correct_count / self.attempts_count if self.attempts_count else 0.0

    @property
    def recent_accuracy(self):
        recent = self.recent_json or []
        return sum(1 for r in recent if r) / len(recent) if recent else 0.0


class LevelAdjustment(db.Model):
    """History of every level change of a subtopic: automatic promotions and
    demotions from study-mode practice, and manual adjustments. Mock exams
    never write here (requirement: a mock never silently changes study
    difficulty)."""

    __tablename__ = "level_adjustments"

    id = db.Column(db.Integer, primary_key=True)
    subtopic_id = db.Column(db.Integer, db.ForeignKey("subtopics.id"), nullable=False)
    previous_level = db.Column(db.Integer, nullable=False)
    new_level = db.Column(db.Integer, nullable=False)
    reason_text = db.Column(db.Text, nullable=True)
    source_mock_exam_id = db.Column(db.Integer, db.ForeignKey("mock_exams.id"), nullable=True)
    triggered_by = db.Column(db.String(20), nullable=False, default="manual")  # manual|auto_promote|auto_demote
    # Newest attempt id when the change happened: only later attempts count as
    # evidence at the new level (timestamps alone are too coarse on Windows).
    after_attempt_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    subtopic = db.relationship("Subtopic")


class ReviewItem(db.Model):
    """Spaced-repetition queue (Leitner boxes): a question you missed / guessed /
    solved too slowly, or a theory flashcard. Also the "caderno de erros"."""

    __tablename__ = "review_items"
    __table_args__ = (
        db.UniqueConstraint("question_id"),
        db.UniqueConstraint("flashcard_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    item_type = db.Column(db.String(12), nullable=False)  # question | flashcard
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=True)
    flashcard_id = db.Column(db.Integer, db.ForeignKey("flashcards.id"), nullable=True)

    box = db.Column(db.Integer, nullable=False, default=0)
    due_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_reviewed_at = db.Column(db.DateTime, nullable=True)
    reviews_count = db.Column(db.Integer, nullable=False, default=0)
    lapses = db.Column(db.Integer, nullable=False, default=0)
    graduated = db.Column(db.Boolean, nullable=False, default=False)

    origin = db.Column(db.String(12), nullable=True)  # wrong | guessed | slow | mock | lesson
    error_reason = db.Column(db.String(20), nullable=True)  # concept | reading | careless | time | strategy
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    question = db.relationship("Question")
    flashcard = db.relationship("Flashcard")


class ScoreSnapshot(db.Model):
    """One estimated-score row per day, for the progress chart."""

    __tablename__ = "score_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.Date, unique=True, nullable=False)
    qr = db.Column(db.Integer, nullable=True)
    vr = db.Column(db.Integer, nullable=True)
    di = db.Column(db.Integer, nullable=True)
    total = db.Column(db.Integer, nullable=True)


class ExternalScore(db.Model):
    """A score from an OFFICIAL practice exam (mba.com) or the real test.
    Used to calibrate the app's estimate against reality."""

    __tablename__ = "external_scores"

    id = db.Column(db.Integer, primary_key=True)
    taken_on = db.Column(db.Date, nullable=False)
    source = db.Column(db.String(120), nullable=False)
    total = db.Column(db.Integer, nullable=False)
    qr = db.Column(db.Integer, nullable=True)
    vr = db.Column(db.Integer, nullable=True)
    di = db.Column(db.Integer, nullable=True)
    app_estimate_total = db.Column(db.Integer, nullable=True)  # snapshot of the app's (uncalibrated) estimate that day
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
