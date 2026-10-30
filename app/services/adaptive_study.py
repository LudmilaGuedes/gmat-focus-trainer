"""Study-mode adaptation, per SUBTOPIC (one specific skill):

* records every attempt and rolls it up per (subtopic, level);
* promotes a subtopic to the next level when recent accuracy at its current
  level is high enough, and (optionally) demotes it when it collapses;
* sends missed / guessed / too-slow questions to the spaced-review queue;
* tracks the lesson -> checkpoint -> practice lifecycle of each subtopic.

Mock exams log attempts through `record_attempt(mode="mock_exam")`, which
feeds the review queue and the score estimate but NEVER changes a level —
only practice does (or the explicit manual adjustment).
"""

from app.extensions import db
from app.levels import MAX_LEVEL, MIN_LEVEL, TARGET_SECONDS_BY_SECTION, clamp_level
from app.models.progress import LevelAdjustment, SubtopicLevelStat, SubtopicProgress
from app.models.question_bank import Flashcard, Lesson
from app.models.sessions import PRACTICE_MODES, Attempt, LessonView
from app.models.settings import AppSetting
from app.services import srs
from app.timeutils import utcnow

RECENT_WINDOW = 10


def get_or_create_progress(subtopic_id):
    progress = SubtopicProgress.query.get(subtopic_id)
    if progress is None:
        progress = SubtopicProgress(subtopic_id=subtopic_id, level=1)
        db.session.add(progress)
        db.session.commit()
    return progress


def progress_map(subtopic_ids=None):
    """{subtopic_id: SubtopicProgress} without creating missing rows."""
    query = SubtopicProgress.query
    if subtopic_ids is not None:
        query = query.filter(SubtopicProgress.subtopic_id.in_(list(subtopic_ids)))
    return {p.subtopic_id: p for p in query.all()}


def target_seconds(question):
    return TARGET_SECONDS_BY_SECTION.get(question.section.code, 120)


def record_attempt(
    question,
    session_id,
    selected_answer,
    is_correct,
    mode="study",
    time_spent_seconds=None,
    guessed=False,
):
    """Logs one answer and applies all side effects. Returns a dict with
    `attempt`, `level_change` (None or (old, new)) and `review_item`."""
    attempt = Attempt(
        question_id=question.id,
        session_id=session_id,
        mode=mode,
        selected_answer_json=selected_answer,
        is_correct=bool(is_correct),
        difficulty_at_attempt=question.difficulty,
        time_spent_seconds=time_spent_seconds,
        guessed=bool(guessed),
    )
    db.session.add(attempt)

    level_change = None
    if mode in PRACTICE_MODES:
        stat = _level_stat(question.subtopic_id, question.difficulty)
        stat.attempts_count += 1
        if is_correct:
            stat.correct_count += 1
        stat.recent_json = (list(stat.recent_json or []) + [bool(is_correct)])[-RECENT_WINDOW:]
        db.session.flush()

    review_item = None
    if mode != "review":
        review_item = _maybe_enqueue_for_review(question, is_correct, guessed, time_spent_seconds, mode)

    db.session.commit()

    if mode in PRACTICE_MODES:
        level_change = maybe_adjust_level(question.subtopic_id)

    return {"attempt": attempt, "level_change": level_change, "review_item": review_item}


def _level_stat(subtopic_id, level):
    stat = SubtopicLevelStat.query.filter_by(subtopic_id=subtopic_id, level=level).first()
    if stat is None:
        stat = SubtopicLevelStat(
            subtopic_id=subtopic_id, level=level, attempts_count=0, correct_count=0, recent_json=[]
        )
        db.session.add(stat)
    return stat


def _maybe_enqueue_for_review(question, is_correct, guessed, time_spent_seconds, mode):
    if not is_correct:
        return srs.enqueue_question(question.id, origin="mock" if mode == "mock_exam" else "wrong", box=0)
    if guessed:
        return srs.enqueue_question(question.id, origin="guessed", box=0)
    slow_factor = AppSetting.get_float("slow_answer_factor")
    if time_spent_seconds and slow_factor and time_spent_seconds > slow_factor * target_seconds(question):
        return srs.enqueue_question(question.id, origin="slow", box=1)
    return None


def evidence_at_level(subtopic_id, level, since=None, window=RECENT_WINDOW):
    """Results (oldest -> newest) of the last `window` practice attempts in this
    subtopic on questions at `level` or harder, after `since` (the last
    LevelAdjustment — each level needs fresh evidence)."""
    from app.models.question_bank import Question

    query = (
        Attempt.query.join(Question, Attempt.question_id == Question.id)
        .filter(
            Question.subtopic_id == subtopic_id,
            Attempt.mode.in_(PRACTICE_MODES),
            Attempt.difficulty_at_attempt >= level,
        )
    )
    if since is not None:
        if since.after_attempt_id is not None:
            query = query.filter(Attempt.id > since.after_attempt_id)
        else:
            query = query.filter(Attempt.answered_at > since.created_at)
    rows = query.order_by(Attempt.answered_at.desc(), Attempt.id.desc()).limit(window).all()
    return [a.is_correct for a in reversed(rows)]


def _last_level_change(subtopic_id):
    return (
        LevelAdjustment.query.filter_by(subtopic_id=subtopic_id)
        .order_by(LevelAdjustment.id.desc())
        .first()
    )


