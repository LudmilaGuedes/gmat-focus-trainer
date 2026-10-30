from datetime import date

from app.extensions import db

DEFAULT_SETTINGS = {
    # Study plan
    "exam_date": "",  # ISO date; empty = no date set
    "target_score": "645",
    "daily_minutes": "90",
    # Automatic level changes (per subtopic, study mode only)
    "promotion_threshold_pct": "75",
    "min_attempts_before_promotion": "6",
    "demotion_threshold_pct": "34",
    "min_attempts_before_demotion": "6",
    "auto_demotion": "1",
    # Weak-subtopic diagnosis
    "weak_subtopic_min_attempts": "4",
    "weak_subtopic_accuracy_pct": "50",
    # Checkpoint (teste de fixação) after each lesson
    "checkpoint_questions": "5",
    "checkpoint_pass_count": "4",
    # A correct answer slower than this multiple of the target time goes to review
    "slow_answer_factor": "1.6",
    # Apply the offset learned from official practice exams to the estimate
    "use_calibration": "1",
}


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(200), nullable=False)

    @staticmethod
    def get(key, default=None):
        row = AppSetting.query.get(key)
        if row is not None:
            return row.value
        if default is not None:
            return default
        return DEFAULT_SETTINGS.get(key)

    @staticmethod
    def get_int(key, default=None):
        value = AppSetting.get(key, default)
        return int(float(value)) if value not in (None, "") else 0

    @staticmethod
    def get_float(key, default=None):
        value = AppSetting.get(key, default)
        return float(value) if value not in (None, "") else 0.0

    @staticmethod
    def get_bool(key, default=None):
        return str(AppSetting.get(key, default)).strip().lower() in ("1", "true", "yes", "on")

    @staticmethod
    def get_date(key):
        value = AppSetting.get(key)
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def set(key, value):
        row = AppSetting.query.get(key)
        if row is None:
            row = AppSetting(key=key, value=str(value))
            db.session.add(row)
        else:
            row.value = str(value)
