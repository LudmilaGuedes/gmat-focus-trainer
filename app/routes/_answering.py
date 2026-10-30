"""Shared helpers for every screen that serves a question (practice,
checkpoint, review, mock exam)."""

from datetime import datetime

from flask import request

from app.services.grading import build_answer_groups
from app.timeutils import utcnow

MAX_COUNTED_SECONDS = 20 * 60  # a question left open over lunch shouldn't wreck the stats


def parse_answer(question):
    groups = build_answer_groups(question)
    return {key: request.form.get(f"group_{key}") for key in groups}


def group_labels(question):
    """Human label for each answer group (statement text / part label)."""
    media = question.media_json or {}
    labels = {}
    for statement in media.get("statements") or []:
        labels[statement.get("key")] = statement.get("text")
    for key, text in (media.get("part_labels") or {}).items():
        labels[key] = text
    return labels


def answer_breakdown(question, selected):
    """[{key, label, options: [{option, selected, correct}], ok}] for the
    feedback screen: what you chose vs. the right answer, per group."""
    labels = group_labels(question)
    rows = []
    for key, options in build_answer_groups(question).items():
        chosen = str(selected.get(key)) if selected and selected.get(key) is not None else None
        opts = [{"option": o, "selected": chosen == str(o.id), "correct": o.is_correct} for o in options]
        rows.append({
            "key": key,
            "label": labels.get(key),
            "options": opts,
            "ok": any(o["selected"] and o["correct"] for o in opts),
        })
    return rows


def stamp():
    return utcnow().isoformat()


def seconds_since(iso_stamp):
    if not iso_stamp:
        return None
    try:
        elapsed = (utcnow() - datetime.fromisoformat(iso_stamp)).total_seconds()
    except ValueError:
        return None
    return int(max(0, min(elapsed, MAX_COUNTED_SECONDS)))


def form_guessed():
    return request.form.get("guessed") in ("1", "on", "true")
