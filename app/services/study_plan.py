"""The study track and the daily plan ("Hoje").

Track: every subtopic in the order of sample_bank/study_plan.yaml, each one
going through  lesson -> checkpoint (teste de fixação) -> practice N1..N5.

Phases (whole preparation):
  1 Fundamentos  — some subtopic still hasn't had its lesson + checkpoint
  2 Construção   — all subtopics started; some still below level 3
  3 Nível-alvo   — all at level >= 3; some below the target level
  4 Reta final   — all at target, or the estimate reached the target,
                   or the exam is <= 21 days away

Daily plan: spaced reviews first (what you're about to forget), then theory
reviews, then new lessons at the pace needed to finish the track in time,
then focused practice on the weakest subtopics with the remaining minutes,
plus mock-exam / official-exam suggestions on a weekly rhythm.
"""

import math
from datetime import timedelta

from app.levels import LEVEL_INFO, target_level_for_score
from app.models.mock_exam import MockExam
from app.models.progress import ExternalScore, ReviewItem
from app.models.question_bank import Lesson, Question
from app.models.sessions import PRACTICE_MODES, Attempt, LessonView
from app.models.settings import AppSetting
from app.models.taxonomy import ContentArea, Section, Subtopic
from app.services import srs
from app.services.adaptive_study import is_weak, progress_map, recent_subtopic_accuracy
from app.services.question_selector import fresh_question_count
from app.timeutils import local_today, start_of_today, utcnow

PHASES = {
    1: ("Fundamentos", "Aprender a teoria de cada assunto e passar no teste de fixação."),
    2: ("Construção", "Levar todos os assuntos pelo menos ao nível 3 (Intermediário)."),
    3: ("Nível-alvo", "Levar todos os assuntos ao nível da sua meta e treinar tempo."),
    4: ("Reta final", "Simulados semanais, revisões e manutenção — sem assunto novo."),
}
MINUTES_PER_QUESTION = 2.3
MINUTES_PER_FLASHCARD = 0.5
MINUTES_PER_THEORY_REVIEW = 6
MINUTES_PER_CHECKPOINT = 12


def target_score():
    return AppSetting.get_int("target_score") or 645


def target_level():
    return target_level_for_score(target_score())


def days_until_exam(today=None):
    exam = AppSetting.get_date("exam_date")
    if exam is None:
        return None
    return (exam - (today or local_today())).days


def track_subtopics():
    subtopics = Subtopic.query.filter(Subtopic.track_order.isnot(None)).order_by(Subtopic.track_order).all()
    if subtopics:
        return subtopics
    return (
        Subtopic.query.join(ContentArea).join(Section)
        .order_by(Section.order, ContentArea.order, Subtopic.order)
        .all()
    )


def track_overview():
    subtopics = track_subtopics()
    progress_by_id = progress_map([s.id for s in subtopics])
    lessons = {l.subtopic_id: l for l in Lesson.query.all()}
    tgt = target_level()
    items = []
    for s in subtopics:
        p = progress_by_id.get(s.id)
        correct, total = recent_subtopic_accuracy(s.id) if p else (0, 0)
        items.append(
            {
                "subtopic": s,
                "progress": p,
                "status": p.status if p else "new",
                "level": p.level if p else 1,
                "lesson": lessons.get(s.id),
                "recent_correct": correct,
                "recent_total": total,
                "at_target": bool(p and p.status == "practicing" and p.level >= tgt),
                "phase": s.track_phase or 1,
            }
        )
    started = [i for i in items if i["status"] == "practicing"]
    return {
        "items": items,
        "total": len(items),
        "lessons_done": sum(1 for i in items if i["status"] != "new"),
        "started": len(started),
        "at_level3": sum(1 for i in started if i["level"] >= 3),
        "at_target": sum(1 for i in items if i["at_target"]),
        "target_level": tgt,
    }


def current_phase(overview, estimate_total=None, days_left=None):
    if days_left is not None and days_left <= 21:
        return 4
    total = overview["total"]
    if total == 0:
        return 1
    if overview["started"] < total:
        return 1
    if overview["at_level3"] < total:
        return 2
    if overview["at_target"] < total and not (estimate_total and estimate_total >= target_score()):
        return 3
    return 4