def maybe_adjust_level(subtopic_id):
    """Promotion/demotion from the recent results at the current level (or
    harder) since the last level change. Returns (old, new) or None."""
    progress = get_or_create_progress(subtopic_id)
    if progress.manually_locked:
        return None

    recent = evidence_at_level(subtopic_id, progress.level, since=_last_level_change(subtopic_id))
    if not recent:
        return None
    recent_pct = sum(recent) / len(recent) * 100

    min_promote = AppSetting.get_int("min_attempts_before_promotion")
    promote_pct = AppSetting.get_float("promotion_threshold_pct")
    if progress.level < MAX_LEVEL and len(recent) >= min_promote and recent_pct >= promote_pct:
        return _change_level(
            progress, progress.level + 1, "auto_promote",
            f"{sum(recent)}/{len(recent)} certas recentes no N{progress.level}+",
        )

    if AppSetting.get_bool("auto_demotion"):
        min_demote = AppSetting.get_int("min_attempts_before_demotion")
        demote_pct = AppSetting.get_float("demotion_threshold_pct")
        last = recent[-min_demote:]
        if progress.level > MIN_LEVEL and len(last) >= min_demote and (sum(last) / len(last)) * 100 < demote_pct:
            return _change_level(
                progress, progress.level - 1, "auto_demote",
                f"só {sum(last)}/{len(last)} certas recentes no N{progress.level}",
            )
    return None


def _change_level(progress, new_level, triggered_by, reason_text=None, source_mock_exam_id=None):
    old_level = progress.level
    new_level = clamp_level(new_level)
    if new_level == old_level:
        return None
    from sqlalchemy import func

    last_attempt_id = db.session.query(func.max(Attempt.id)).scalar()
    db.session.add(
        LevelAdjustment(
            subtopic_id=progress.subtopic_id,
            after_attempt_id=last_attempt_id,
            previous_level=old_level,
            new_level=new_level,
            reason_text=reason_text,
            source_mock_exam_id=source_mock_exam_id,
            triggered_by=triggered_by,
        )
    )
    progress.level = new_level
    db.session.commit()
    return (old_level, new_level)


def apply_manual_level_adjustment(subtopic_id, new_level, reason_text=None, source_mock_exam_id=None, lock=None):
    """The only path besides practice that changes a subtopic's level —
    always an explicit user click (e.g. after reviewing a mock exam)."""
    progress = get_or_create_progress(subtopic_id)
    if lock is not None:
        progress.manually_locked = bool(lock)
    change = _change_level(progress, new_level, "manual", reason_text, source_mock_exam_id)
    db.session.commit()
    return change


def recent_subtopic_accuracy(subtopic_id, window=8):
    """(correct, total) over the last `window` practice attempts in this subtopic, any level."""
    from app.models.question_bank import Question

    rows = (
        Attempt.query.join(Question, Attempt.question_id == Question.id)
        .filter(Question.subtopic_id == subtopic_id, Attempt.mode.in_(PRACTICE_MODES))
        .order_by(Attempt.answered_at.desc())
        .limit(window)
        .all()
    )
    return sum(1 for a in rows if a.is_correct), len(rows)


def is_weak(subtopic_id):
    correct, total = recent_subtopic_accuracy(subtopic_id)
    min_attempts = AppSetting.get_int("weak_subtopic_min_attempts")
    threshold = AppSetting.get_float("weak_subtopic_accuracy_pct")
    return total >= min_attempts and (correct / total) * 100 < threshold


def weak_subtopic_ids(subtopic_ids):
    return [sid for sid in subtopic_ids if is_weak(sid)]


def get_lesson_for_subtopic(subtopic_id):
    return Lesson.query.filter_by(subtopic_id=subtopic_id).first()


def complete_lesson(subtopic_id):
    """Marks the lesson as studied: schedules its first theory review and
    puts its flashcards into the spaced-review queue."""
    progress = get_or_create_progress(subtopic_id)
    now = utcnow()
    first_time = progress.lesson_completed_at is None
    if first_time:
        progress.lesson_completed_at = now
        progress.lesson_review_step = 0
        srs.schedule_lesson_review(progress, now)
    lesson = get_lesson_for_subtopic(subtopic_id)
    if lesson is not None:
        db.session.add(LessonView(lesson_id=lesson.id, kind="study"))
        for card in Flashcard.query.filter_by(lesson_id=lesson.id).all():
            srs.enqueue_flashcard(card.id)
    db.session.commit()
    return progress


def complete_lesson_review(subtopic_id):
    progress = get_or_create_progress(subtopic_id)
    progress.lesson_review_step += 1
    srs.schedule_lesson_review(progress)
    lesson = get_lesson_for_subtopic(subtopic_id)
    if lesson is not None:
        db.session.add(LessonView(lesson_id=lesson.id, kind="review"))
    db.session.commit()
    return progress


def finalize_checkpoint(subtopic_id, correct, total):
    """Teste de fixação: pass -> subtopic enters regular practice; a perfect
    score starts it at level 2 directly. Returns True if passed."""
    progress = get_or_create_progress(subtopic_id)
    progress.checkpoint_attempts += 1
    pass_count = min(AppSetting.get_int("checkpoint_pass_count"), total) if total else 0
    passed = total > 0 and correct >= pass_count
    if passed and progress.checkpoint_passed_at is None:
        progress.checkpoint_passed_at = utcnow()
        if correct == total and progress.level == 1 and not progress.manually_locked:
            _change_level(progress, 2, "auto_promote", f"teste de fixação {correct}/{total}")
    if passed and progress.lesson_completed_at is None:
        # "Já sei esse assunto": passing the test counts as having the theory.
        progress.lesson_completed_at = utcnow()
        srs.schedule_lesson_review(progress)
    db.session.commit()
    return passed
