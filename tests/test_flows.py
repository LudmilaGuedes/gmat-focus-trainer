"""End-to-end walk through every screen with the Flask test client, on the
real content bank."""

import os
import sys
from datetime import timedelta

import pytest

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import import_questions as import_questions_module  # noqa: E402
import seed_taxonomy as seed_taxonomy_module  # noqa: E402

from app.extensions import db  # noqa: E402
from app.models.mock_exam import MockExam, MockExamAttempt  # noqa: E402
from app.models.progress import ReviewItem, SubtopicProgress  # noqa: E402
from app.models.question_bank import Question  # noqa: E402
from app.models.sessions import Attempt  # noqa: E402
from app.models.taxonomy import Subtopic  # noqa: E402
from app.services.grading import build_answer_groups  # noqa: E402
from app.timeutils import utcnow  # noqa: E402


@pytest.fixture
def client(app):
    seed_taxonomy_module.seed()
    import_questions_module.import_all()
    return app.test_client()


def _form(question, correct=True):
    data = {"question_id": str(question.id)}
    for key, options in build_answer_groups(question).items():
        pick = next(o for o in options if o.is_correct == correct) if correct else next(
            (o for o in options if not o.is_correct), options[0])
        data[f"group_{key}"] = str(pick.id)
    return data


def _current(client, key, field="current_qid"):
    with client.session_transaction() as sess:
        state = sess.get(key)
        qid = state.get(field) if isinstance(state, dict) else state
    return db.session.get(Question, qid)


def test_static_pages(client):
    for url in ("/", "/trilha", "/conteudos", "/section/QR", "/progress/", "/settings/", "/resources/",
                "/resources/guia", "/review/errors", "/mock-exam/history", "/mock-exam/start", "/question/flagged"):
        resp = client.get(url)
        assert resp.status_code == 200, url


def test_lesson_checkpoint_practice_review_cycle(client):
    subtopic = Subtopic.query.order_by(Subtopic.track_order).first()
    assert client.get(f"/learn/{subtopic.id}").status_code == 200

    # Lesson -> checkpoint (5 questions, all right).
    resp = client.post(f"/learn/{subtopic.id}/complete")
    assert resp.status_code == 302
    client.get(resp.headers["Location"])
    for _ in range(5):
        assert client.get("/learn/checkpoint").status_code == 200
        question = _current(client, "checkpoint")
        assert question.difficulty <= 3  # N1-N2 first; N3 only if the subtopic runs out
        client.post("/learn/checkpoint/answer", data=_form(question))
        assert client.get("/learn/checkpoint/feedback").status_code == 200
    resp = client.get("/learn/checkpoint/result")
    assert resp.status_code == 200 and "Aprovado" in resp.get_data(as_text=True)
    progress = db.session.get(SubtopicProgress, subtopic.id)
    assert progress.status == "practicing" and progress.level == 2

    # Practice: answer one wrong, tag the reason.
    client.get(f"/study/subtopic/{subtopic.id}")
    assert client.get("/study/question").status_code == 200
    question = _current(client, "practice")
    client.post("/study/answer", data=_form(question, correct=False))
    resp = client.get("/study/feedback")
    assert resp.status_code == 200 and "Você errou" in resp.get_data(as_text=True)
    resp = client.post(f"/review/reason/{question.id}", data={"reason": "concept", "note": "rever"})
    assert resp.status_code == 200
    item = ReviewItem.query.filter_by(question_id=question.id).one()
    assert item.error_reason == "concept" and item.note == "rever"
    assert client.post("/study/end").status_code == 302

    # Everything due now -> review session (flashcards + the missed question).
    for it in ReviewItem.query.all():
        it.due_at = utcnow() - timedelta(minutes=1)
    db.session.commit()
    resp = client.get("/review/")
    assert resp.status_code == 302
    for _ in range(40):
        resp = client.get("/review/item")
        body = resp.get_data(as_text=True)
        if "Revisão concluída" in body:
            break
        if "flashcard" in body and 'name="grade"' in body:
            client.post("/review/flashcard", data={"grade": "good"})
        else:
            with client.session_transaction() as sess:
                state = sess["review"]
            rev_item = db.session.get(ReviewItem, state["queue"][state["idx"]])
            client.post("/review/answer", data=_form(rev_item.question))
            assert client.get("/review/feedback").status_code == 200
    else:
        pytest.fail("review never finished")
    assert Attempt.query.filter_by(mode="review").count() >= 1

    assert client.get("/").status_code == 200
    assert client.get(f"/question/{question.id}").status_code == 200
    assert client.get(f"/learn/{subtopic.id}/review").status_code == 200
    assert client.post(f"/learn/{subtopic.id}/review", data={"next": "/"}).status_code == 302


