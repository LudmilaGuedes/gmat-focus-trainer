"""The 5 difficulty levels and how they map onto the real GMAT Focus score scale.

Every question has an integer `difficulty` 1..5. Each level has an IRT-style
difficulty parameter `b` on the same latent scale as the ability estimate
theta used everywhere in the app (study-mode score estimate and the mock
exam CAT). A section score is a linear function of theta:

    section_score = 80 + 4 * theta      (clipped to the official 60-90)

so each level is anchored to the section score (and the total score, if all
three sections were at that level) of someone who gets ~50% of that level's
non-guessable questions right. The anchors were chosen from public GMAT
Focus score distributions (median total ~555, section medians ~77-81):

    level  b      section  total   "who gets ~60-70% right here"
    1     -2.5    70       ~405    fundamentals (school math / basic reading)
    2     -1.25   75       ~505    below the median
    3      0.0    80       ~605    solid, around the 70th percentile
    4      1.0    84       ~685    the 645-705 band
    5      2.0    88       ~765    top 5%

A 645 total is ~82 per section, i.e. theta ~0.5: roughly 70% right at
level 3 and 50% at level 4 (with the 20% guessing floor of 5-option
questions). See app/services/ability.py for the estimator.
"""

LEVELS = (1, 2, 3, 4, 5)
MIN_LEVEL, MAX_LEVEL = 1, 5

LEVEL_INFO = {
    1: {"name": "Fundamentos", "short": "N1", "b": -2.5, "band": "até ~455"},
    2: {"name": "Básico", "short": "N2", "b": -1.25, "band": "~455-555"},
    3: {"name": "Intermediário", "short": "N3", "b": 0.0, "band": "~555-645"},
    4: {"name": "Avançado", "short": "N4", "b": 1.0, "band": "~645-705"},
    5: {"name": "Expert", "short": "N5", "b": 2.0, "band": "705+"},
}

# Old 3-level bank (easy/medium/hard) was systematically too easy for its
# labels; it maps one tier down onto the new scale.
LEGACY_DIFFICULTY_MAP = {"easy": 1, "medium": 2, "hard": 3}

SECTION_SCORE_MIN, SECTION_SCORE_MAX = 60, 90
TOTAL_SCORE_MIN, TOTAL_SCORE_MAX = 205, 805
SECTION_SCORE_AT_THETA_0 = 80
SECTION_POINTS_PER_THETA = 4

# Official pacing: 45 min per section.
TARGET_SECONDS_BY_SECTION = {"QR": 128, "VR": 117, "DI": 135}


def level_b(level):
    return LEVEL_INFO[int(level)]["b"]


def level_name(level):
    return LEVEL_INFO[int(level)]["name"]


def normalize_difficulty(value):
    """Accepts 1..5 (int or numeric str) or a legacy 'easy'/'medium'/'hard'."""
    if isinstance(value, str) and value in LEGACY_DIFFICULTY_MAP:
        return LEGACY_DIFFICULTY_MAP[value]
    level = int(value)
    if level not in LEVEL_INFO:
        raise ValueError(f"difficulty must be 1..5, got {value!r}")
    return level


def clamp_level(level):
    return max(MIN_LEVEL, min(MAX_LEVEL, int(level)))


def section_score_from_theta(theta):
    raw = SECTION_SCORE_AT_THETA_0 + SECTION_POINTS_PER_THETA * theta
    return int(max(SECTION_SCORE_MIN, min(SECTION_SCORE_MAX, round(raw))))


def theta_from_section_score(score):
    return (score - SECTION_SCORE_AT_THETA_0) / SECTION_POINTS_PER_THETA


def total_score_from_sections(qr, vr, di):
    """Linear map of the sum of 3 section scores onto 205-805, on the
    official 205, 215, ..., 805 grid (anchored at 205, not at 0)."""
    total = qr + vr + di
    min_sum, max_sum = SECTION_SCORE_MIN * 3, SECTION_SCORE_MAX * 3
    raw = TOTAL_SCORE_MIN + (total - min_sum) / (max_sum - min_sum) * (TOTAL_SCORE_MAX - TOTAL_SCORE_MIN)
    raw = max(TOTAL_SCORE_MIN, min(TOTAL_SCORE_MAX, raw))
    steps = int((raw - TOTAL_SCORE_MIN) / 10 + 0.5)
    return TOTAL_SCORE_MIN + steps * 10


def section_score_for_total(total):
    """Average per-section score needed for a given total (inverse of the above)."""
    return SECTION_SCORE_MIN + (total - TOTAL_SCORE_MIN) / 20


def target_level_for_score(target_total):
    """The practice level a subtopic must reach to be 'at target': the level
    whose b is just above the target theta (you should be practicing where
    you still miss some)."""
    theta = theta_from_section_score(section_score_for_total(target_total))
    for level in LEVELS:
        if LEVEL_INFO[level]["b"] >= theta:
            return level
    return MAX_LEVEL
