"""Mock exams that behave like the GMAT Focus Edition:

* full exam (3 sections in the order you choose, one optional 10-min break
  after section 1 or 2) or a single timed section;
* 45 min per section, adaptive (CAT) difficulty, no difficulty shown;
* bookmark questions and, at the end of each section while time remains,
  review them and change up to 3 answers;
* unanswered questions are penalized, like the real test;
* after the exam: question-by-question review, pacing analysis.

All CAT state is derived from the DB (MockExamAttempt rows); only the
currently displayed question id and its display time live in the session.
Answers are logged to the generic `attempts` table (and wrong ones to the
review queue) when a section is closed, so edits are taken into account.
A mock NEVER changes study-mode levels.
"""

from datetime import datetime, timedelta
from itertools import permutations

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from app.extensions import db
from app.levels import TARGET_SECONDS_BY_SECTION, total_score_from_sections
from app.models.mock_exam import (
    BREAK_SECONDS,
    MAX_ANSWER_EDITS_PER_SECTION,
    SECTION_QUESTION_COUNTS,
    MockExam,
    MockExamAttempt,
    MockExamResult,
    MockExamSection,
)
from app.models.progress import ExternalScore
from app.models.sessions import StudySession
from app.models.taxonomy import Section
from app.routes._answering import answer_breakdown, parse_answer, seconds_since, stamp
from app.services.ability import guessing_for
from app.services.adaptive_study import record_attempt
from app.services.cat_engine import ThetaCat
from app.services.grading import build_answer_groups, grade_answer
from app.services.question_selector import select_mock_question
from app.services.reporting import save_session_report
from app.timeutils import utcnow

bp = Blueprint("mock_exam", __name__, url_prefix="/mock-exam")

SECTION_CODES = ("QR", "VR", "DI")


def _keys(msec_id):
    return f"mock_q_{msec_id}", f"mock_shown_{msec_id}"


def _load(mock_exam_id, mock_section_id):
    mock_exam = MockExam.query.get_or_404(mock_exam_id)
    msec = MockExamSection.query.get_or_404(mock_section_id)
    if msec.mock_exam_id != mock_exam.id:
        abort(404)
    return mock_exam, msec


def _remaining_seconds(msec):
    if msec.started_at is None:
        return msec.time_limit_seconds
    # While paused the clock is frozen at paused_at; past pauses are subtracted.
    elapsed = ((msec.paused_at or utcnow()) - msec.started_at).total_seconds() - msec.paused_seconds
    return max(0, msec.time_limit_seconds - int(elapsed))


def _paused_redirect(mock_exam, msec):
    """Every in-section screen bounces to the pause screen while paused."""
    if msec.paused_at is not None and msec.ended_at is None:
        return redirect(url_for("mock_exam.paused", mock_exam_id=mock_exam.id, mock_section_id=msec.id))
    return None


def _cat_for(msec):
    return ThetaCat(
        (a.difficulty_presented, a.is_correct, guessing_for(a.question.question_type.code))
        for a in msec.attempts
    )


# ---------------------------------------------------------------- start


@bp.route("/start")
def start_form():
    orders = [" → ".join(p) for p in permutations(SECTION_CODES)]
    in_progress = MockExam.query.filter_by(status="in_progress").order_by(MockExam.started_at.desc()).first()
    return render_template("mock_exam/start.html", orders=orders, in_progress=in_progress,
                           counts=SECTION_QUESTION_COUNTS)


@bp.route("/start", methods=["POST"])
def start():
    sections = {s.code: s for s in Section.query.all()}
    if not sections:
        abort(400, "Taxonomia não carregada — rode scripts/seed_taxonomy.py primeiro.")
    kind = request.form.get("kind", "full")
    if kind == "section":
        codes = [request.form.get("section_code", "QR")]
    else:
        kind = "full"
        codes = [c.strip() for c in request.form.get("order", "QR → VR → DI").split("→")]
    if not codes or any(c not in sections for c in codes):
        abort(400)

    # Abandon any exam left half-way.
    for old in MockExam.query.filter_by(status="in_progress").all():
        old.status = "abandoned"

    study_session = StudySession(mode="mock_exam")
    db.session.add(study_session)
    db.session.flush()
    mock_exam = MockExam(session_id=study_session.id, kind=kind)
    db.session.add(mock_exam)
    db.session.flush()
    for order, code in enumerate(codes):
        db.session.add(MockExamSection(
            mock_exam_id=mock_exam.id, section_id=sections[code].id, order=order,
            questions_planned=SECTION_QUESTION_COUNTS.get(code, 20),
        ))
    db.session.commit()
    first = min(mock_exam.sections, key=lambda s: s.order)
    return redirect(url_for("mock_exam.section_intro", mock_exam_id=mock_exam.id, mock_section_id=first.id))