def _run_section(client, mock_id, answer_correct=True, max_questions=30):
    """Answers questions until the section's review screen shows up."""
    for _ in range(max_questions):
        exam = db.session.get(MockExam, mock_id)
        msec = next(s for s in sorted(exam.sections, key=lambda s: s.order) if s.ended_at is None)
        resp = client.get(f"/mock-exam/{mock_id}/section/{msec.id}")
        if resp.status_code == 302 and "/review" in resp.headers["Location"]:
            return msec
        assert resp.status_code == 200
        assert "badge lv" not in resp.get_data(as_text=True), "difficulty must be hidden in mocks"
        question = _current(client, f"mock_q_{msec.id}", field=None)
        client.post(f"/mock-exam/{mock_id}/section/{msec.id}/answer",
                    data={**_form(question, answer_correct), "bookmark": "1"})
    pytest.fail("section never ended")


def test_single_section_mock_with_edits(client):
    resp = client.post("/mock-exam/start", data={"kind": "section", "section_code": "QR"})
    mock = MockExam.query.one()
    assert resp.status_code == 302 and "/intro" in resp.headers["Location"]
    msec = _run_section(client, mock.id, answer_correct=False)
    assert len(msec.attempts) == 21
    levels = [a.difficulty_presented for a in msec.attempts]
    assert levels[0] == 3 and min(levels) <= 2  # CAT moved down after misses

    assert client.get(f"/mock-exam/{mock.id}/section/{msec.id}/review").status_code == 200
    # 3 edits allowed, the 4th is refused.
    for attempt in msec.attempts[:4]:
        client.post(f"/mock-exam/{mock.id}/section/{msec.id}/edit/{attempt.id}", data=_form(attempt.question, True))
    db.session.refresh(msec)
    assert msec.edits_used == 3
    assert sum(1 for a in msec.attempts if a.is_correct) == 3

    resp = client.post(f"/mock-exam/{mock.id}/section/{msec.id}/finish")
    assert resp.status_code == 302
    resp = client.get(f"/mock-exam/{mock.id}/results")
    assert resp.status_code == 200
    db.session.refresh(mock)
    assert mock.status == "completed" and mock.result.qr_scaled_score is not None
    assert mock.result.total_scaled_score is None
    # Answers were logged for the estimate and wrong ones queued for review.
    assert Attempt.query.filter_by(mode="mock_exam").count() == 21
    assert ReviewItem.query.filter_by(origin="mock").count() == 18
    # Mocks never touch levels.
    assert SubtopicProgress.query.filter(SubtopicProgress.level > 1).count() == 0
    attempt = MockExamAttempt.query.first()
    assert client.get(f"/mock-exam/{mock.id}/question/{attempt.id}").status_code == 200


def test_mock_pause_freezes_the_clock(client):
    client.post("/mock-exam/start", data={"kind": "section", "section_code": "VR"})
    mock = MockExam.query.one()
    msec = mock.sections[0]
    assert client.get(f"/mock-exam/{mock.id}/section/{msec.id}").status_code == 200
    resp = client.post(f"/mock-exam/{mock.id}/section/{msec.id}/pause")
    assert resp.headers["Location"].endswith(f"/section/{msec.id}/paused")
    # Every section screen bounces to the pause screen; answers are refused.
    resp = client.get(f"/mock-exam/{mock.id}/section/{msec.id}")
    assert "/paused" in resp.headers["Location"]
    assert "/paused" in client.get(f"/mock-exam/{mock.id}/resume").headers["Location"]
    question = _current(client, f"mock_q_{msec.id}", field=None)
    client.post(f"/mock-exam/{mock.id}/section/{msec.id}/answer", data=_form(question))
    assert MockExamAttempt.query.count() == 0

    # Simulate a 2-hour pause: longer than the section, yet no time is lost.
    db.session.refresh(msec)
    msec.paused_at -= timedelta(hours=2)
    msec.started_at -= timedelta(hours=2)
    db.session.commit()
    assert client.get(f"/mock-exam/{mock.id}/section/{msec.id}/paused").status_code == 200
    resp = client.post(f"/mock-exam/{mock.id}/section/{msec.id}/unpause")
    assert resp.headers["Location"].endswith(f"/section/{msec.id}")
    db.session.refresh(msec)
    assert msec.paused_at is None and msec.paused_seconds >= 2 * 3600 and msec.ended_at is None
    assert client.get(f"/mock-exam/{mock.id}/section/{msec.id}").status_code == 200
    assert _current(client, f"mock_q_{msec.id}", field=None).id == question.id

    client.post(f"/mock-exam/{mock.id}/section/{msec.id}/answer", data=_form(question))
    attempt = MockExamAttempt.query.one()
    assert attempt.time_spent_seconds < 60, "pause time must not count toward the question"
    db.session.refresh(mock)
    assert mock.pause_count == 1