def _today_bounds():
    start = start_of_today()
    return start, start + timedelta(days=1)


def todays_activity():
    start, end = _today_bounds()
    attempts = Attempt.query.filter(Attempt.answered_at >= start, Attempt.answered_at < end).all()
    views = LessonView.query.filter(LessonView.viewed_at >= start, LessonView.viewed_at < end).all()
    reviewed = ReviewItem.query.filter(ReviewItem.last_reviewed_at >= start, ReviewItem.last_reviewed_at < end).count()
    seconds = sum(a.time_spent_seconds or 0 for a in attempts)
    return {
        "practice": sum(1 for a in attempts if a.mode in PRACTICE_MODES),
        "practice_correct": sum(1 for a in attempts if a.mode in PRACTICE_MODES and a.is_correct),
        "focused_practice": sum(1 for a in attempts if a.mode == "study"),
        "review_attempts": sum(1 for a in attempts if a.mode == "review"),
        "mock": sum(1 for a in attempts if a.mode == "mock_exam"),
        "reviewed_items": reviewed,
        "lessons_studied": [v for v in views if v.kind == "study"],
        "lessons_reviewed": [v for v in views if v.kind == "review"],
        "question_minutes": round(seconds / 60),
    }


def _lessons_per_day(remaining, days_left, daily_minutes):
    if remaining <= 0:
        return 0
    if days_left is None or days_left <= 0:
        return 2 if daily_minutes >= 120 else 1
    # Leave ~45% of the remaining time for building level and mocks.
    window = max(7, int(days_left * 0.55))
    return max(1, min(3, math.ceil(remaining / window)))


def practice_focus(overview, limit=3):
    """Subtopics to practice today: weak first, then furthest below target,
    then least recently practiced."""
    tgt = overview["target_level"]
    candidates = [i for i in overview["items"] if i["status"] == "practicing"]
    if not candidates:
        return []
    last_practice = {}
    for item in candidates:
        last = (
            Attempt.query.join(Question, Attempt.question_id == Question.id)
            .filter(Question.subtopic_id == item["subtopic"].id, Attempt.mode.in_(PRACTICE_MODES))
            .order_by(Attempt.answered_at.desc())
            .first()
        )
        last_practice[item["subtopic"].id] = last.answered_at if last else None

    def priority(item):
        sid = item["subtopic"].id
        weak = is_weak(sid)
        gap = max(0, tgt - item["level"])
        last = last_practice[sid]
        staleness = (utcnow() - last).days if last else 999
        return (-int(weak), -gap, -staleness)

    return sorted(candidates, key=priority)[:limit]


