"""Flask-Admin panel at /admin — a ready-made CRUD UI over the curatable
question bank (Question, AnswerOption, Lesson, Flashcard, QuestionSet), as an
alternative to editing YAML files under sample_bank/ and re-running
scripts/import_questions.py. Note: edits made here are overwritten the next
time the YAML with the same slug is imported."""

from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView

from app.extensions import db
from app.models.progress import ExternalScore, LevelAdjustment, ReviewItem, SubtopicProgress
from app.models.question_bank import AnswerOption, Flashcard, Lesson, Question, QuestionSet
from app.models.settings import AppSetting
from app.models.taxonomy import ContentArea, QuestionType, Section, Subtopic


class QuestionView(ModelView):
    column_list = ("slug", "subtopic", "question_type", "difficulty", "status", "flagged", "source")
    column_searchable_list = ("slug", "stem_text")
    column_filters = ("difficulty", "status", "flagged", "source")
    column_editable_list = ("difficulty", "status", "flagged")


def init_admin(app):
    admin = Admin(app, name="GMAT Focus Trainer — Curadoria", template_mode="bootstrap4")

    admin.add_view(ModelView(Section, db.session, category="Taxonomia"))
    admin.add_view(ModelView(ContentArea, db.session, category="Taxonomia"))
    admin.add_view(ModelView(Subtopic, db.session, category="Taxonomia"))
    admin.add_view(ModelView(QuestionType, db.session, category="Taxonomia"))

    admin.add_view(ModelView(QuestionSet, db.session, category="Banco de questões"))
    admin.add_view(QuestionView(Question, db.session, category="Banco de questões"))
    admin.add_view(ModelView(AnswerOption, db.session, category="Banco de questões"))
    admin.add_view(ModelView(Lesson, db.session, category="Banco de questões"))
    admin.add_view(ModelView(Flashcard, db.session, category="Banco de questões"))

    admin.add_view(ModelView(SubtopicProgress, db.session, category="Progresso"))
    admin.add_view(ModelView(ReviewItem, db.session, category="Progresso"))
    admin.add_view(ModelView(LevelAdjustment, db.session, category="Progresso"))
    admin.add_view(ModelView(ExternalScore, db.session, category="Progresso"))
    admin.add_view(ModelView(AppSetting, db.session, category="Progresso"))

    return admin
