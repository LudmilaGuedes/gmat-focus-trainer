"""Validates the content banks: the public sample_bank/ always, and the private
content_bank/ when it exists on this machine (it is kept out of git). Both must
import cleanly, every question must be well-formed, and numeric answers are
machine-checked where the YAML has an `answer_check`. The private (full) bank
must also have enough questions per subtopic and level for the track and for
full-length mock exams; the sample bank must show every question type and level."""

import glob
import math
import os
import re
import sys
from collections import Counter
from fractions import Fraction

import pytest
import yaml

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import import_questions as import_questions_module  # noqa: E402
import seed_taxonomy as seed_taxonomy_module  # noqa: E402

from app.models.question_bank import AnswerOption, Flashcard, Lesson, Question  # noqa: E402
from app.models.taxonomy import Section, Subtopic  # noqa: E402
from config import PRIVATE_BANK_DIR, SAMPLE_BANK_DIR  # noqa: E402

DS_OPTIONS = [
    "Statement (1) ALONE is sufficient, but statement (2) alone is not sufficient.",
    "Statement (2) ALONE is sufficient, but statement (1) alone is not sufficient.",
    "BOTH statements TOGETHER are sufficient, but NEITHER statement ALONE is sufficient.",
    "EACH statement ALONE is sufficient.",
    "Statements (1) and (2) TOGETHER are NOT sufficient.",
]


@pytest.fixture(params=[SAMPLE_BANK_DIR, PRIVATE_BANK_DIR], ids=["sample", "private"])
def bank_dir(request):
    if not os.path.isdir(request.param):
        pytest.skip("no private content bank on this machine")
    return request.param


@pytest.fixture
def bank_app(app, bank_dir):
    app.config["CONTENT_BANK_DIR"] = bank_dir
    return app


def _is_private(bank_dir):
    return bank_dir == PRIVATE_BANK_DIR


def _full_import():
    seed_taxonomy_module.seed()
    return import_questions_module.import_all()


def _yaml_questions(bank_dir):
    for path in sorted(glob.glob(os.path.join(bank_dir, "questions", "**", "*.yaml"), recursive=True)):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for q in data.get("questions", []):
            yield path, q


def test_content_bank_imports_without_errors(bank_app):
    total, lessons = _full_import()
    assert Section.query.count() == 3
    assert total == Question.query.count()
    assert lessons == Lesson.query.count()

    for question in Question.query.all():
        options = AnswerOption.query.filter_by(question_id=question.id).all()
        assert options, f"{question.slug} has no answer options"
        groups = {}
        for opt in options:
            groups.setdefault(opt.group_key, []).append(opt)
        for group_key, group_options in groups.items():
            correct = [o for o in group_options if o.is_correct]
            assert len(correct) == 1, f"{question.slug} group {group_key} has {len(correct)} correct options"
            labels = [o.option_label for o in group_options]
            assert len(labels) == len(set(labels)), f"{question.slug} group {group_key} repeats labels"
        assert 1 <= question.difficulty <= 5


def test_import_is_idempotent_on_slug(bank_app):
    _full_import()
    first = (Question.query.count(), Lesson.query.count(), Flashcard.query.count())
    _full_import()
    assert (Question.query.count(), Lesson.query.count(), Flashcard.query.count()) == first


def test_slugs_are_unique_across_files(bank_dir):
    seen = {}
    for path, q in _yaml_questions(bank_dir):
        assert q["slug"] not in seen, f"duplicate slug {q['slug']} in {path} and {seen.get(q['slug'])}"
        seen[q["slug"]] = path


# Verbal answer options are written so the correct one is not given away by being the longest
# (on the real exam it is the longest about as often as chance, ~20%).
LENGTH_BALANCED_PREFIX = "vr_"