@bp.route("/<int:mock_exam_id>/resume")
def resume(mock_exam_id):
    mock_exam = MockExam.query.get_or_404(mock_exam_id)
    if mock_exam.status != "in_progress":
        return redirect(url_for("mock_exam.results", mock_exam_id=mock_exam.id))
    return _advance(mock_exam)


# ---------------------------------------------------------------- section flow


@bp.route("/<int:mock_exam_id>/section/<int:mock_section_id>/intro")
def section_intro(mock_exam_id, mock_section_id):
    mock_exam, msec = _load(mock_exam_id, mock_section_id)
    if msec.started_at is not None:
        return redirect(url_for("mock_exam.section_view", mock_exam_id=mock_exam.id, mock_section_id=msec.id))
    return render_template("mock_exam/intro.html", mock_exam=mock_exam, msec=msec)


@bp.route("/<int:mock_exam_id>/section/<int:mock_section_id>")
def section_view(mock_exam_id, mock_section_id):
    mock_exam, msec = _load(mock_exam_id, mock_section_id)
    if msec.ended_at is not None:
        return _advance(mock_exam)
    if msec.started_at is None:
        msec.started_at = utcnow()
        db.session.commit()
    if (paused := _paused_redirect(mock_exam, msec)) is not None:
        return paused
    if _remaining_seconds(msec) <= 0:
        return _finalize_section(mock_exam, msec)

    answered = len(msec.attempts)
    if answered >= msec.questions_planned:
        return redirect(url_for("mock_exam.section_review", mock_exam_id=mock_exam.id, mock_section_id=msec.id))

    q_key, shown_key = _keys(msec.id)
    from app.models.question_bank import Question

    question = Question.query.get(session.get(q_key)) if session.get(q_key) else None
    if question is None:
        served = [a.question for a in msec.attempts]
        question = select_mock_question(msec.section, _cat_for(msec).next_level(), served)
        if question is None:
            # Bank exhausted for this section: shorten it instead of penalizing.
            msec.questions_planned = answered
            db.session.commit()
            return redirect(url_for("mock_exam.section_review", mock_exam_id=mock_exam.id, mock_section_id=msec.id))
        session[q_key] = question.id
        session[shown_key] = stamp()

    return render_template(
        "mock_exam/section.html",
        mock_exam=mock_exam,
        msec=msec,
        question=question,
        answer_groups=build_answer_groups(question),
        number=answered + 1,
        remaining_seconds=_remaining_seconds(msec),
        target_seconds=TARGET_SECONDS_BY_SECTION.get(msec.section.code, 120),
    )


@bp.route("/<int:mock_exam_id>/section/<int:mock_section_id>/answer", methods=["POST"])
def section_answer(mock_exam_id, mock_section_id):
    mock_exam, msec = _load(mock_exam_id, mock_section_id)
    if msec.ended_at is not None:
        return _advance(mock_exam)
    if (paused := _paused_redirect(mock_exam, msec)) is not None:
        return paused
    q_key, shown_key = _keys(msec.id)
    from app.models.question_bank import Question

    question = Question.query.get(session.get(q_key)) if session.get(q_key) else None
    if question is None or request.form.get("question_id") != str(question.id):
        return redirect(url_for("mock_exam.section_view", mock_exam_id=mock_exam.id, mock_section_id=msec.id))

    selected = parse_answer(question)
    is_correct = grade_answer(question, selected)
    cat = _cat_for(msec)
    cat.record_response(question.difficulty, is_correct, guessing_for(question.question_type.code))
    db.session.add(MockExamAttempt(
        mock_exam_section_id=msec.id,
        question_id=question.id,
        sequence_number=len(msec.attempts) + 1,
        difficulty_presented=question.difficulty,
        is_correct=is_correct,
        selected_answer_json=selected,
        time_spent_seconds=seconds_since(session.get(shown_key)),
        running_ability_estimate=cat.theta(),
        bookmarked=request.form.get("bookmark") == "1",
    ))
    db.session.commit()
    session.pop(q_key, None)
    session.pop(shown_key, None)
    return redirect(url_for("mock_exam.section_view", mock_exam_id=mock_exam.id, mock_section_id=msec.id))


