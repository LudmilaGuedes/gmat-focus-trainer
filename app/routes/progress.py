"""Where am I: estimated score (per section, with uncertainty), its history,
official practice-exam scores (calibration), level history, and stats by
level / question type / time."""

from datetime import date, timedelta

from flask import Blueprint, abort, redirect, render_template, request, url_for

from app.extensions import db
from app.levels import LEVELS
from app.models.mock_exam import MockExam, MockExamResult
from app.models.progress import ExternalScore, LevelAdjustment, ScoreSnapshot
from app.models.question_bank import Question
from app.models.sessions import ABILITY_MODES, Attempt
from app.services.estimates import current_estimate, snapshot_today
from app.services.study_plan import section_level_summary, target_score, track_overview
from app.timeutils import local_today, start_of_local_day

bp = Blueprint("progress", __name__, url_prefix="/progress")


def _stats():
    attempts = Attempt.query.filter(Attempt.mode.in_(ABILITY_MODES)).all()
    by_level = {lvl: {"total": 0, "correct": 0, "seconds": []} for lvl in LEVELS}
    by_type = {}
    for a in attempts:
        lvl = by_level.setdefault(a.difficulty_at_attempt, {"total": 0, "correct": 0, "seconds": []})
        lvl["total"] += 1
        lvl["correct"] += 1 if a.is_correct else 0
        if a.time_spent_seconds:
            lvl["seconds"].append(a.time_spent_seconds)
        tname = a.question.question_type.name
        t = by_type.setdefault(tname, {"total": 0, "correct": 0, "seconds": []})
        t["total"] += 1
        t["correct"] += 1 if a.is_correct else 0
        if a.time_spent_seconds:
            t["seconds"].append(a.time_spent_seconds)
    for bucket in list(by_level.values()) + list(by_type.values()):
        s = bucket.pop("seconds")
        bucket["avg_seconds"] = round(sum(s) / len(s)) if s else None
    return by_level, by_type


def _daily_activity(days=28):
    today = local_today()
    rows = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        start = start_of_local_day(day)
        end = start + timedelta(days=1)
        atts = Attempt.query.filter(Attempt.answered_at >= start, Attempt.answered_at < end).all()
        rows.append({
            "label": day.strftime("%d/%m"),
            "questions": len(atts),
            "minutes": round(sum(a.time_spent_seconds or 0 for a in atts) / 60),
        })
    return rows


@bp.route("/")
def index():
    estimate = current_estimate()
    snapshot_today(estimate)
    overview = track_overview()
    snapshots = ScoreSnapshot.query.order_by(ScoreSnapshot.day).all()
    mocks = (
        MockExamResult.query.join(MockExam)
        .filter(MockExam.status == "completed", MockExamResult.total_scaled_score.isnot(None))
        .order_by(MockExamResult.completed_at).all()
    )
    officials = ExternalScore.query.order_by(ExternalScore.taken_on).all()
    by_level, by_type = _stats()
    adjustments = LevelAdjustment.query.order_by(LevelAdjustment.created_at.desc()).limit(25).all()
    return render_template(
        "progress/index.html",
        estimate=estimate,
        target=target_score(),
        overview=overview,
        section_levels=section_level_summary(overview),
        snapshots=snapshots,
        mocks=mocks,
        officials=officials,
        by_level=by_level,
        by_type=by_type,
        adjustments=adjustments,
        activity=_daily_activity(),
        today=local_today(),
        total_questions=Question.query.filter_by(status="active").count(),
        attempted=Attempt.query.with_entities(Attempt.question_id).distinct().count(),
    )


@bp.route("/official", methods=["POST"])
def add_official():
    try:
        taken_on = date.fromisoformat(request.form.get("taken_on") or local_today().isoformat())
        total = int(request.form["total"])
    except (KeyError, ValueError):
        abort(400)
    if not 205 <= total <= 805:
        abort(400)

    def _opt(name):
        value = request.form.get(name, "").strip()
        return int(value) if value.isdigit() else None

    estimate = current_estimate()
    db.session.add(ExternalScore(
        taken_on=taken_on,
        source=(request.form.get("source") or "Official Practice Exam").strip(),
        total=total, qr=_opt("qr"), vr=_opt("vr"), di=_opt("di"),
        # Only snapshot the app's estimate when it rests on enough data to be comparable.
        app_estimate_total=estimate["raw_total"] if estimate["n"] >= 30 else None,
        notes=(request.form.get("notes") or "").strip() or None,
    ))
    db.session.commit()
    return redirect(url_for("progress.index") + "#oficiais")


@bp.route("/official/<int:score_id>/delete", methods=["POST"])
def delete_official(score_id):
    row = ExternalScore.query.get_or_404(score_id)
    db.session.delete(row)
    db.session.commit()
    return redirect(url_for("progress.index") + "#oficiais")
