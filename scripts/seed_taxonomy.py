"""Loads <content bank>/taxonomy_seed.yaml into the sections / content_areas /
subtopics / question_types tables, and <content bank>/study_plan.yaml into the
subtopics' track order (content bank = app.config["CONTENT_BANK_DIR"], see
config.py). Idempotent: upserts by `code`, safe to re-run after editing the YAML."""

import os
import sys

import yaml
from flask import current_app

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.settings import DEFAULT_SETTINGS, AppSetting  # noqa: E402
from app.models.taxonomy import ContentArea, QuestionType, Section, Subtopic  # noqa: E402


def _bank_file(name):
    return os.path.join(current_app.config["CONTENT_BANK_DIR"], name)


def seed():
    with open(_bank_file("taxonomy_seed.yaml"), "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for qt in data.get("question_types", []):
        row = QuestionType.query.filter_by(code=qt["code"]).first()
        if row is None:
            row = QuestionType(code=qt["code"])
            db.session.add(row)
        row.name = qt["name"]

    for section_order, section_data in enumerate(data.get("sections", [])):
        section = Section.query.filter_by(code=section_data["code"]).first()
        if section is None:
            section = Section(code=section_data["code"])
            db.session.add(section)
        section.name = section_data["name"]
        section.description = section_data.get("description")
        section.order = section_order
        db.session.flush()

        for ca_order, ca_data in enumerate(section_data.get("content_areas", [])):
            content_area = ContentArea.query.filter_by(code=ca_data["code"]).first()
            if content_area is None:
                content_area = ContentArea(code=ca_data["code"])
                db.session.add(content_area)
            content_area.section_id = section.id
            content_area.name = ca_data["name"]
            content_area.description = ca_data.get("description")
            content_area.order = ca_order
            db.session.flush()

            for st_order, st_data in enumerate(ca_data.get("subtopics", [])):
                subtopic = Subtopic.query.filter_by(code=st_data["code"]).first()
                if subtopic is None:
                    subtopic = Subtopic(code=st_data["code"])
                    db.session.add(subtopic)
                subtopic.content_area_id = content_area.id
                subtopic.name = st_data["name"]
                subtopic.description = st_data.get("description")
                subtopic.order = st_order

    db.session.flush()
    seed_study_plan()
    seed_default_settings()
    db.session.commit()
    print("Taxonomia e trilha carregadas com sucesso.")


def seed_study_plan():
    study_plan_file = _bank_file("study_plan.yaml")
    if not os.path.exists(study_plan_file):
        return
    with open(study_plan_file, "r", encoding="utf-8") as f:
        plan = yaml.safe_load(f) or {}
    for subtopic in Subtopic.query.all():
        subtopic.track_order = None
        subtopic.track_phase = None
    order = 0
    for block_no, block in enumerate(plan.get("blocks", []), start=1):
        for code in block.get("subtopics", []):
            subtopic = Subtopic.query.filter_by(code=code).first()
            if subtopic is None:
                raise ValueError(f"study_plan.yaml: unknown subtopic '{code}'")
            order += 1
            subtopic.track_order = order
            subtopic.track_phase = block_no


def seed_default_settings():
    for key, value in DEFAULT_SETTINGS.items():
        if AppSetting.query.get(key) is None:
            db.session.add(AppSetting(key=key, value=value))


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed()
