"""Picks the next question to serve.

Freshness uses the persistent attempt history (not the browser session):
a question you have never seen beats one you saw long ago, which beats one
you saw recently, and a question not attempted in the last few days (at any
level, nearest first) beats repeating a recent one; practice never repeats. If the requested level has nothing
left in a subtopic, the nearest level is used (lower first in study mode, so a gap in the bank
never pushes you into something much harder).

Mock exams additionally prefer questions never used in a previous mock and
not practiced in the last few weeks, follow the official content mix of each
section, and keep Reading Comprehension / Multi-Source Reasoning sets
together like the real test.
"""

import random
from datetime import timedelta

from sqlalchemy import func

from app.extensions import db
from app.levels import LEVELS, MAX_LEVEL
from app.models.mock_exam import MockExamAttempt
from app.models.question_bank import Question
from app.models.sessions import Attempt
from app.models.taxonomy import ContentArea, Subtopic
from app.services import srs
from app.timeutils import utcnow

# Approximate official content mix per section (questions per content area code).
MOCK_CONTENT_MIX = {
    "VR": {"vr_critical_reasoning": 10, "vr_reading_comprehension": 13},
    "DI": {
        "di_data_sufficiency": 6,
        "di_table_analysis": 3,
        "di_graphics_interpretation": 4,
        "di_two_part_analysis": 4,
        "di_multi_source_reasoning": 3,
    },
}
# On the real exam a short RC passage (~200-250 words) carries 3 questions, a long one (~300-350) carries 4,
# and an MSR set carries 3.
LONG_PASSAGE_WORDS = 280


def mock_set_size(question_set):
    if question_set is None:
        return 4
    if question_set.set_type == "reading_passage":
        words = len((question_set.stimulus_text or "").split())
        return 4 if words >= LONG_PASSAGE_WORDS else 3
    return 3


MOCK_RECENT_STUDY_DAYS = 21
# Practice avoids questions attempted in the last few days while fresh ones exist nearby.
PRACTICE_RECENT_DAYS = 3


def level_search_order(level, prefer_lower=True):
    order = [level]
    for delta in range(1, MAX_LEVEL):
        first, second = (level - delta, level + delta) if prefer_lower else (level + delta, level - delta)
        for lvl in (first, second):
            if lvl in LEVELS:
                order.append(lvl)
    return order


def _active_query():
    return Question.query.filter(Question.status == "active", Question.flagged.is_(False))


def last_attempt_map(question_ids):
    if not question_ids:
        return {}
    rows = (
        db.session.query(Attempt.question_id, func.max(Attempt.answered_at))
        .filter(Attempt.question_id.in_(list(question_ids)))
        .group_by(Attempt.question_id)
        .all()
    )
    return dict(rows)


def _freshest(candidates):
    """Never-attempted first (random among them), else least recently attempted."""
    if not candidates:
        return None
    last = last_attempt_map([q.id for q in candidates])
    never = [q for q in candidates if q.id not in last]
    if never:
        return random.choice(never)
    return min(candidates, key=lambda q: last[q.id])


