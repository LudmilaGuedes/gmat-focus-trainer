from app.models.progress import LevelAdjustment, ReviewItem
from app.models.settings import AppSetting
from app.services.adaptive_study import (
    apply_manual_level_adjustment,
    complete_lesson,
    finalize_checkpoint,
    get_or_create_progress,
    is_weak,
    record_attempt,
)
from tests.factories import make_question, make_session, make_subtopic


def _answer(subtopic, session, level, correct, mode="study", **kwargs):
    question = make_question(subtopic, level)
    return record_attempt(question, session.id, {"single": "x"}, correct, mode=mode, **kwargs)


def test_new_subtopic_starts_at_level_1(app):
    subtopic = make_subtopic()
    assert get_or_create_progress(subtopic.id).level == 1


def test_promotes_after_enough_correct_attempts(app):
    subtopic, session = make_subtopic(), make_session()
    results = [_answer(subtopic, session, 1, True) for _ in range(6)]
    assert get_or_create_progress(subtopic.id).level == 2
    assert results[-1]["level_change"] == (1, 2)
    assert LevelAdjustment.query.filter_by(triggered_by="auto_promote").count() == 1


def test_does_not_promote_below_threshold(app):
    subtopic, session = make_subtopic(), make_session()
    for correct in (True, False, True, False, True, False):
        _answer(subtopic, session, 1, correct)
    assert get_or_create_progress(subtopic.id).level == 1


def test_does_not_promote_with_too_few_attempts(app):
    subtopic, session = make_subtopic(), make_session()
    for _ in range(3):
        _answer(subtopic, session, 1, True)
    assert get_or_create_progress(subtopic.id).level == 1


def test_each_level_needs_fresh_evidence(app):
    """After a promotion, the streak that caused it must not count again."""
    subtopic, session = make_subtopic(), make_session()
    for _ in range(6):
        _answer(subtopic, session, 1, True)
    assert get_or_create_progress(subtopic.id).level == 2
    for _ in range(5):
        _answer(subtopic, session, 2, True)
    assert get_or_create_progress(subtopic.id).level == 2  # only 5 fresh attempts at N2
    _answer(subtopic, session, 2, True)
    assert get_or_create_progress(subtopic.id).level == 3


def test_easier_questions_do_not_count_toward_promotion(app):
    subtopic, session = make_subtopic(), make_session()
    apply_manual_level_adjustment(subtopic.id, 3)
    for _ in range(8):
        _answer(subtopic, session, 2, True)  # below the current level
    assert get_or_create_progress(subtopic.id).level == 3


def test_demotes_when_recent_results_collapse(app):
    subtopic, session = make_subtopic(), make_session()
    apply_manual_level_adjustment(subtopic.id, 3)
    for _ in range(6):
        _answer(subtopic, session, 3, False)
    assert get_or_create_progress(subtopic.id).level == 2
    assert LevelAdjustment.query.filter_by(triggered_by="auto_demote").count() == 1


def test_no_demotion_when_disabled(app):
    AppSetting.set("auto_demotion", "0")
    subtopic, session = make_subtopic(), make_session()
    apply_manual_level_adjustment(subtopic.id, 3)
    for _ in range(6):
        _answer(subtopic, session, 3, False)
    assert get_or_create_progress(subtopic.id).level == 3


def test_manual_lock_freezes_level(app):
    subtopic, session = make_subtopic(), make_session()
    apply_manual_level_adjustment(subtopic.id, 2, lock=True)
    for _ in range(8):
        _answer(subtopic, session, 2, True)
    assert get_or_create_progress(subtopic.id).level == 2


def test_mock_exam_attempts_never_change_level(app):
    subtopic, session = make_subtopic(), make_session("mock_exam")
    for _ in range(8):
        _answer(subtopic, session, 1, True, mode="mock_exam")
    assert get_or_create_progress(subtopic.id).level == 1


def test_review_attempts_never_change_level(app):
    subtopic, session = make_subtopic(), make_session("review")
    for _ in range(8):
        _answer(subtopic, session, 1, True, mode="review")
    assert get_or_create_progress(subtopic.id).level == 1


def test_wrong_answer_goes_to_review_queue(app):
    subtopic, session = make_subtopic(), make_session()
    result = _answer(subtopic, session, 1, False)
    item = ReviewItem.query.filter_by(question_id=result["attempt"].question_id).one()
    assert item.box == 0 and item.origin == "wrong"


def test_guessed_or_slow_correct_answers_go_to_review(app):
    subtopic, session = make_subtopic(), make_session()
    guessed = _answer(subtopic, session, 1, True, guessed=True)
    slow = _answer(subtopic, session, 1, True, time_spent_seconds=600)
    fast = _answer(subtopic, session, 1, True, time_spent_seconds=60)
    assert ReviewItem.query.filter_by(question_id=guessed["attempt"].question_id).one().origin == "guessed"
    assert ReviewItem.query.filter_by(question_id=slow["attempt"].question_id).one().origin == "slow"
    assert ReviewItem.query.filter_by(question_id=fast["attempt"].question_id).first() is None


def test_weak_subtopic_detection(app):
    subtopic, session = make_subtopic(), make_session()
    for _ in range(4):
        _answer(subtopic, session, 1, False)
    assert is_weak(subtopic.id)


def test_lesson_then_checkpoint_lifecycle(app):
    subtopic = make_subtopic()
    progress = get_or_create_progress(subtopic.id)
    assert progress.status == "new"
    complete_lesson(subtopic.id)
    assert progress.status == "checkpoint"
    assert progress.lesson_next_review_at is not None
    assert finalize_checkpoint(subtopic.id, 3, 5) is False
    assert progress.status == "checkpoint"
    assert finalize_checkpoint(subtopic.id, 5, 5) is True
    assert progress.status == "practicing"
    assert progress.level == 2  # perfect checkpoint starts at N2


def test_checkpoint_can_skip_lesson(app):
    subtopic = make_subtopic()
    assert finalize_checkpoint(subtopic.id, 4, 5) is True
    progress = get_or_create_progress(subtopic.id)
    assert progress.status == "practicing" and progress.level == 1


def test_practice_prefers_unseen_adjacent_level_over_just_seen_questions(app):
    from app.services.question_selector import select_question

    subtopic, session = make_subtopic(), make_session(mode="checkpoint")
    seen = [make_question(subtopic, 2) for _ in range(2)]
    fresh = make_question(subtopic, 3)
    far = make_question(subtopic, 5)
    for q in seen:
        record_attempt(q, session.id, {"single": "A"}, True, mode="checkpoint")
    assert select_question(subtopic.id, 2).id == fresh.id
    # An unseen question two levels away still beats repeating one done today.
    assert select_question(subtopic.id, 2, exclude_ids=[fresh.id]).id == far.id
    # Practice never repeats: nothing unseen left -> None.
    assert select_question(subtopic.id, 2, exclude_ids=[fresh.id, far.id], allow_repeat=False) is None


def test_practice_prefers_unseen_next_level_over_question_seen_long_ago(app):
    from datetime import timedelta

    from app.models.sessions import Attempt
    from app.services.question_selector import select_question
    from app.timeutils import utcnow

    subtopic, session = make_subtopic(), make_session(mode="study")
    old = make_question(subtopic, 3)
    record_attempt(old, session.id, {"single": "A"}, True, mode="study")
    Attempt.query.filter_by(question_id=old.id).update({"answered_at": utcnow() - timedelta(days=10)})
    unseen = make_question(subtopic, 4)
    assert select_question(subtopic.id, 3).id == unseen.id
