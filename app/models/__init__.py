"""Import every model so Alembic's autogenerate can discover them via db.metadata."""

from app.models.taxonomy import Section, ContentArea, Subtopic, QuestionType  # noqa: F401
from app.models.question_bank import QuestionSet, Question, AnswerOption, Lesson, Flashcard  # noqa: F401
from app.models.progress import (  # noqa: F401
    SubtopicProgress,
    SubtopicLevelStat,
    LevelAdjustment,
    ReviewItem,
    ScoreSnapshot,
    ExternalScore,
)
from app.models.sessions import StudySession, Attempt, LessonView, SessionReport  # noqa: F401
from app.models.mock_exam import MockExam, MockExamSection, MockExamAttempt, MockExamResult  # noqa: F401
from app.models.settings import AppSetting  # noqa: F401
