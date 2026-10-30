# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal, local-only Flask study platform for the GMAT Focus Edition: a study track (lesson → checkpoint →
practice per subtopic), adaptive practice on a 5-level difficulty scale calibrated to real score bands, spaced
repetition (missed questions + flashcards + theory), an error notebook, realistic timed mock exams with an
IRT-based CAT, a score estimator, and a daily plan ("Hoje"). Single user, SQLite, server-rendered Jinja2 +
htmx (no SPA, no build step). UI text is Portuguese; question stems are English, explanations Portuguese.

## Commands

Run everything from this directory (`gmat_focus_trainer/`), with the venv active.

```bash
pip install -r requirements-dev.txt
python scripts/init_db.py                   # migrations + taxonomy/track/settings + questions/lessons (idempotent)
python run.py                               # http://127.0.0.1:5000 (curation UI at /admin)

pytest                                      # full suite (content + end-to-end flows)
pytest tests/test_content_bank.py           # validate the YAML content bank(s) only
python scripts/backup_db.py                 # copy instance/gmat_trainer.sqlite3 to instance/backups/
```

The steps of `init_db.py` also exist separately: `flask db upgrade`, `scripts/seed_taxonomy.py`,
`scripts/import_questions.py`.

**Which content bank** (`config.resolve_content_bank_dir`): `GMAT_CONTENT_DIR` if set, else the private
`content_bank/` if it exists (gitignored: the author's full bank), else the public `sample_bank/` (68 original
questions, 16 lessons). Tests always run on `sample_bank/` (`TestConfig`); `test_content_bank.py` also validates the
private bank when present, with the stricter coverage rules. Never copy private-bank content into `sample_bank/`.

**Demo** (`Dockerfile`, Hugging Face Spaces): `DEMO_MODE=1` drops `/admin`, sets cross-site session cookies, and
generates a random `SECRET_KEY` if none is given.

New migrations: `flask db migrate -m "..."` (render_as_batch is on for SQLite). New NOT NULL columns need a
`server_default`. Back up the DB before upgrading.

## Architecture

**Levels are the backbone** (`app/levels.py`): every question has an integer `difficulty` 1..5, and each level
has an IRT difficulty `b` anchored to a real section-score band (section = 80 + 4θ; N3 ≈ 555-645, N4 ≈
645-705). `target_level_for_score(645) == 4`. Legacy easy/medium/hard map to 1/2/3.

**Ability / score** (`app/services/ability.py`, `estimates.py`): 3PL IRT with fixed item params from the level
(guessing depends on question type), MAP θ on a grid. The study-mode estimate uses only the FIRST attempt per
question in practice/checkpoint/mock modes (reviews excluded), recency-weighted (30-day half-life), and is
shifted by the mean gap to official practice-exam scores the user entered (`ExternalScore`). The total is only
shown once every section has ≥5 responses (`estimate["complete"]`).

**Per-subtopic progress** (`app/services/adaptive_study.py`): `SubtopicProgress.level` is the single source of
truth for what difficulty to serve. Lifecycle: `new` → lesson done (`checkpoint`) → checkpoint passed
(`practicing`). `maybe_adjust_level` promotes/demotes from the recent results at the current level or harder
**after the last `LevelAdjustment`** (`after_attempt_id`, not timestamps — Windows clock resolution is coarse).
Only `PRACTICE_MODES` ("study", "checkpoint") change levels; mock exams and reviews never do (hard requirement).
Manual changes go through `apply_manual_level_adjustment` and are logged.

**Spaced repetition** (`app/services/srs.py`): Leitner boxes (1, 3, 7, 14, 30, 60 days) in `ReviewItem` for
questions (missed / guessed / too slow / from mocks) and flashcards; theory reviews use
`SubtopicProgress.lesson_next_review_at`. `ReviewItem` doubles as the error notebook (error_reason, note).

**Daily plan** (`app/services/study_plan.py`): phase (1 Fundamentos … 4 Reta final), then tasks in order:
due reviews, due theory reviews, pending checkpoints, new lessons at the pace needed for the exam date,
focused practice on the weakest subtopics with the remaining minutes, weekly mock/official-exam suggestions.
Task completion is detected from today's activity (local day via `app/timeutils.py`).

**Question selection** (`app/services/question_selector.py`): freshness from the persistent attempt history
(never seen > least recently seen); nearest level first (lower first in study mode). Mock selection follows
the official content mix per section, keeps RC/MSR sets together, and avoids questions used in earlier mocks
or practiced in the last 21 days.

**Mock exams** (`app/routes/mock_exam.py`, `app/services/cat_engine.py`): full exam (section order chosen,
one optional 10-min break) or single section; CAT picks the level nearest the current θ; difficulty is hidden;
bookmarks + end-of-section review with up to 3 answer edits; unanswered questions are penalized. CAT state is
derived from `MockExamAttempt` rows (only the displayed question id lives in the session). Answers are logged
to `attempts` (mode `mock_exam`) and the review queue only when the section closes, so edits count.

**Content bank** (`sample_bank/` or the private `content_bank/`, schema in `sample_bank/README.md`): taxonomy, `study_plan.yaml` (track order), `lessons/*.yaml`
(Markdown lessons + key points + flashcards), `questions/**/*.yaml`. `answer_check` expressions are evaluated by
`tests/test_content_bank.py` against the correct option; that test also enforces per-subtopic coverage.

**One generic answer shape for all 6 question types**: `AnswerOption.group_key` turns single-answer types into
multi-part ones; `grading.py` requires every group correct. Templates: `study/_question_body.html` (passage/tabs
split layout) includes `study/_question_types/<code>.html`. Jinja filters: `mathfmt` (x^2, sqrt(, **bold**),
`reflow` (YAML-wrapped text → paragraphs, keeps "I."/"(1)" lines), `md` (lessons), `mmss`.

**Session cookie vs DB**: the cookie only holds the current activity (practice/checkpoint/review queue state,
current question id and when it was shown). Everything else is written to SQLite on every answer.

**Timestamps are naive UTC** (`app/timeutils.utcnow`); "today" for the plan uses `start_of_today()` (local day
expressed in naive UTC). Never mix tz-aware datetimes with DB values.
