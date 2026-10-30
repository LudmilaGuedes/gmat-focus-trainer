"""Single-question page (solution, your history, report an error) and the
list of questions you flagged as possibly wrong."""

from flask import Blueprint, redirect, render_template, request, url_for

from app.extensions import db
from app.models.progress import ReviewItem
from app.models.question_bank import Question
from app.models.sessions import Attempt
from app.routes._answering import answer_breakdown
from app.services.srs import ERROR_REASONS

bp = Blueprint("questions", __name__, url_prefix="/question")


@bp.route("/<int:question_id>")
def detail(question_id):
    question = Question.query.get_or_404(question_id)
    attempts = Attempt.query.filter_by(question_id=question_id).order_by(Attempt.answered_at.desc()).all()
    last_selected = attempts[0].selected_answer_json if attempts else {}
    return render_template(
        "questions/detail.html",
        question=question,
        attempts=attempts,
        breakdown=answer_breakdown(question, last_selected),
        review_item=ReviewItem.query.filter_by(question_id=question_id).first(),
        reasons=ERROR_REASONS,
    )


@bp.route("/<int:question_id>/flag", methods=["POST"])
def flag(question_id):
    question = Question.query.get_or_404(question_id)
    if request.form.get("action") == "unflag":
        question.flagged = False
        question.flag_note = None
    else:
        question.flagged = True
        question.flag_note = (request.form.get("note") or "").strip() or None
    db.session.commit()
    return redirect(request.form.get("next") or url_for("questions.detail", question_id=question_id))


@bp.route("/flagged")
def flagged():
    questions = Question.query.filter_by(flagged=True).order_by(Question.updated_at.desc()).all()
    return render_template("questions/flagged.html", questions=questions)
