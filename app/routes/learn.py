"""Track + theory: /trilha, lessons, theory reviews and the checkpoint
(teste de fixação) that closes each lesson."""

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from app.extensions import db
from app.models.question_bank import Question
from app.models.sessions import StudySession
from app.models.settings import AppSetting
from app.models.taxonomy import Subtopic
from app.routes._answering import answer_breakdown, form_guessed, parse_answer, seconds_since, stamp
from app.services.adaptive_study import (
    complete_lesson,
    complete_lesson_review,
    finalize_checkpoint,
    get_lesson_for_subtopic,
    get_or_create_progress,
    record_attempt,
)
from app.services.grading import build_answer_groups, grade_answer
from app.services.question_selector import select_question_in_range
from app.services.study_plan import PHASES, current_phase, days_until_exam, track_overview
from app.timeutils import utcnow

bp = Blueprint("learn", __name__)


@bp.route("/trilha")
def track():
    overview = track_overview()
    phase = current_phase(overview, None, days_until_exam())
    groups = {}
    for item in overview["items"]:
        groups.setdefault(item["phase"], []).append(item)
    next_item = next((i for i in overview["items"] if i["status"] != "practicing"), None)
    return render_template(
        "learn/track.html", overview=overview, groups=groups, phase=phase, phases=PHASES, next_item=next_item
    )


@bp.route("/learn/<int:subtopic_id>")
def lesson(subtopic_id):
    subtopic = Subtopic.query.get_or_404(subtopic_id)
    lesson_row = get_lesson_for_subtopic(subtopic_id)
    progress = get_or_create_progress(subtopic_id)
    n_questions = Question.query.filter_by(subtopic_id=subtopic_id, status="active").count()
    return render_template(
        "learn/lesson.html", subtopic=subtopic, lesson=lesson_row, progress=progress, n_questions=n_questions
    )


@bp.route("/learn/<int:subtopic_id>/complete", methods=["POST"])
def lesson_complete(subtopic_id):
    Subtopic.query.get_or_404(subtopic_id)
    complete_lesson(subtopic_id)
    return redirect(url_for("learn.checkpoint_start", subtopic_id=subtopic_id))


@bp.route("/learn/<int:subtopic_id>/review", methods=["GET", "POST"])
def lesson_review(subtopic_id):
    subtopic = Subtopic.query.get_or_404(subtopic_id)
    lesson_row = get_lesson_for_subtopic(subtopic_id)
    if request.method == "POST":
        complete_lesson_review(subtopic_id)
        return redirect(request.form.get("next") or url_for("home.index"))
    return render_template(
        "learn/lesson_review.html", subtopic=subtopic, lesson=lesson_row, progress=get_or_create_progress(subtopic_id)
    )


# ------------------------------------------------------------------ checkpoint


def _checkpoint_state():
    return session.get("checkpoint")


@bp.route("/learn/<int:subtopic_id>/checkpoint")
def checkpoint_start(subtopic_id):
    Subtopic.query.get_or_404(subtopic_id)
    study_session = StudySession(mode="checkpoint")
    db.session.add(study_session)
    db.session.commit()
    session["checkpoint"] = {
        "subtopic_id": subtopic_id,
        "session_id": study_session.id,
        "total": AppSetting.get_int("checkpoint_questions") or 5,
        "served": [],
        "correct": 0,
        "current_qid": None,
        "shown_at": None,
        "results": [],
    }
    return redirect(url_for("learn.checkpoint_question"))


@bp.route("/learn/checkpoint")
def checkpoint_question():
    state = _checkpoint_state()
    if not state:
        return redirect(url_for("learn.track"))
    subtopic = Subtopic.query.get_or_404(state["subtopic_id"])
    if len(state["served"]) >= state["total"] and not state["current_qid"]:
        return redirect(url_for("learn.checkpoint_result"))

    question = Question.query.get(state["current_qid"]) if state["current_qid"] else None
    if question is None:
        question = select_question_in_range(subtopic.id, (1, 2), exclude_ids=state["served"])
        if question is None:
            if state["served"]:
                return redirect(url_for("learn.checkpoint_result"))
            return render_template("study/no_questions.html", subtopic=subtopic)
        state["current_qid"] = question.id
        state["shown_at"] = stamp()
        session["checkpoint"] = state

    return render_template(
        "learn/checkpoint.html",
        subtopic=subtopic,
        question=question,
        answer_groups=build_answer_groups(question),
        number=len(state["served"]) + 1,
        total=state["total"],
        shown_at=state["shown_at"],
    )


@bp.route("/learn/checkpoint/answer", methods=["POST"])
def checkpoint_answer():
    state = _checkpoint_state()
    if not state or not state.get("current_qid"):
        return redirect(url_for("learn.track"))
    question = Question.query.get_or_404(state["current_qid"])
    if request.form.get("question_id") != str(question.id):
        abort(400)
    selected = parse_answer(question)
    is_correct = grade_answer(question, selected)
    elapsed = seconds_since(state.get("shown_at"))
    record_attempt(question, state["session_id"], selected, is_correct, mode="checkpoint",
                   time_spent_seconds=elapsed, guessed=form_guessed())
    state["served"].append(question.id)
    state["correct"] += 1 if is_correct else 0
    state["results"].append({"qid": question.id, "correct": is_correct, "selected": selected, "seconds": elapsed})
    state["current_qid"] = None
    session["checkpoint"] = state
    return redirect(url_for("learn.checkpoint_feedback"))


@bp.route("/learn/checkpoint/feedback")
def checkpoint_feedback():
    state = _checkpoint_state()
    if not state or not state["results"]:
        return redirect(url_for("learn.track"))
    last = state["results"][-1]
    question = Question.query.get_or_404(last["qid"])
    return render_template(
        "learn/checkpoint_feedback.html",
        question=question,
        is_correct=last["correct"],
        seconds=last["seconds"],
        breakdown=answer_breakdown(question, last["selected"]),
        number=len(state["served"]),
        total=state["total"],
        finished=len(state["served"]) >= state["total"],
    )


@bp.route("/learn/checkpoint/result")
def checkpoint_result():
    state = _checkpoint_state()
    if not state:
        return redirect(url_for("learn.track"))
    subtopic = Subtopic.query.get_or_404(state["subtopic_id"])
    total = len(state["served"])
    if not state.get("finalized"):
        passed = finalize_checkpoint(subtopic.id, state["correct"], total)
        study_session = StudySession.query.get(state["session_id"])
        if study_session and study_session.ended_at is None:
            study_session.ended_at = utcnow()
            db.session.commit()
        state["finalized"] = True
        state["passed"] = passed
        session["checkpoint"] = state
    progress = get_or_create_progress(subtopic.id)
    return render_template(
        "learn/checkpoint_result.html",
        subtopic=subtopic,
        correct=state["correct"],
        total=total,
        passed=state["passed"],
        progress=progress,
    )
