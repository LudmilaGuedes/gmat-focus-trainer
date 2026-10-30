"""Practice mode. A practice run has a scope (one subtopic, a content area,
a section, or today's focus list); each question comes from a subtopic of
the scope — weighted toward weak / below-target subtopics — at THAT
subtopic's current level."""

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from app.extensions import db
from app.models.question_bank import Question
from app.models.sessions import StudySession
from app.models.taxonomy import ContentArea, Section, Subtopic
from app.routes._answering import answer_breakdown, form_guessed, parse_answer, seconds_since, stamp
from app.services.adaptive_study import (
    get_lesson_for_subtopic,
    get_or_create_progress,
    is_weak,
    progress_map,
    record_attempt,
    target_seconds,
    weak_subtopic_ids,
)
from app.services.grading import build_answer_groups, grade_answer
from app.services.question_selector import pick_subtopic_for_practice, select_question
from app.services.reporting import save_session_report
from app.services.srs import ERROR_REASONS, is_known
from app.services.study_plan import target_level, todays_activity
from app.timeutils import utcnow

bp = Blueprint("study", __name__, url_prefix="/study")

RECENT_SERVED_LIMIT = 25


def _start(subtopic_ids, label, back_url, goal=None, done_before=0):
    if not subtopic_ids:
        abort(404)
    _close_session_if_any()
    study_session = StudySession(mode="study")
    db.session.add(study_session)
    db.session.commit()
    session["practice"] = {
        "ids": list(subtopic_ids),
        "label": label,
        "back": back_url,
        "goal": goal,
        "done_before": done_before,
        "count": 0,
        "correct": 0,
        "served": [],
        "current_qid": None,
        "shown_at": None,
        "session_id": study_session.id,
        "last": None,
    }
    return redirect(url_for("study.question"))


def _close_session_if_any():
    state = session.get("practice")
    if not state:
        return None
    study_session = StudySession.query.get(state.get("session_id"))
    if study_session and study_session.ended_at is None:
        study_session.ended_at = utcnow()
        db.session.commit()
        save_session_report(study_session.id)
    return study_session


@bp.route("/subtopic/<int:subtopic_id>")
def subtopic(subtopic_id):
    s = Subtopic.query.get_or_404(subtopic_id)
    return _start([s.id], s.name, url_for("content.content_detail", content_area_id=s.content_area_id))


@bp.route("/area/<int:content_area_id>")
def area(content_area_id):
    ca = ContentArea.query.get_or_404(content_area_id)
    ids = [s.id for s in ca.subtopics]
    return _start(ids, ca.name, url_for("content.content_detail", content_area_id=ca.id))


@bp.route("/section/<section_code>")
def section(section_code):
    sec = Section.query.filter_by(code=section_code).first_or_404()
    ids = [s.id for ca in sec.content_areas for s in ca.subtopics]
    return _start(ids, f"{sec.name} (misto)", url_for("content.section_detail", section_code=sec.code))


@bp.route("/focus")
def focus():
    raw = request.args.get("subtopics", "")
    ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    ids = [s.id for s in Subtopic.query.filter(Subtopic.id.in_(ids)).all()] if ids else []
    goal = request.args.get("goal", type=int)
    # Coming back after "Encerrar": keep counting toward today's goal.
    done_before = todays_activity()["focused_practice"] if goal else 0
    return _start(ids, "Prática focada de hoje", url_for("home.index"), goal=goal, done_before=done_before)


@bp.route("/question")
def question():
    state = session.get("practice")
    if not state:
        return redirect(url_for("home.index"))

    q = Question.query.get(state["current_qid"]) if state.get("current_qid") else None
    if q is None:
        progress_by_id = progress_map(state["ids"])
        weak = weak_subtopic_ids(state["ids"]) if len(state["ids"]) > 1 else []
        tried = set()
        while q is None and len(tried) < len(state["ids"]):
            remaining = [sid for sid in state["ids"] if sid not in tried]
            sid = pick_subtopic_for_practice(remaining, progress_by_id, target_level(), weak)
            tried.add(sid)
            level = get_or_create_progress(sid).level
            # Never repeat a question in practice: if this subtopic has nothing unseen in the
            # last few days, try the other subtopics of the run.
            q = select_question(sid, level, exclude_ids=state["served"], allow_repeat=False)
        if q is None:
            return render_template("study/exhausted.html", state=state,
                                   subtopics=Subtopic.query.filter(Subtopic.id.in_(state["ids"])).all())
        state["current_qid"] = q.id
        state["shown_at"] = stamp()
        session["practice"] = state

    return render_template(
        "study/practice.html",
        state=state,
        question=q,
        answer_groups=build_answer_groups(q),
        progress=get_or_create_progress(q.subtopic_id),
        target_seconds=target_seconds(q),
    )


@bp.route("/answer", methods=["POST"])
def answer():
    state = session.get("practice")
    if not state or not state.get("current_qid"):
        return redirect(url_for("home.index"))
    q = Question.query.get_or_404(state["current_qid"])
    if request.form.get("question_id") != str(q.id):
        abort(400)

    selected = parse_answer(q)
    is_correct = grade_answer(q, selected)
    elapsed = seconds_since(state.get("shown_at"))
    guessed = form_guessed()
    result = record_attempt(q, state["session_id"], selected, is_correct, mode="study",
                            time_spent_seconds=elapsed, guessed=guessed)

    state["served"] = (state["served"] + [q.id])[-RECENT_SERVED_LIMIT:]
    state["count"] += 1
    state["correct"] += 1 if is_correct else 0
    state["current_qid"] = None
    state["last"] = {
        "qid": q.id,
        "correct": is_correct,
        "selected": selected,
        "seconds": elapsed,
        "guessed": guessed,
        "level_change": list(result["level_change"]) if result["level_change"] else None,
        "queued": bool(result["review_item"]),
    }
    session["practice"] = state
    return redirect(url_for("study.feedback"))


@bp.route("/feedback")
def feedback():
    state = session.get("practice")
    if not state or not state.get("last"):
        return redirect(url_for("home.index"))
    last = state["last"]
    q = Question.query.get_or_404(last["qid"])
    weak = is_weak(q.subtopic_id)
    goal_reached = bool(state.get("goal") and state.get("done_before", 0) + state["count"] >= state["goal"])
    return render_template(
        "study/feedback.html",
        state=state,
        question=q,
        last=last,
        breakdown=answer_breakdown(q, last["selected"]),
        target_seconds=target_seconds(q),
        weak=weak,
        lesson=get_lesson_for_subtopic(q.subtopic_id) if weak or not last["correct"] else None,
        progress=get_or_create_progress(q.subtopic_id),
        reasons=ERROR_REASONS,
        goal_reached=goal_reached,
        known=is_known(q.id),
    )


@bp.route("/end", methods=["POST", "GET"])
def end_session():
    study_session = _close_session_if_any()
    session.pop("practice", None)
    if study_session is None:
        return redirect(url_for("home.index"))
    return redirect(url_for("reports.session_report", session_id=study_session.id))
