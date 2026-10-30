"""Computer Adaptive Test engine for mock exams.

Each section keeps the list of (level, is_correct, guessing) responses; after
every answer the ability theta is re-estimated by MAP (app/services/ability.py)
and the next question is taken from the level whose difficulty is closest to
that estimate — the most informative item, which is how a real CAT behaves.
Because theta is always recomputed from ALL responses, editing an answer on
the end-of-section review screen is automatically reflected in the score.

Not the official GMAC algorithm (item parameters here come from each
question's level, not from a statistically calibrated bank), so results are
always labeled as an ESTIMATE in the UI.
"""

from app.services.ability import estimate_theta, nearest_level, section_estimate

FIRST_LEVEL = 3


class ThetaCat:
    def __init__(self, responses=()):
        self.responses = list(responses)

    def record_response(self, level, is_correct, guessing=0.2):
        self.responses.append((level, bool(is_correct), guessing))
        return self.theta()

    def theta(self):
        return estimate_theta(self.responses)[0]

    def next_level(self):
        if not self.responses:
            return FIRST_LEVEL
        return nearest_level(self.theta())

    def final_estimate(self, unanswered=0):
        """Unanswered questions count as wrong at the current level — the real
        test also penalizes not finishing a section."""
        responses = list(self.responses)
        if unanswered:
            level = nearest_level(self.theta()) if responses else FIRST_LEVEL
            responses += [(level, False, 0.2)] * unanswered
        return section_estimate(responses)