def _recently_attempted_ids(subtopic_id, days):
    cutoff = utcnow() - timedelta(days=days)
    rows = (
        db.session.query(Attempt.question_id)
        .join(Question, Attempt.question_id == Question.id)
        .filter(Question.subtopic_id == subtopic_id, Attempt.answered_at >= cutoff)
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def fresh_question_count(subtopic_ids, days=PRACTICE_RECENT_DAYS):
    """Active questions in these subtopics not attempted in the last `days` days."""
    if not subtopic_ids:
        return 0
    cutoff = utcnow() - timedelta(days=days)
    recent = (
        db.session.query(Attempt.question_id).filter(Attempt.answered_at >= cutoff).distinct()
    )
    return (
        _active_query()
        .filter(Question.subtopic_id.in_(list(subtopic_ids)), Question.id.notin_(recent))
        .count()
    )


def select_question(subtopic_id, level, exclude_ids=(), allow_repeat=True):
    """Never-seen questions at the level or one step away come first; then the nearest level
    among questions not attempted in the last few days; then unseen ones at any level.
    With allow_repeat=False, returns None
    instead of repeating (practice then moves to another subtopic or stops)."""
    exclude_ids = set(exclude_ids or ())
    recent = exclude_ids | _recently_attempted_ids(subtopic_id, PRACTICE_RECENT_DAYS)
    known = srs.known_question_ids()
    by_level = {}
    for q in _active_query().filter(Question.subtopic_id == subtopic_id).all():
        if q.id in known:
            continue
        by_level.setdefault(q.difficulty, []).append(q)
    order = level_search_order(level, prefer_lower=True)
    seen = set(last_attempt_map([q.id for qs in by_level.values() for q in qs]))
    tiers = [
        # Never seen, at the level or one step away: beats a question seen long ago.
        (order[:3], lambda q: q.id not in seen),
        (order, lambda q: q.id not in recent),
        (order, lambda q: q.id not in seen),
    ]
    for levels, ok in tiers:
        for lvl in levels:
            fresh = [q for q in by_level.get(lvl, []) if q.id not in exclude_ids and ok(q)]
            if fresh:
                return _freshest(fresh)
    if not allow_repeat:
        return None
    for lvl in level_search_order(level, prefer_lower=True):
        candidates = [q for q in by_level.get(lvl, []) if q.id not in exclude_ids]
        if candidates:
            return _freshest(candidates)
    if exclude_ids:
        # Everything was served in this run: repeat the least recent one.
        return select_question(subtopic_id, level, exclude_ids=())
    return None


def select_question_in_range(subtopic_id, levels, exclude_ids=()):
    """Checkpoint: any question in the given levels, freshest first."""
    exclude_ids = set(exclude_ids or ()) | srs.known_question_ids()
    candidates = [
        q for q in _active_query().filter(Question.subtopic_id == subtopic_id, Question.difficulty.in_(levels)).all()
        if q.id not in exclude_ids
    ]
    if not candidates:
        return select_question(subtopic_id, min(levels), exclude_ids)
    # Unseen first, then easier, then freshness.
    seen = last_attempt_map([q.id for q in candidates])
    candidates = [q for q in candidates if q.id not in seen] or candidates
    lowest = min(q.difficulty for q in candidates)
    return _freshest([q for q in candidates if q.difficulty == lowest] or candidates)


def pick_subtopic_for_practice(subtopic_ids, progress_by_id, target_level, weak_ids=()):
    """Weighted choice: subtopics further below the target level and those
    currently weak come up more often (interleaving, not blocked practice)."""
    if not subtopic_ids:
        return None
    started = [
        sid for sid in subtopic_ids
        if progress_by_id.get(sid) is not None and progress_by_id[sid].checkpoint_passed_at is not None
    ]
    if not started:
        started = [
            sid for sid in subtopic_ids
            if progress_by_id.get(sid) is not None and progress_by_id[sid].lesson_completed_at is not None
        ]
    pool = started or list(subtopic_ids)
    weights = []
    for sid in pool:
        progress = progress_by_id.get(sid)
        level = progress.level if progress else 1
        weight = 1.0 + max(0, target_level - level) + (2.0 if sid in weak_ids else 0.0)
        weights.append(weight)
    return random.choices(pool, weights=weights, k=1)[0]


# --------------------------------------------------------------------------- mock exam


def _mock_used_ids():
    return {row[0] for row in db.session.query(MockExamAttempt.question_id).distinct().all()}


def _recently_studied_ids(days=MOCK_RECENT_STUDY_DAYS):
    cutoff = utcnow() - timedelta(days=days)
    rows = (
        db.session.query(Attempt.question_id)
        .filter(Attempt.mode != "mock_exam", Attempt.answered_at >= cutoff)
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def _section_subtopic_ids(section_id, content_area_codes=None):
    query = ContentArea.query.filter_by(section_id=section_id)
    if content_area_codes:
        query = query.filter(ContentArea.code.in_(list(content_area_codes)))
    ca_ids = [c.id for c in query.all()]
    return [s.id for s in Subtopic.query.filter(Subtopic.content_area_id.in_(ca_ids)).all()] if ca_ids else []


def _next_content_area_code(section_code, served_questions):
    mix = MOCK_CONTENT_MIX.get(section_code)
    if not mix:
        return None
    served = {}
    for q in served_questions:
        code = q.content_area.code
        served[code] = served.get(code, 0) + 1
    total_quota = sum(mix.values())
    total_served = len(served_questions)
    # Pick the area furthest behind its proportional share.
    best, best_gap = None, None
    for code, quota in mix.items():
        expected = quota / total_quota * (total_served + 1)
        gap = expected - served.get(code, 0)
        if best_gap is None or gap > best_gap:
            best, best_gap = code, gap
    return best


def select_mock_question(section, level, served_questions):
    """served_questions: Questions already used in THIS mock section, in order."""
    served_ids = {q.id for q in served_questions}

    # Keep a passage / MSR set together: continue it while it has unused questions.
    if served_questions and served_questions[-1].set_id:
        last = served_questions[-1]
        siblings = [
            q for q in _active_query().filter(Question.set_id == last.set_id).order_by(Question.set_order).all()
            if q.id not in served_ids
        ]
        set_served = sum(1 for q in served_questions if q.set_id == last.set_id)
        if siblings and set_served < mock_set_size(last.question_set):
            return siblings[0]

    area_code = _next_content_area_code(section.code, served_questions)
    subtopic_ids = _section_subtopic_ids(section.id, [area_code] if area_code else None)
    if not subtopic_ids:
        subtopic_ids = _section_subtopic_ids(section.id)

    mock_used = _mock_used_ids()
    recent = _recently_studied_ids()
    tiers = [
        lambda q: q.id not in mock_used and q.id not in recent,
        lambda q: q.id not in mock_used,
        lambda q: True,
    ]
    for lvl in level_search_order(level, prefer_lower=False)[:3]:
        candidates = [
            q for q in _active_query().filter(Question.subtopic_id.in_(subtopic_ids), Question.difficulty == lvl).all()
            if q.id not in served_ids
        ]
        for tier in tiers:
            pool = [q for q in candidates if tier(q)]
            if pool:
                # Start sets at their first question.
                starters = [q for q in pool if not q.set_id or (q.set_order or 1) == 1]
                return random.choice(starters or pool)
    # Nothing left near the level (in this content area): nearest level anywhere in the section.
    subtopic_ids = _section_subtopic_ids(section.id)
    for lvl in level_search_order(level, prefer_lower=False):
        candidates = [
            q for q in _active_query().filter(Question.subtopic_id.in_(subtopic_ids), Question.difficulty == lvl).all()
            if q.id not in served_ids
        ]
        if candidates:
            return random.choice(candidates)
    return None
