from datetime import timedelta

from app.extensions import db
from app.models.progress import ReviewItem
from app.services import srs
from app.timeutils import utcnow
from tests.factories import make_question, make_subtopic


def test_correct_reviews_space_out_and_graduate(app):
    question = make_question(make_subtopic())
    item = srs.enqueue_question(question.id, origin="wrong")
    db.session.commit()
    gaps = []
    now = utcnow()
    for _ in range(len(srs.INTERVAL_DAYS)):
        srs.record_review(item, True, now)
        gaps.append((item.due_at - now).days)
    assert item.graduated
    assert gaps == sorted(gaps)


def test_wrong_review_resets_to_box_zero(app):
    question = make_question(make_subtopic())
    item = srs.enqueue_question(question.id, origin="wrong")
    srs.record_review(item, True)
    srs.record_review(item, True)
    srs.record_review(item, False)
    assert item.box == 0 and item.lapses == 1


def test_enqueue_is_idempotent_and_resets_graduated(app):
    question = make_question(make_subtopic())
    item = srs.enqueue_question(question.id, origin="wrong")
    db.session.commit()
    item.graduated = True
    item.box = 5
    again = srs.enqueue_question(question.id, origin="mock")
    db.session.commit()
    assert again.id == item.id
    assert ReviewItem.query.count() == 1
    assert not again.graduated and again.box == 0


def test_due_items_query(app):
    question = make_question(make_subtopic())
    item = srs.enqueue_question(question.id, origin="wrong")
    db.session.commit()
    assert srs.due_count() == 0  # due tomorrow
    assert srs.due_count(utcnow() + timedelta(days=2)) == 1
    item.due_at = utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert srs.due_count() == 1


def test_flashcard_grades(app):
    item = ReviewItem(item_type="flashcard", box=0, due_at=utcnow())
    srs.record_flashcard_grade(item, "good")
    assert item.box == 1
    srs.record_flashcard_grade(item, "easy")
    assert item.box == 3
    srs.record_flashcard_grade(item, "hard")
    assert item.box == 3
    srs.record_flashcard_grade(item, "again")
    assert item.box == 0 and item.lapses == 1


def test_mark_known_leaves_reviews_and_practice_until_missed_again(app):
    from app.services.question_selector import select_question

    subtopic = make_subtopic()
    question = make_question(subtopic)
    srs.enqueue_question(question.id, origin="slow", box=1)
    srs.mark_known(question.id)
    db.session.commit()
    assert srs.is_known(question.id)
    assert srs.due_items_query(utcnow() + timedelta(days=90)).count() == 0
    assert select_question(subtopic.id, question.difficulty) is None

    srs.enqueue_question(question.id, origin="mock")
    db.session.commit()
    assert not srs.is_known(question.id)
    assert select_question(subtopic.id, question.difficulty).id == question.id
