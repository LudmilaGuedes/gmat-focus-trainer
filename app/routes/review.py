"""Spaced review session (/review) and the error notebook (/review/errors)."""

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from app.extensions import db
from app.models.progress import ReviewItem
from app.models.question_bank import Question
from app.models.sessions import StudySession
from app.models.taxonomy import ContentArea, Section, Subtopic
from app.routes._answering import answer_breakdown, parse_answer, seconds_since, stamp
from app.services import srs
from app.services.adaptive_study import get_lesson_for_subtopic, record_attempt, target_seconds
from app.services.grading import build_answer_groups, grade_answer
from app.timeutils import utcnow

bp = Blueprint("review", __name__, url_prefix="/review")

MAX_QUEUE = 40


@bp.route("/")
def start():
    due = srs.due_items_query().order_by(ReviewItem.due_at).all()
    # Interleave: questions and flashcards mixed, oldest-due first, capped.
    queue = [i.id for i in due][:MAX_QUEUE]
    if not queue:
        return render_template("review/empty.html", next_due=_next_due())
    study_session = StudySession(mode="review")
    db.session.add(study_session)
    db.session.commit()
    session["review"] = {
        "queue": queue, "idx": 0, "correct": 0, "done": 0, "session_id": study_session.id,
        "shown_at": None, "last": None,
    }
    return redirect(url_for("review.item"))


def _next_due():
    item = ReviewItem.query.filter(ReviewItem.graduated.is_(False)).order_by(ReviewItem.due_at).first()
    return item.due_at if item else None


def _current():
    state = session.get("review")
    if not state or state["idx"] >= len(state["queue"]):
        return state, None
    return state, ReviewItem.query.get(state["queue"][state["idx"]])


@bp.route("/item")
def item():
    state, current = _current()
    if state is None:
        return redirect(url_for("review.start"))
    if current is None:
        return _finish(state)
    if not state.get("shown_at"):
        state["shown_at"] = stamp()
        session["review"] = state
    common = {"state": state, "item": current, "position": state["idx"] + 1, "total": len(state["queue"]),
              "reasons": srs.ERROR_REASONS}
    if current.item_type == "flashcard":
        return render_template("review/flashcard.html", card=current.flashcard, **common)
    question = current.question
    return render_template(
        "review/question.html", question=question, answer_groups=build_answer_groups(question),
        target_seconds=target_seconds(question), **common,
    )


def _advance(state):
    state["idx"] += 1
    state["done"] += 1
    state["shown_at"] = None
    session["review"] = state


@bp.route("/flashcard", methods=["POST"])
def flashcard_grade():
    state, current = _current()
    if current is None or current.item_type != "flashcard":
        return redirect(url_for("review.item"))
    grade = request.form.get("grade")
    if grade not in ("again", "hard", "good", "easy"):
        abort(400)
    srs.record_flashcard_grade(current, grade)
    if grade != "again":
        state["correct"] += 1
    db.session.commit()
    _advance(state)
    return redirect(url_for("review.item"))


@bp.route("/answer", methods=["POST"])
def answer():
    state, current = _current()
    if current is None or current.item_type != "question":
        return redirect(url_for("review.item"))
    question = current.question
    if request.form.get("question_id") != str(question.id):
        abort(400)
    selected = parse_answer(question)
    is_correct = grade_answer(question, selected)
    elapsed = seconds_since(state.get("shown_at"))
    record_attempt(question, state["session_id"], selected, is_correct, mode="review", time_spent_seconds=elapsed)
    srs.record_review(current, is_correct)
    db.session.commit()
    state["correct"] += 1 if is_correct else 0
    state["last"] = {"item_id": current.id, "qid": question.id, "correct": is_correct,
                     "selected": selected, "seconds": elapsed}
    _advance(state)
    return redirect(url_for("review.feedback"))


@bp.route("/feedback")
def feedback():
    state = session.get("review")
    if not state or not state.get("last"):
        return redirect(url_for("review.item"))
    last = state["last"]
    question = Question.query.get_or_404(last["qid"])
    review_item = ReviewItem.query.get(last["item_id"])
    return render_template(
        "review/feedback.html",
        state=state,
        question=question,
        last=last,
        item=review_item,
        breakdown=answer_breakdown(question, last["selected"]),
        target_seconds=target_seconds(question),
        lesson=get_lesson_for_subtopic(question.subtopic_id),
        reasons=srs.ERROR_REASONS,
        remaining=len(state["queue"]) - state["idx"],
    )


def _finish(state):
    study_session = StudySession.query.get(state["session_id"])
    if study_session and study_session.ended_at is None:
        study_session.ended_at = utcnow()
        db.session.commit()
    result = {"done": state["done"], "correct": state["correct"]}
    session.pop("review", None)
    return render_template("review/done.html", result=result, next_due=_next_due(), due_now=srs.due_count())


@bp.route("/reason/<int:question_id>", methods=["POST"])
def set_reason(question_id):
    """htmx: tag why a question was missed (and optionally a personal note)."""
    item = ReviewItem.query.filter_by(question_id=question_id).first()
    if item is None:
        item = srs.enqueue_question(question_id, origin="manual", box=0)
    reason = request.form.get("reason")
    if reason in srs.ERROR_REASONS:
        item.error_reason = reason
    note = request.form.get("note")
    if note is not None:
        item.note = note.strip() or None
    db.session.commit()
    return render_template(
        "review/_reason_saved.html", item=item, question=item.question, reasons=srs.ERROR_REASONS
    )


@bp.route("/add/<int:question_id>", methods=["POST"])
def add(question_id):
    """Manually send any question to the review queue."""
    Question.query.get_or_404(question_id)
    srs.enqueue_question(question_id, origin="manual", box=0)
    db.session.commit()
    return redirect(request.form.get("next") or url_for("questions.detail", question_id=question_id))


@bp.route("/known/<int:question_id>", methods=["POST"])
def known(question_id):
    """htmx: "Já sei" — take a question you got right out of reviews and practice."""
    Question.query.get_or_404(question_id)
    srs.mark_known(question_id)
    db.session.commit()
    return render_template("review/_known_button.html", question_id=question_id, known=True)


@bp.route("/errors")
def errors():
    section_code = request.args.get("section")
    reason = request.args.get("reason")
    query = (
        ReviewItem.query.filter(ReviewItem.item_type == "question")
        .join(Question, ReviewItem.question_id == Question.id)
        .join(Subtopic, Question.subtopic_id == Subtopic.id)
        .join(ContentArea, Subtopic.content_area_id == ContentArea.id)
        .join(Section, ContentArea.section_id == Section.id)
    )
    if section_code:
        query = query.filter(Section.code == section_code)
    if reason:
        query = query.filter(ReviewItem.error_reason == reason)
    items = query.order_by(ReviewItem.created_at.desc()).all()

    all_items = ReviewItem.query.filter_by(item_type="question").all()
    by_reason = {}
    by_subtopic = {}
    for it in all_items:
        by_reason[it.error_reason or "none"] = by_reason.get(it.error_reason or "none", 0) + 1
        name = it.question.subtopic.name
        by_subtopic[name] = by_subtopic.get(name, 0) + (it.lapses + 1)
    top_subtopics = sorted(by_subtopic.items(), key=lambda kv: -kv[1])[:8]
    return render_template(
        "review/errors.html",
        items=items,
        reasons=srs.ERROR_REASONS,
        by_reason=by_reason,
        top_subtopics=top_subtopics,
        sections=Section.query.order_by(Section.order).all(),
        section_code=section_code,
        reason=reason,
        total=len(all_items),
        graduated=sum(1 for i in all_items if i.graduated),
    )
