from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.levels import LEVEL_INFO, target_level_for_score
from app.models.settings import DEFAULT_SETTINGS, AppSetting

bp = Blueprint("settings", __name__, url_prefix="/settings")

EDITABLE = {
    "exam_date": "date",
    "target_score": "int",
    "daily_minutes": "int",
    "promotion_threshold_pct": "float",
    "min_attempts_before_promotion": "int",
    "auto_demotion": "bool",
    "demotion_threshold_pct": "float",
    "min_attempts_before_demotion": "int",
    "checkpoint_questions": "int",
    "checkpoint_pass_count": "int",
    "slow_answer_factor": "float",
    "use_calibration": "bool",
}


@bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        for key, kind in EDITABLE.items():
            if kind == "bool":
                AppSetting.set(key, "1" if request.form.get(key) == "1" else "0")
                continue
            value = (request.form.get(key) or "").strip()
            if kind == "date":
                if value:
                    try:
                        date.fromisoformat(value)
                    except ValueError:
                        continue
                AppSetting.set(key, value)
            elif value:
                try:
                    float(value)
                except ValueError:
                    continue
                AppSetting.set(key, value)
        db.session.commit()
        flash("Configurações salvas.")
        return redirect(url_for("settings.index"))

    values = {key: AppSetting.get(key) for key in EDITABLE}
    target = AppSetting.get_int("target_score") or 645
    return render_template(
        "settings.html", values=values, defaults=DEFAULT_SETTINGS,
        target_level=target_level_for_score(target), level_info=LEVEL_INFO,
    )
