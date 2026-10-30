from flask import Blueprint, abort, redirect, render_template, request, url_for

from app.levels import LEVELS
from app.models.progress import LevelAdjustment, SubtopicLevelStat
from app.models.question_bank import Question
from app.models.taxonomy import ContentArea, Section, Subtopic
from app.services.adaptive_study import apply_manual_level_adjustment, is_weak, progress_map, recent_subtopic_accuracy
from app.services.study_plan import target_level

bp = Blueprint("content", __name__)


@bp.route("/conteudos")
def sections():
    return render_template("content/sections.html", sections=Section.query.order_by(Section.order).all())


def _subtopic_rows(subtopics):
    progress_by_id = progress_map([s.id for s in subtopics])
    rows = []
    for s in subtopics:
        p = progress_by_id.get(s.id)
        correct, total = recent_subtopic_accuracy(s.id)
        counts = {lvl: 0 for lvl in LEVELS}
        for q in Question.query.filter_by(subtopic_id=s.id, status="active").all():
            counts[q.difficulty] = counts.get(q.difficulty, 0) + 1
        rows.append({
            "subtopic": s, "progress": p, "level": p.level if p else 1, "status": p.status if p else "new",
            "recent_correct": correct, "recent_total": total, "weak": is_weak(s.id) if p else False,
            "counts": counts,
        })
    return rows


@bp.route("/section/<section_code>")
def section_detail(section_code):
    section = Section.query.filter_by(code=section_code).first_or_404()
    content_areas = ContentArea.query.filter_by(section_id=section.id).order_by(ContentArea.order).all()
    rows_by_area = {ca.id: _subtopic_rows(ca.subtopics) for ca in content_areas}
    return render_template(
        "content/section.html", section=section, content_areas=content_areas, rows_by_area=rows_by_area,
        target_level=target_level(),
    )


@bp.route("/content/<int:content_area_id>")
def content_detail(content_area_id):
    content_area = ContentArea.query.get_or_404(content_area_id)
    rows = _subtopic_rows(content_area.subtopics)
    stats = {}
    for s in content_area.subtopics:
        for st in SubtopicLevelStat.query.filter_by(subtopic_id=s.id).all():
            entry = stats.setdefault(st.level, {"attempts": 0, "correct": 0})
            entry["attempts"] += st.attempts_count
            entry["correct"] += st.correct_count
    adjustments = (
        LevelAdjustment.query.filter(LevelAdjustment.subtopic_id.in_([s.id for s in content_area.subtopics]))
        .order_by(LevelAdjustment.created_at.desc())
        .limit(12)
        .all()
    )
    return render_template(
        "content/detail.html",
        content_area=content_area,
        rows=rows,
        stats=stats,
        levels=LEVELS,
        adjustments=adjustments,
        target_level=target_level(),
    )


@bp.route("/subtopic/<int:subtopic_id>/level", methods=["POST"])
def set_level(subtopic_id):
    subtopic = Subtopic.query.get_or_404(subtopic_id)
    try:
        new_level = int(request.form.get("new_level", ""))
    except ValueError:
        abort(400)
    if new_level not in LEVELS:
        abort(400)
    reason = request.form.get("reason", "").strip() or None
    lock = request.form.get("lock") == "1"
    apply_manual_level_adjustment(subtopic.id, new_level, reason_text=reason, lock=lock,
                                  source_mock_exam_id=request.form.get("mock_exam_id", type=int))
    return redirect(request.form.get("next") or url_for("content.content_detail", content_area_id=subtopic.content_area_id))
