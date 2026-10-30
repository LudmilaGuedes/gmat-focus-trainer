from app.levels import (
    normalize_difficulty,
    section_score_from_theta,
    target_level_for_score,
    total_score_from_sections,
)
from app.services.ability import estimate_theta, nearest_level, p_correct, section_estimate
from app.services.cat_engine import ThetaCat


def test_total_score_bounds_and_grid():
    assert total_score_from_sections(60, 60, 60) == 205
    assert total_score_from_sections(90, 90, 90) == 805
    score = total_score_from_sections(75, 70, 80)
    assert 205 <= score <= 805 and (score - 205) % 10 == 0


def test_645_is_about_82_per_section():
    assert total_score_from_sections(82, 82, 82) == 645


def test_target_level_for_645_is_4():
    assert target_level_for_score(645) == 4
    assert target_level_for_score(555) == 3
    assert target_level_for_score(725) == 5


def test_normalize_difficulty_accepts_legacy_labels():
    assert normalize_difficulty("easy") == 1
    assert normalize_difficulty("hard") == 3
    assert normalize_difficulty(5) == 5


def test_probability_is_monotonic():
    assert p_correct(1.0, 3) > p_correct(0.0, 3) > p_correct(-1.0, 3)
    assert p_correct(0.0, 1) > p_correct(0.0, 5)


def test_more_correct_answers_mean_higher_theta():
    low, _ = estimate_theta([(3, False)] * 8 + [(3, True)] * 2)
    high, _ = estimate_theta([(3, True)] * 8 + [(3, False)] * 2)
    assert high > low


def test_correct_hard_answers_beat_correct_easy_answers():
    easy, _ = estimate_theta([(1, True)] * 10)
    hard, _ = estimate_theta([(4, True)] * 10)
    assert hard > easy


def test_uncertainty_shrinks_with_data():
    _, se_few = estimate_theta([(3, True), (3, False)])
    _, se_many = estimate_theta([(3, True), (3, False)] * 15)
    assert se_many < se_few


def test_simulated_645_profile_lands_near_645():
    # ~72% at N3 and ~48% at N4 is the expected profile of a 645 test taker.
    responses = [(3, i % 25 < 18) for i in range(25)] + [(4, i % 25 < 12) for i in range(25)]
    est = section_estimate(responses)
    assert 80 <= est["score"] <= 84


def test_section_score_is_clipped():
    assert section_score_from_theta(-10) == 60
    assert section_score_from_theta(10) == 90


def test_cat_starts_at_level_3_and_adapts():
    cat = ThetaCat()
    assert cat.next_level() == 3
    for _ in range(5):
        cat.record_response(cat.next_level(), True)
    assert cat.next_level() >= 4
    down = ThetaCat()
    for _ in range(5):
        down.record_response(down.next_level(), False)
    assert down.next_level() <= 2


def test_unanswered_questions_are_penalized():
    cat = ThetaCat([(3, True, 0.2)] * 10)
    assert cat.final_estimate(unanswered=8)["score"] < cat.final_estimate(unanswered=0)["score"]


def test_nearest_level():
    assert nearest_level(0.1) == 3
    assert nearest_level(0.9) == 4
    assert nearest_level(-3) == 1
