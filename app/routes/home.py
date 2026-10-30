from flask import Blueprint, render_template

from app.models.settings import AppSetting
from app.services.estimates import current_estimate, snapshot_today
from app.services.study_plan import build_today_plan, section_level_summary

bp = Blueprint("home", __name__)


@bp.route("/")
def index():
    estimate = current_estimate()
    snapshot_today(estimate)
    plan = build_today_plan(estimate)
    return render_template(
        "home.html",
        plan=plan,
        estimate=estimate,
        section_levels=section_level_summary(plan["overview"]),
        exam_date=AppSetting.get_date("exam_date"),
    )