@bp.route("/<int:mock_exam_id>/section/<int:mock_section_id>/review")
def section_review(mock_exam_id, mock_section_id):
    """Question Review & Edit screen (end of section, while time remains)."""
    mock_exam, msec = _load(mock_exam_id, mock_section_id)
    if msec.ended_at is not None:
        return _advance(mock_exam)
    if (paused := _paused_redirect(mock_exam, msec)) is not None:
        return paused
    if _remaining_seconds(msec) <= 0:
        return _finalize_section(mock_exam, msec)
    return render_template(
        "mock_exam/review.html", mock_exam=mock_exam, msec=msec, remaining_seconds=_remaining_seconds(msec),
        edits_left=MAX_ANSWER_EDITS_PER_SECTION - msec.edits_used,
    )


@bp.route("/<int:mock_exam_id>/section/<int:mock_section_id>/bookmark/<int:attempt_id>", methods=["POST"])
def toggle_bookmark(mock_exam_id, mock_section_id, attempt_id):
    mock_exam, msec = _load(mock_exam_id, mock_section_id)
    attempt = MockExamAttempt.query.get_or_404(attempt_id)
    if attempt.mock_exam_section_id != msec.id:
        abort(404)
    if (paused := _paused_redirect(mock_exam, msec)) is not None:
        return paused
    attempt.bookmarked = not attempt.bookmarked
    db.session.commit()
    return redirect(url_for("mock_exam.section_review", mock_exam_id=mock_exam.id, mock_section_id=msec.id))


@bp.route("/<int:mock_exam_id>/section/<int:mock_section_id>/edit/<int:attempt_id>", methods=["GET", "POST"])
def edit_answer(mock_exam_id, mock_section_id, attempt_id):
    mock_exam, msec = _load(mock_exam_id, mock_section_id)
    attempt = MockExamAttempt.query.get_or_404(attempt_id)
    if attempt.mock_exam_section_id != msec.id or msec.ended_at is not None:
        abort(404)
    if (paused := _paused_redirect(mock_exam, msec)) is not None:
        return paused
    if _remaining_seconds(msec) <= 0:
        return _finalize_section(mock_exam, msec)
    question = attempt.question
    edits_left = MAX_ANSWER_EDITS_PER_SECTION - msec.edits_used

    if request.method == "POST":
        selected = parse_answer(question)
        changed = selected != attempt.selected_answer_json
        if changed and (attempt.edited or edits_left > 0):
            if not attempt.edited:
                msec.edits_used += 1
            attempt.edited = True
            attempt.selected_answer_json = selected
            attempt.is_correct = grade_answer(question, selected)
            db.session.commit()
        return redirect(url_for("mock_exam.section_review", mock_exam_id=mock_exam.id, mock_section_id=msec.id))

    return render_template(
        "mock_exam/edit.html", mock_exam=mock_exam, msec=msec, attempt=attempt, question=question,
        answer_groups=build_answer_groups(question), selected_answer=attempt.selected_answer_json or {},
        remaining_seconds=_remaining_seconds(msec), edits_left=edits_left,
    )


@bp.route("/<int:mock_exam_id>/section/<int:mock_section_id>/finish", methods=["POST"])
def finish_section(mock_exam_id, mock_section_id):
    mock_exam, msec = _load(mock_exam_id, mock_section_id)
    if (paused := _paused_redirect(mock_exam, msec)) is not None:
        return paused
    return _finalize_section(mock_exam, msec)


@bp.route("/<int:mock_exam_id>/section/<int:mock_section_id>/timeout")
def section_timeout(mock_exam_id, mock_section_id):
    mock_exam, msec = _load(mock_exam_id, mock_section_id)
    if (paused := _paused_redirect(mock_exam, msec)) is not None:
        return paused
    if msec.ended_at is None and _remaining_seconds(msec) > 5:
        # Client clock drift: the server is the authority on time.
        return redirect(url_for("mock_exam.section_view", mock_exam_id=mock_exam.id, mock_section_id=msec.id))
    return _finalize_section(mock_exam, msec)