def test_correct_answer_is_not_usually_the_longest_option(bank_dir):
    stats = {}
    for _, q in _yaml_questions(bank_dir):
        if not q["subtopic"].startswith(LENGTH_BALANCED_PREFIX) or q["question_type"] != "multiple_choice":
            continue
        options = q["options"]
        longest = max(len(o["text"]) for o in options)
        correct = next(o for o in options if o["correct"])
        total, longest_count = stats.get(q["subtopic"], (0, 0))
        stats[q["subtopic"]] = (total + 1, longest_count + (len(correct["text"]) == longest))
    for subtopic, (total, longest_count) in stats.items():
        assert longest_count / total <= 0.35, (
            f"{subtopic}: correct answer is the longest option in {longest_count}/{total} questions"
        )


def test_answer_positions_are_balanced(bank_dir):
    """No answer letter / position / truth value should be predictable from the bank's habits."""
    letters = {}   # pool -> Counter of correct letters among 5-option single-answer questions
    truth = [0, 0]  # [true statements, all statements] in Table Analysis and MSR yes/no items
    middle = [0, 0]  # [middle correct, all] in 3-option Graphics Interpretation dropdowns
    for _, q in _yaml_questions(bank_dir):
        groups = {}
        for o in q["options"]:
            groups.setdefault(o.get("group"), []).append(o)
        if len(groups) == 1 and len(q["options"]) == 5:
            pool = q["question_type"] if q["question_type"] != "multiple_choice" else q["subtopic"][:2]
            idx = [o["correct"] for o in q["options"]].index(True)
            letters.setdefault(pool, Counter())["ABCDE"[idx]] += 1
        elif q["question_type"] in ("table_analysis", "multi_source_reasoning"):
            for opts in groups.values():
                if len(opts) == 2:
                    truth[0] += opts[0]["correct"]
                    truth[1] += 1
        elif q["question_type"] == "graphics_interpretation":
            for opts in groups.values():
                if len(opts) == 3:
                    middle[0] += opts[1]["correct"]
                    middle[1] += 1
    for pool, counts in letters.items():
        total = sum(counts.values())
        if total >= 40:
            letter, n = counts.most_common(1)[0]
            assert n / total <= 0.30, f"{pool}: answer {letter} is correct in {n}/{total} questions"
    assert 0.40 <= truth[0] / truth[1] <= 0.60, f"{truth[0]}/{truth[1]} true/false statements are true"
    assert middle[0] / middle[1] <= 0.45, f"middle dropdown option is correct in {middle[0]}/{middle[1]}"


def test_question_shapes_match_their_type(bank_dir):
    for path, q in _yaml_questions(bank_dir):
        qtype, options, media = q["question_type"], q["options"], q.get("media") or {}
        groups = {o.get("group") for o in options}
        where = f"{q['slug']} ({os.path.basename(path)})"
        if qtype in ("multiple_choice", "data_sufficiency"):
            assert groups == {None}, where
            assert len(options) == 5, f"{where}: GMAT single-answer questions have 5 options"
        if qtype == "data_sufficiency":
            assert [o["text"] for o in options] == DS_OPTIONS, f"{where}: non-standard DS options"
            assert "(1)" in (q.get("stimulus") or "") and "(2)" in q["stimulus"], where
        if qtype == "two_part_analysis":
            assert groups == {"part1", "part2"}, where
        if qtype in ("table_analysis", "graphics_interpretation") or (qtype == "multi_source_reasoning" and media.get("statements")):
            keys = {s["key"] for s in media.get("statements", [])}
            assert keys and keys == groups, f"{where}: statements {keys} vs option groups {groups}"
        if qtype == "table_analysis":
            table = media["table"]
            assert all(len(row) == len(table["columns"]) for row in table["rows"]), where
        if qtype == "multi_source_reasoning":
            assert q.get("question_set"), where
        assert q["explanation"].strip(), where


def _as_number(text):
    """Leading number of an option ('$1,200', '210 km', '3/5', '−51', '15.2%')."""
    cleaned = str(text).replace("$", "").replace(",", "").replace("−", "-").strip()
    match = re.match(r"^(-?\d+(?:\.\d+)?)(?:\s*/\s*(\d+))?", cleaned)
    if not match:
        raise ValueError(text)
    if match.group(2):
        return float(Fraction(int(match.group(1)), int(match.group(2))))
    return float(match.group(1))


