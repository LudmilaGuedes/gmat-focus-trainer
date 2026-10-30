"""Generic answer grading shared by all 6 GMAT Focus question types.

A question's AnswerOption rows are grouped by `group_key` (None -> a single
implicit group called "single"). Multi-part types (Table Analysis, Two-Part
Analysis, Graphics Interpretation, Multi-Source Reasoning statement sets)
use several groups; simple multiple choice / data sufficiency use just one.
The GMAT does not give partial credit, so ALL groups must match their
correct option for the question to count as correct.
"""


def build_answer_groups(question):
    groups = {}
    for opt in question.options:
        key = opt.group_key or "single"
        groups.setdefault(key, []).append(opt)
    return groups


def grade_answer(question, selected_answer):
    """selected_answer: dict {group_key: option_id}. option_id may be a str
    (as posted from an HTML form) or an int."""
    groups = build_answer_groups(question)
    if not groups:
        return False
    for group_key, options in groups.items():
        correct_option = next((o for o in options if o.is_correct), None)
        selected_id = selected_answer.get(group_key)
        if correct_option is None or selected_id is None:
            return False
        if str(selected_id) != str(correct_option.id):
            return False
    return True
