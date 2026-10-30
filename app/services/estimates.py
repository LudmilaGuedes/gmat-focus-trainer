"""The "where am I" numbers: estimated score per section and total, from all
first attempts in practice, checkpoints and mock exams (recency-weighted),
optionally calibrated against official practice-exam scores you entered."""

from datetime import timedelta

from app.extensions import db
from app.levels import total_score_from_sections
from app.models.progress import ExternalScore, ScoreSnapshot
from app.models.question_bank import Question
from app.models.sessions import ABILITY_MODES, Attempt
from app.models.settings import AppSetting
from app.models.taxonomy import ContentArea, Section, Subtopic
from app.services.ability import guessing_for, section_estimate
from app.timeutils import local_today, utcnow

HALF_LIFE_DAYS = 30
WINDOW_DAYS = 180
MAX_RESPONSES = 200
RELIABLE_MIN_RESPONSES = 15
MIN_RESPONSES_FOR_TOTAL = 5  # per section; below this the total would mostly be the prior


def _section_responses(section_id, now=None):
    now = now or utcnow()
    rows = (
        Attempt.query.join(Question, Attempt.question_id == Question.id)
        .join(Subtopic, Question.subtopic_id == Subtopic.id)
        .join(ContentArea, Subtopic.content_area_id == ContentArea.id)
        .filter(
            ContentArea.section_id == section_id,
            Attempt.mode.in_(ABILITY_MODES),
            Attempt.answered_at >= now - timedelta(days=WINDOW_DAYS),
        )
        .order_by(Attempt.answered_at.asc())
        .all()
    )
    seen, responses = set(), []
    for attempt in rows:
        # Only the first attempt at each question: a repeat is memory, not ability.
        if attempt.question_id in seen:
            continue
        seen.add(attempt.question_id)
        age_days = max(0.0, (now - attempt.answered_at).total_seconds() / 86400)
        weight = 0.5 ** (age_days / HALF_LIFE_DAYS)
        responses.append(
            (attempt.difficulty_at_attempt, attempt.is_correct,
             guessing_for(attempt.question.question_type.code), weight)
        )
    return responses[-MAX_RESPONSES:]


def calibration_offset():
    """Mean (official - app) over the last 3 official scores that have an app snapshot."""
    rows = (
        ExternalScore.query.filter(ExternalScore.app_estimate_total.isnot(None))
        .order_by(ExternalScore.taken_on.desc())
        .limit(3)
        .all()
    )
    if not rows:
        return 0
    return round(sum(r.total - r.app_estimate_total for r in rows) / len(rows))


def current_estimate(now=None):
    sections = {}
    for section in Section.query.order_by(Section.order).all():
        responses = _section_responses(section.id, now)
        est = section_estimate(responses)
        est["n"] = len(responses)
        est["reliable"] = len(responses) >= RELIABLE_MIN_RESPONSES
        est["name"] = section.name
        sections[section.code] = est

    def _total(key):
        return total_score_from_sections(*(sections.get(c, {}).get(key, 60) for c in ("QR", "VR", "DI")))

    raw_total = _total("score")
    offset = calibration_offset() if AppSetting.get_bool("use_calibration") else 0
    offset = int(round(offset / 10.0)) * 10  # stay on the official 205, 215, ... grid

    def _shift(value):
        return max(205, min(805, value + offset))

    return {
        "sections": sections,
        "raw_total": raw_total,
        "total": _shift(raw_total),
        "low": _shift(_total("low")),
        "high": _shift(_total("high")),
        "offset": offset,
        "reliable": all(s["reliable"] for s in sections.values()) if sections else False,
        "complete": bool(sections) and all(s["n"] >= MIN_RESPONSES_FOR_TOTAL for s in sections.values()),
        "n": sum(s["n"] for s in sections.values()),
    }


def snapshot_today(estimate=None):
    estimate = estimate or current_estimate()
    if not estimate["complete"]:
        return None
    today = local_today()
    row = ScoreSnapshot.query.filter_by(day=today).first()
    if row is None:
        row = ScoreSnapshot(day=today)
        db.session.add(row)
    secs = estimate["sections"]
    row.qr = secs.get("QR", {}).get("score")
    row.vr = secs.get("VR", {}).get("score")
    row.di = secs.get("DI", {}).get("score")
    row.total = estimate["total"]
    db.session.commit()
    return row
