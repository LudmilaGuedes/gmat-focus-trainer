"""Spaced repetition (Leitner boxes) for missed questions, flashcards and theory.

Box n is reviewed INTERVAL_DAYS[n] days after the last review. Getting it
right moves the item up a box; getting it wrong sends it back to box 0.
Passing the last box "graduates" the item (it leaves the queue; it counts
as learned). Theory (lesson key points) uses its own, longer schedule.
"""

from datetime import timedelta

from app.extensions import db
from app.models.progress import ReviewItem
from app.timeutils import start_of_today, utcnow

INTERVAL_DAYS = [1, 3, 7, 14, 30, 60]
LESSON_REVIEW_DAYS = [2, 7, 21, 45, 90]

ERROR_REASONS = {
    "concept": "Não sabia o conceito",
    "reading": "Li/interpretei errado",
    "careless": "Erro de conta / descuido",
    "strategy": "Não achei o caminho (estratégia)",
    "time": "Faltou tempo / demorei",
    "trap": "Caí numa alternativa-armadilha",
}


def _due_after(box, now=None):
    now = now or utcnow()
    days = INTERVAL_DAYS[min(box, len(INTERVAL_DAYS) - 1)]
    # Due at the start of that day, so a review scheduled "in 1 day" shows up
    # tomorrow morning regardless of the hour it was created.
    return start_of_today(now) + timedelta(days=days)


def enqueue_question(question_id, origin, box=0, error_reason=None):
    """Adds (or resets) a question in the review queue. Returns the item."""
    item = ReviewItem.query.filter_by(question_id=question_id).first()
    if item is None:
        item = ReviewItem(item_type="question", question_id=question_id, origin=origin, box=box,
                          reviews_count=0, lapses=0, graduated=False)
        db.session.add(item)
    else:
        if item.graduated or item.box > box:
            item.box = box
        item.graduated = False
        item.origin = origin
    if error_reason:
        item.error_reason = error_reason
    item.due_at = _due_after(item.box)
    return item


def enqueue_flashcard(flashcard_id):
    item = ReviewItem.query.filter_by(flashcard_id=flashcard_id).first()
    if item is None:
        item = ReviewItem(item_type="flashcard", flashcard_id=flashcard_id, origin="lesson", box=0,
                          reviews_count=0, lapses=0, graduated=False)
        item.due_at = _due_after(0)
        db.session.add(item)
    return item


def record_review(item, is_correct, now=None):
    """Question reviews: right -> next box, wrong -> box 0."""
    now = now or utcnow()
    item.reviews_count = (item.reviews_count or 0) + 1
    item.last_reviewed_at = now
    if is_correct:
        item.box += 1
        if item.box >= len(INTERVAL_DAYS):
            item.graduated = True
            item.box = len(INTERVAL_DAYS) - 1
    else:
        item.box = 0
        item.lapses = (item.lapses or 0) + 1
    item.due_at = _due_after(item.box, now)
    return item


def record_flashcard_grade(item, grade, now=None):
    """grade: again | hard | good | easy."""
    now = now or utcnow()
    item.reviews_count = (item.reviews_count or 0) + 1
    item.last_reviewed_at = now
    if grade == "again":
        item.box = 0
        item.lapses = (item.lapses or 0) + 1
    elif grade == "good":
        item.box += 1
    elif grade == "easy":
        item.box += 2
    # "hard" keeps the same box.
    if item.box >= len(INTERVAL_DAYS):
        item.graduated = True
        item.box = len(INTERVAL_DAYS) - 1
    item.due_at = _due_after(item.box, now)
    return item


def mark_known(question_id, now=None):
    """"Já sei": the user answered correctly and doesn't want to see it again.
    Graduates it out of the review queue and keeps it out of practice; missing
    it later (e.g. in a mock) re-enqueues it through enqueue_question."""
    now = now or utcnow()
    item = ReviewItem.query.filter_by(question_id=question_id).first()
    if item is None:
        item = ReviewItem(item_type="question", question_id=question_id, reviews_count=0, lapses=0)
        db.session.add(item)
    item.origin = "known"
    item.graduated = True
    item.box = len(INTERVAL_DAYS) - 1
    item.due_at = now
    return item


def is_known(question_id):
    return ReviewItem.query.filter_by(question_id=question_id, origin="known", graduated=True).first() is not None


def known_question_ids():
    rows = db.session.query(ReviewItem.question_id).filter(
        ReviewItem.origin == "known", ReviewItem.graduated.is_(True)
    )
    return {row[0] for row in rows}


def due_items_query(now=None):
    now = now or utcnow()
    return ReviewItem.query.filter(ReviewItem.graduated.is_(False), ReviewItem.due_at <= now)


def due_count(now=None):
    return due_items_query(now).count()


def schedule_lesson_review(progress, now=None):
    """After a lesson or a theory review: next review of its key points."""
    now = now or utcnow()
    step = progress.lesson_review_step
    if step >= len(LESSON_REVIEW_DAYS):
        progress.lesson_next_review_at = None
        return
    progress.lesson_next_review_at = start_of_today(now) + timedelta(days=LESSON_REVIEW_DAYS[step])