def test_numeric_answers_are_machine_checked(bank_dir):
    """`answer_check` is a Python expression that must evaluate to the value of
    the option marked correct — catches arithmetic slips in the explanations."""
    env = {"math": math, "sqrt": math.sqrt, "comb": math.comb, "perm": math.perm,
           "factorial": math.factorial, "Fraction": Fraction, "gcd": math.gcd, "lcm": math.lcm}
    checked = 0
    for path, q in _yaml_questions(bank_dir):
        expr = q.get("answer_check")
        if expr is None:
            continue
        correct = next(o for o in q["options"] if o.get("correct"))
        expected = eval(str(expr), {"__builtins__": {}}, env)  # noqa: S307 - trusted local content
        assert math.isclose(float(expected), _as_number(correct["text"]), rel_tol=1e-6, abs_tol=1e-9), (
            f"{q['slug']}: answer_check gives {expected}, correct option says {correct['text']}"
        )
        others = [o for o in q["options"] if not o.get("correct")]
        for o in others:
            try:
                value = _as_number(o["text"])
            except ValueError:
                continue
            assert not math.isclose(float(expected), value, rel_tol=1e-9), f"{q['slug']}: two options equal the answer"
        checked += 1
    assert checked >= (100 if _is_private(bank_dir) else 20)


def test_every_subtopic_has_a_lesson_and_questions(bank_app, bank_dir):
    _full_import()
    for subtopic in Subtopic.query.all():
        lesson = Lesson.query.filter_by(subtopic_id=subtopic.id).first()
        assert lesson is not None, f"{subtopic.code} has no lesson"
        assert Flashcard.query.filter_by(lesson_id=lesson.id).count() >= 3, f"{subtopic.code}: <3 flashcards"
        by_level = {}
        for q in Question.query.filter_by(subtopic_id=subtopic.id, status="active").all():
            by_level[q.difficulty] = by_level.get(q.difficulty, 0) + 1
        assert by_level, f"{subtopic.code} has no questions"
        if not _is_private(bank_dir):
            continue
        assert by_level.get(1, 0) + by_level.get(2, 0) >= 3, f"{subtopic.code}: checkpoint needs N1-N2 questions {by_level}"
        assert by_level.get(3, 0) >= 2, f"{subtopic.code}: needs N3 questions {by_level}"
        assert by_level.get(4, 0) + by_level.get(5, 0) >= 2, f"{subtopic.code}: needs N4/N5 questions {by_level}"


def test_sample_bank_shows_every_question_type_and_level(app):
    _full_import()
    from app.models.taxonomy import QuestionType

    used_types = {q.question_type_id for q in Question.query.all()}
    assert used_types == {t.id for t in QuestionType.query.all()}
    assert {q.difficulty for q in Question.query.all()} == {1, 2, 3, 4, 5}
    for subtopic in Subtopic.query.filter(Subtopic.track_order.isnot(None)).order_by(Subtopic.track_order).limit(1):
        easy = Question.query.filter(Question.subtopic_id == subtopic.id, Question.difficulty <= 3).count()
        assert easy >= 5, "the first track subtopic needs a full checkpoint (5 questions up to N3)"


def test_mock_exam_has_enough_questions_per_section(bank_app, bank_dir):
    if not _is_private(bank_dir):
        pytest.skip("the sample bank is too small for full-length mocks (sections end early instead)")
    _full_import()
    from app.models.taxonomy import ContentArea

    for section, needed in (("QR", 21), ("VR", 23), ("DI", 20)):
        sec = Section.query.filter_by(code=section).one()
        area_ids = [c.id for c in ContentArea.query.filter_by(section_id=sec.id)]
        sub_ids = [s.id for s in Subtopic.query.filter(Subtopic.content_area_id.in_(area_ids))]
        for level in (3, 4):
            n = Question.query.filter(Question.subtopic_id.in_(sub_ids), Question.difficulty == level).count()
            assert n >= needed, f"{section} has only {n} N{level} questions for mocks"
