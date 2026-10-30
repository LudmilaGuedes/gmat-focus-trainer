from flask import Blueprint, render_template

from app.models.sessions import SessionReport, StudySession
from app.services.reporting import generate_session_summary

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.route("/session/<int:session_id>")
def session_report(session_id):
    study_session = StudySession.query.get_or_404(session_id)
    report = SessionReport.query.filter_by(session_id=session_id).first()
    summary = report.summary_json if report else generate_session_summary(session_id)
    return render_template("reports/session_report.html", study_session=study_session, summary=summary)
