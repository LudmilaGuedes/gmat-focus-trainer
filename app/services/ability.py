"""Ability (theta) estimation — the engine behind every score estimate.

A small 3-parameter-logistic IRT model with FIXED item parameters taken from
the question's level (app/levels.py), estimated by maximum a posteriori over
a grid. Real IRT calibrates each item from thousands of test takers; here
the level's `b` is the calibration, which is why each level was written to
match a real GMAT score band. The same function is used by:

  * the mock-exam CAT (responses of one section, unweighted), and
  * the study-mode estimate (first attempts per question in the last months,
    recency-weighted so old mistakes fade out as you improve).

    P(correct | theta) = c + (1 - c) / (1 + exp(-a * (theta - b)))

c (guessing floor) is 0.2 for 5-option single-answer questions and ~0 for
multi-part Data Insights questions (all parts must be right).
"""

import math

from app.levels import level_b, section_score_from_theta

DISCRIMINATION = 1.3
PRIOR_MEAN = -0.6  # ~ the GMAT median section score (77-78)
PRIOR_SD = 1.5
THETA_GRID = [x / 50 for x in range(-200, 201)]  # -4.0 .. 4.0 step 0.02

GUESSING_BY_TYPE = {
    "multiple_choice": 0.2,
    "data_sufficiency": 0.2,
    "two_part_analysis": 0.04,
    "table_analysis": 0.08,
    "graphics_interpretation": 0.08,
    "multi_source_reasoning": 0.1,
}


def guessing_for(question_type_code):
    return GUESSING_BY_TYPE.get(question_type_code, 0.2)


def p_correct(theta, level, guessing=0.2):
    b = level_b(level)
    return guessing + (1 - guessing) / (1 + math.exp(-DISCRIMINATION * (theta - b)))


def estimate_theta(responses, prior_mean=PRIOR_MEAN, prior_sd=PRIOR_SD):
    """responses: iterable of (level, is_correct, guessing, weight) — the last
    two optional. Returns (theta, standard_error)."""
    normalized = []
    for r in responses:
        level, is_correct = r[0], r[1]
        guessing = r[2] if len(r) > 2 and r[2] is not None else 0.2
        weight = r[3] if len(r) > 3 and r[3] is not None else 1.0
        normalized.append((level, bool(is_correct), guessing, weight))

    best_theta, best_ll = prior_mean, -math.inf
    log_posts = []
    for theta in THETA_GRID:
        ll = -((theta - prior_mean) ** 2) / (2 * prior_sd ** 2)
        for level, is_correct, guessing, weight in normalized:
            p = p_correct(theta, level, guessing)
            p = min(max(p, 1e-9), 1 - 1e-9)
            ll += weight * (math.log(p) if is_correct else math.log(1 - p))
        log_posts.append(ll)
        if ll > best_ll:
            best_theta, best_ll = theta, ll

    # Posterior SD from the grid (robust even when the curve is flat/skewed).
    peak = max(log_posts)
    weights = [math.exp(lp - peak) for lp in log_posts]
    total = sum(weights)
    mean = sum(t * w for t, w in zip(THETA_GRID, weights)) / total
    var = sum(((t - mean) ** 2) * w for t, w in zip(THETA_GRID, weights)) / total
    return best_theta, math.sqrt(var)


def section_estimate(responses, **kwargs):
    """Returns dict(theta, se, score, low, high) for a section."""
    theta, se = estimate_theta(responses, **kwargs)
    return {
        "theta": theta,
        "se": se,
        "score": section_score_from_theta(theta),
        "low": section_score_from_theta(theta - se),
        "high": section_score_from_theta(theta + se),
    }


def nearest_level(theta):
    """The level whose b is closest to theta — the most informative next item."""
    from app.levels import LEVELS

    return min(LEVELS, key=lambda lvl: abs(level_b(lvl) - theta))
