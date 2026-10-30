"""End-of-session report: performance by content area and level, plus time,
for everything answered in one session (practice, review, checkpoint or
mock exam alike — they all log to the same `attempts` table)."""

from app.extensions import db
from app.models.sessions import Attempt, SessionReport
from app.timeutils import utcnow


def generate_session_summary(session_id):
    attempts = Attempt.query.filter_by(session_id=session_id).all()
    by_content = {}
    for attempt in attempts:
        content_area = attempt.question.content_area
        entry = by_content.setdefault(
            content_area.id,
            {
                "content_area_id": content_area.id,
                "content_area_name": content_area.name,
                "section_name": content_area.section.name,
                "attempts": 0,
                "correct": 0,
                "seconds": 0,
                "by_difficulty": {},
            },
        )
        entry["attempts"] += 1
        entry["correct"] += 1 if attempt.is_correct else 0
        entry["seconds"] += attempt.time_spent_seconds or 0
        diff_entry = entry["by_difficulty"].setdefault(
            str(attempt.difficulty_at_attempt), {"attempts": 0, "correct": 0}
        )
        diff_entry["attempts"] += 1
        diff_entry["correct"] += 1 if attempt.is_correct else 0

    total_seconds = sum(a.time_spent_seconds or 0 for a in attempts)
    timed = [a for a in attempts if a.time_spent_seconds]
    return {
        "content_areas": list(by_content.values()),
        "total_attempts": len(attempts),
        "total_correct": sum(1 for a in attempts if a.is_correct),
        "total_seconds": total_seconds,
        "avg_seconds": round(total_seconds / len(timed)) if timed else None,
        "wrong_question_ids": [a.question_id for a in attempts if not a.is_correct],
    }


def save_session_report(session_id):
    summary = generate_session_summary(session_id)
    report = SessionReport.query.filter_by(session_id=session_id).first()
    if report is None:
        report = SessionReport(session_id=session_id, summary_json=summary)
        db.session.add(report)
    else:
        report.summary_json = summary
        report.generated_at = utcnow()
    db.session.commit()
    return report