@bp.route("/<int:mock_exam_id>/section/<int:mock_section_id>/pause", methods=["POST"])
def pause(mock_exam_id, mock_section_id):
    """Freeze the section clock. Not something the real exam allows, so the
    mock is flagged (pause_count) and the results say so."""
    mock_exam, msec = _load(mock_exam_id, mock_section_id)
    if msec.ended_at is not None:
        return _advance(mock_exam)
    if msec.started_at is not None and msec.paused_at is None and _remaining_seconds(msec) > 0:
        msec.paused_at = utcnow()
        mock_exam.pause_count += 1
        db.session.commit()
    return redirect(url_for("mock_exam.paused", mock_exam_id=mock_exam.id, mock_section_id=msec.id))


@bp.route("/<int:mock_exam_id>/section/<int:mock_section_id>/paused")
def paused(mock_exam_id, mock_section_id):
    mock_exam, msec = _load(mock_exam_id, mock_section_id)
    if msec.paused_at is None or msec.ended_at is not None:
        return _advance(mock_exam)
    return render_template("mock_exam/paused.html", mock_exam=mock_exam, msec=msec,
                           remaining_seconds=_remaining_seconds(msec))


@bp.route("/<int:mock_exam_id>/section/<int:mock_section_id>/unpause", methods=["POST"])
def unpause(mock_exam_id, mock_section_id):
    mock_exam, msec = _load(mock_exam_id, mock_section_id)
    if msec.paused_at is not None and msec.ended_at is None:
        pause_seconds = (utcnow() - msec.paused_at).total_seconds()
        msec.paused_seconds += int(pause_seconds)
        msec.paused_at = None
        db.session.commit()
        # The pause doesn't count toward the time spent on the displayed question either.
        _, shown_key = _keys(msec.id)
        if session.get(shown_key):
            shown = datetime.fromisoformat(session[shown_key]) + timedelta(seconds=pause_seconds)
            session[shown_key] = shown.isoformat()
    return _advance(mock_exam)


def _finalize_section(mock_exam, msec):
    if msec.ended_at is None:
        msec.ended_at = utcnow()
        unanswered = max(0, msec.questions_planned - len(msec.attempts))
        estimate = _cat_for(msec).final_estimate(unanswered=unanswered)
        msec.scaled_score = estimate["score"]
        msec.theta = estimate["theta"]
        db.session.commit()
        # Now that answers are final, log them (score estimate + review queue).
        for a in msec.attempts:
            record_attempt(
                a.question, mock_exam.session_id, a.selected_answer_json, a.is_correct,
                mode="mock_exam", time_spent_seconds=a.time_spent_seconds,
            )
    for key in _keys(msec.id):
        session.pop(key, None)
    return _advance(mock_exam)


def _advance(mock_exam):
    remaining = [s for s in mock_exam.sections if s.ended_at is None]
    if not remaining:
        return _finalize_exam(mock_exam)
    nxt = min(remaining, key=lambda s: s.order)
    offered = session.get(f"mock_break_offered_{mock_exam.id}", [])
    if (mock_exam.kind == "full" and not mock_exam.break_used and nxt.order in (1, 2)
            and nxt.started_at is None and nxt.order not in offered):
        return redirect(url_for("mock_exam.break_offer", mock_exam_id=mock_exam.id, mock_section_id=nxt.id))
    if nxt.started_at is None:
        return redirect(url_for("mock_exam.section_intro", mock_exam_id=mock_exam.id, mock_section_id=nxt.id))
    if (paused := _paused_redirect(mock_exam, nxt)) is not None:
        return paused
    return redirect(url_for("mock_exam.section_view", mock_exam_id=mock_exam.id, mock_section_id=nxt.id))


@bp.route("/<int:mock_exam_id>/break/<int:mock_section_id>", methods=["GET", "POST"])
def break_offer(mock_exam_id, mock_section_id):
    mock_exam, msec = _load(mock_exam_id, mock_section_id)
    key = f"mock_break_offered_{mock_exam.id}"
    session[key] = session.get(key, []) + [msec.order]
    if request.method == "POST" and request.form.get("take") == "1" and not mock_exam.break_used:
        mock_exam.break_used = True
        db.session.commit()
        return render_template("mock_exam/break.html", mock_exam=mock_exam, msec=msec, seconds=BREAK_SECONDS)
    if request.method == "POST":
        return redirect(url_for("mock_exam.section_intro", mock_exam_id=mock_exam.id, mock_section_id=msec.id))
    return render_template("mock_exam/break_offer.html", mock_exam=mock_exam, msec=msec)