def test_full_mock_with_break_and_no_repeats(client):
    client.post("/mock-exam/start", data={"kind": "full", "order": "VR → DI → QR"})
    mock = MockExam.query.one()
    assert [s.section.code for s in sorted(mock.sections, key=lambda s: s.order)] == ["VR", "DI", "QR"]

    msec = _run_section(client, mock.id)
    resp = client.post(f"/mock-exam/{mock.id}/section/{msec.id}/finish")
    assert "/break/" in resp.headers["Location"]
    resp = client.post(resp.headers["Location"], data={"take": "1"})
    assert resp.status_code == 200 and "Pausa" in resp.get_data(as_text=True)

    msec = _run_section(client, mock.id)
    resp = client.post(f"/mock-exam/{mock.id}/section/{msec.id}/finish")
    assert "/intro" in resp.headers["Location"]  # break already used: no second offer

    msec = _run_section(client, mock.id)
    client.post(f"/mock-exam/{mock.id}/section/{msec.id}/finish")
    db.session.refresh(mock)
    assert mock.status == "completed" and mock.result.total_scaled_score is not None
    assert mock.result.total_scaled_score >= 645  # all correct -> high score
    ids = [a.question_id for s in mock.sections for a in s.attempts]
    assert len(ids) == len(set(ids)), "a question repeated inside one mock"

    # RC passages come in groups like the real test.
    vr = next(s for s in mock.sections if s.section.code == "VR")
    set_ids = [a.question.set_id for a in vr.attempts]
    runs = [sid for i, sid in enumerate(set_ids) if sid and (i == 0 or set_ids[i - 1] != sid)]
    assert len(runs) == len(set(runs)), "passage questions were split apart"

    assert client.get("/mock-exam/history").status_code == 200
    assert client.get("/progress/").status_code == 200


def test_settings_and_official_scores(client):
    resp = client.post("/settings/", data={"exam_date": "2026-12-15", "target_score": "645", "daily_minutes": "120",
                                           "auto_demotion": "1", "use_calibration": "1"})
    assert resp.status_code == 302
    body = client.get("/").get_data(as_text=True)
    assert "dias até a prova" in body
    resp = client.post("/progress/official", data={"taken_on": "2026-09-20", "source": "OPE 1", "total": "595",
                                                   "qr": "80", "vr": "79", "di": "76"})
    assert resp.status_code == 302
    assert "OPE 1" in client.get("/progress/").get_data(as_text=True)


def test_flag_question_removes_it_from_rotation(client):
    question = Question.query.first()
    client.post(f"/question/{question.id}/flag", data={"note": "gabarito errado"})
    db.session.refresh(question)
    assert question.flagged
    assert "gabarito errado" in client.get("/question/flagged").get_data(as_text=True)


def test_focused_practice_resumes_todays_count_after_ending(client):
    sub = Subtopic.query.filter_by(code="qr_arithmetic_fractions_decimals_percent").one()
    url = f"/study/focus?subtopics={sub.id}&goal=10"
    client.get(url)
    for _ in range(3):
        client.get("/study/question")
        client.post("/study/answer", data=_form(_current(client, "practice")))
    client.post("/study/end")
    client.get(url)
    with client.session_transaction() as sess:
        assert sess["practice"]["done_before"] == 3
    page = client.get("/study/question").get_data(as_text=True)
    assert "questão 4 de 10" in page


def test_practice_never_repeats_and_stops_when_unseen_questions_run_out(client):
    sub = Subtopic.query.filter_by(code="qr_arithmetic_fractions_decimals_percent").one()
    total = Question.query.filter_by(subtopic_id=sub.id, status="active").count()
    client.get(f"/study/subtopic/{sub.id}")
    seen = []
    for _ in range(total):
        client.get("/study/question")
        q = _current(client, "practice")
        seen.append(q.id)
        client.post("/study/answer", data=_form(q))
    assert len(seen) == len(set(seen)) == total
    page = client.get("/study/question").get_data(as_text=True)
    assert "todas as questões inéditas" in page