def build_today_plan(estimate=None):
    daily_minutes = AppSetting.get_int("daily_minutes") or 90
    days_left = days_until_exam()
    overview = track_overview()
    phase = current_phase(overview, estimate["total"] if estimate else None, days_left)
    activity = todays_activity()
    now = utcnow()
    tasks = []
    # Work already done today uses up the day's budget too; otherwise finishing the other tasks
    # would inflate the practice goal.
    reviewed_flashcards = max(0, activity["reviewed_items"] - activity["review_attempts"])
    review_minutes_done = activity["review_attempts"] * MINUTES_PER_QUESTION + reviewed_flashcards * MINUTES_PER_FLASHCARD
    checkpoint_questions_done = activity["practice"] - activity["focused_practice"]
    budget = daily_minutes - round(
        review_minutes_done
        + checkpoint_questions_done * MINUTES_PER_QUESTION
        + sum(v.lesson.estimated_minutes for v in activity["lessons_studied"])
        + MINUTES_PER_THEORY_REVIEW * len(activity["lessons_reviewed"])
    )

    # 1. Spaced reviews (questions + flashcards).
    due = srs.due_items_query(now).all()
    due_q = sum(1 for i in due if i.item_type == "question")
    due_f = len(due) - due_q
    if due or activity["reviewed_items"]:
        minutes = round(min(due_q, 25) * MINUTES_PER_QUESTION + min(due_f, 60) * MINUTES_PER_FLASHCARD)
        tasks.append({
            "kind": "review",
            "title": "Revisões espaçadas",
            "detail": f"{due_q} questões e {due_f} flashcards vencendo hoje"
            if due else f"Feito: {activity['reviewed_items']} itens revisados hoje",
            "minutes": minutes + round(review_minutes_done),
            "url": ("review.start", {}),
            "done": not due,
        })
        budget -= minutes

    # 2. Theory reviews due (key points of lessons studied days ago).
    theory_due = [
        i for i in overview["items"]
        if i["progress"] and i["progress"].lesson_next_review_at and i["progress"].lesson_next_review_at <= now
        and i["lesson"] is not None
    ]
    for item in theory_due[:3]:
        tasks.append({
            "kind": "theory_review",
            "title": f"Revisar teoria: {item['subtopic'].name}",
            "detail": "Releia os pontos-chave e tente lembrar antes de abrir.",
            "minutes": MINUTES_PER_THEORY_REVIEW,
            "url": ("learn.lesson_review", {"subtopic_id": item["subtopic"].id}),
            "done": False,
        })
        budget -= MINUTES_PER_THEORY_REVIEW
    for view in activity["lessons_reviewed"]:
        tasks.append({
            "kind": "theory_review", "title": f"Revisar teoria: {view.lesson.subtopic.name}",
            "detail": "Feito hoje.", "minutes": MINUTES_PER_THEORY_REVIEW, "url": None, "done": True,
        })

    # 3. Pending checkpoints, then new lessons at the required pace.
    for view in activity["lessons_studied"]:
        tasks.append({
            "kind": "lesson", "title": f"Lição: {view.lesson.title}", "detail": "Estudada hoje.",
            "minutes": view.lesson.estimated_minutes, "url": None, "done": True,
        })
    for item in [i for i in overview["items"] if i["status"] == "checkpoint"][:2]:
        tasks.append({
            "kind": "checkpoint",
            "title": f"Teste de fixação: {item['subtopic'].name}",
            "detail": "5 questões dos níveis 1-2 para confirmar que a teoria entrou.",
            "minutes": MINUTES_PER_CHECKPOINT,
            "url": ("learn.checkpoint_start", {"subtopic_id": item["subtopic"].id}),
            "done": False,
        })
        budget -= MINUTES_PER_CHECKPOINT
    remaining_lessons = overview["total"] - overview["lessons_done"]
    per_day = _lessons_per_day(remaining_lessons, days_left, daily_minutes)
    if phase == 4:
        per_day = 0
    new_today = max(0, per_day - len(activity["lessons_studied"]))
    for item in [i for i in overview["items"] if i["status"] == "new"][:new_today]:
        minutes = (item["lesson"].estimated_minutes if item["lesson"] else 15) + MINUTES_PER_CHECKPOINT
        if budget - minutes < 15 and any(t["kind"] == "lesson" for t in tasks):
            break
        tasks.append({
            "kind": "lesson",
            "title": f"Nova lição: {item['subtopic'].name}",
            "detail": f"{item['subtopic'].content_area.section.code} · {item['subtopic'].content_area.name}"
            " — leia, faça os exemplos e depois o teste de fixação.",
            "minutes": minutes,
            "url": ("learn.lesson", {"subtopic_id": item["subtopic"].id}),
            "done": False,
        })
        budget -= minutes

    # 4. Focused practice with what's left of the budget — but never more than the
    # bank can serve without repeating (questions not seen in the last few days).
    focus = practice_focus(overview)
    goal = 0
    if focus:
        goal = max(10, int(max(budget, 20) / MINUTES_PER_QUESTION))
        goal = min(goal, 40)
        wanted = goal
        goal = min(goal, activity["focused_practice"] + fresh_question_count([i["subtopic"].id for i in focus]))
        if goal < wanted:
            budget -= round(goal * MINUTES_PER_QUESTION)
    if goal:
        names = ", ".join(f"{i['subtopic'].name} (N{i['level']})" for i in focus)
        tasks.append({
            "kind": "practice",
            "title": f"Prática focada — {goal} questões",
            "detail": f"Foco de hoje: {names}. Cronometre-se: meta de ~2 min por questão.",
            "minutes": round(goal * MINUTES_PER_QUESTION),
            "url": ("study.focus", {"subtopics": ",".join(str(i["subtopic"].id) for i in focus), "goal": goal}),
            "done": activity["focused_practice"] >= goal,
            "progress": f"{activity['focused_practice']}/{goal}",
        })

    # Practice capped by the bank: use the spare time to unlock the next subtopic.
    if phase != 4 and budget >= 25 and (not focus or goal < wanted):
        listed = {t["url"][1].get("subtopic_id") for t in tasks if t.get("url") and t["kind"] == "lesson"}
        studied = {v.lesson.subtopic_id for v in activity["lessons_studied"]}
        extra = next((i for i in overview["items"] if i["status"] == "new"
                      and i["subtopic"].id not in listed and i["subtopic"].id not in studied), None)
        if extra is not None and len(listed) + len(studied) < 3:
            minutes = (extra["lesson"].estimated_minutes if extra["lesson"] else 15) + MINUTES_PER_CHECKPOINT
            tasks.append({
                "kind": "lesson",
                "title": f"Nova lição: {extra['subtopic'].name}",
                "detail": "Você já praticou as questões inéditas dos assuntos liberados — avance na trilha "
                "para liberar mais prática.",
                "minutes": minutes,
                "url": ("learn.lesson", {"subtopic_id": extra["subtopic"].id}),
                "done": False,
            })

    # 5. Weekly rhythm suggestions.
    suggestions = []
    last_full = (
        MockExam.query.filter_by(status="completed", kind="full").order_by(MockExam.completed_at.desc()).first()
    )
    days_since_mock = (now - last_full.completed_at).days if last_full else None
    if phase >= 2:
        interval = 14 if phase == 2 else 7
        if days_since_mock is None or days_since_mock >= interval:
            suggestions.append({
                "title": "Simulado completo desta semana",
                "detail": "~2h20, as 3 seções cronometradas. Faça num dia com tempo, de preferência no "
                "mesmo horário da sua prova." + (f" Último: há {days_since_mock} dias." if last_full else ""),
                "url": ("mock_exam.start_form", {}),
            })
    elif overview["started"] >= 6:
        suggestions.append({
            "title": "Mini-simulado de uma seção (opcional)",
            "detail": "45 min, uma seção só — bom para sentir o ritmo da prova sem cansar.",
            "url": ("mock_exam.start_form", {}),
        })
    last_official = ExternalScore.query.order_by(ExternalScore.taken_on.desc()).first()
    if phase >= 3 and (last_official is None or (local_today() - last_official.taken_on).days > 30):
        suggestions.append({
            "title": "Simulado OFICIAL da GMAC",
            "detail": "Faça um dos Official Practice Exams (mba.com) e registre a nota em Progresso — isso "
            "calibra a estimativa do app com a realidade.",
            "url": ("resources.index", {}),
        })

    planned = sum(t["minutes"] for t in tasks)
    return {
        "phase": phase,
        "phase_name": PHASES[phase][0],
        "phase_goal": PHASES[phase][1],
        "days_left": days_left,
        "daily_minutes": daily_minutes,
        "tasks": tasks,
        "suggestions": suggestions,
        "planned_minutes": planned,
        "overview": overview,
        "activity": activity,
        "lessons_per_day": per_day,
        "remaining_lessons": remaining_lessons,
        "target_score": target_score(),
        "target_level": overview["target_level"],
        "target_level_name": LEVEL_INFO[overview["target_level"]]["name"],
    }


def section_level_summary(overview):
    """Average level and counts per section, for the dashboard."""
    by_section = {}
    for item in overview["items"]:
        code = item["subtopic"].content_area.section.code
        entry = by_section.setdefault(code, {"levels": [], "started": 0, "total": 0})
        entry["total"] += 1
        if item["status"] == "practicing":
            entry["started"] += 1
            entry["levels"].append(item["level"])
    for entry in by_section.values():
        entry["avg_level"] = round(sum(entry["levels"]) / len(entry["levels"]), 1) if entry["levels"] else None
    return by_section