def _finalize_exam(mock_exam):
    if mock_exam.result is None:
        by_code = {s.section.code: s.scaled_score for s in mock_exam.sections}
        total = None
        if all(c in by_code for c in SECTION_CODES):
            total = total_score_from_sections(by_code["QR"], by_code["VR"], by_code["DI"])
        db.session.add(MockExamResult(
            mock_exam_id=mock_exam.id, total_scaled_score=total,
            qr_scaled_score=by_code.get("QR"), vr_scaled_score=by_code.get("VR"), di_scaled_score=by_code.get("DI"),
        ))
        mock_exam.status = "completed"
        mock_exam.completed_at = utcnow()
        study_session = StudySession.query.get(mock_exam.session_id) if mock_exam.session_id else None
        if study_session and study_session.ended_at is None:
            study_session.ended_at = utcnow()
        db.session.commit()
        if mock_exam.session_id:
            save_session_report(mock_exam.session_id)
    return redirect(url_for("mock_exam.results", mock_exam_id=mock_exam.id))


# ---------------------------------------------------------------- results


@bp.route("/<int:mock_exam_id>/results")
def results(mock_exam_id):
    mock_exam = MockExam.query.get_or_404(mock_exam_id)
    sections = []
    for msec in mock_exam.sections:
        target = TARGET_SECONDS_BY_SECTION.get(msec.section.code, 120)
        attempts = list(msec.attempts)
        by_area = {}
        cumulative, pacing = 0, []
        for a in attempts:
            area = a.question.content_area.name
            entry = by_area.setdefault(area, {"total": 0, "correct": 0})
            entry["total"] += 1
            entry["correct"] += 1 if a.is_correct else 0
            cumulative += a.time_spent_seconds or 0
            pacing.append(round(cumulative / 60, 1))
        sections.append({
            "msec": msec,
            "attempts": attempts,
            "by_area": by_area,
            "target": target,
            "pacing": pacing,
            "ideal": [round(target * (i + 1) / 60, 1) for i in range(len(attempts))],
            "slow": sum(1 for a in attempts if (a.time_spent_seconds or 0) > 1.6 * target),
            "unanswered": max(0, msec.questions_planned - len(attempts)) if msec.ended_at else 0,
            "missed_subtopics": sorted({a.question.subtopic for a in attempts if not a.is_correct},
                                       key=lambda s: s.name),
        })
    return render_template("mock_exam/results.html", mock_exam=mock_exam, result=mock_exam.result, sections=sections)


@bp.route("/<int:mock_exam_id>/question/<int:attempt_id>")
def review_question(mock_exam_id, attempt_id):
    mock_exam = MockExam.query.get_or_404(mock_exam_id)
    attempt = MockExamAttempt.query.get_or_404(attempt_id)
    if attempt.mock_exam_section.mock_exam_id != mock_exam.id or mock_exam.status == "in_progress":
        abort(404)
    return render_template(
        "mock_exam/question_review.html", mock_exam=mock_exam, attempt=attempt, question=attempt.question,
        breakdown=answer_breakdown(attempt.question, attempt.selected_answer_json),
        target_seconds=TARGET_SECONDS_BY_SECTION.get(attempt.mock_exam_section.section.code, 120),
    )


@bp.route("/history")
def history():
    results_list = (
        MockExamResult.query.join(MockExam)
        .filter(MockExam.status == "completed")
        .order_by(MockExamResult.completed_at)
        .all()
    )
    full = [r for r in results_list if r.total_scaled_score is not None]
    officials = ExternalScore.query.order_by(ExternalScore.taken_on).all()
    in_progress = MockExam.query.filter_by(status="in_progress").order_by(MockExam.started_at.desc()).first()
    return render_template(
        "mock_exam/history.html",
        results=list(reversed(results_list)),
        chart_labels=[r.completed_at.strftime("%d/%m") for r in full],
        chart_totals=[r.total_scaled_score for r in full],
        officials=officials,
        in_progress=in_progress,
    )
