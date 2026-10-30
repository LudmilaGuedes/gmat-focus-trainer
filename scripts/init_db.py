"""Sets up a working database from scratch (or brings an existing one up to date):

  1. applies the Alembic migrations (creates the SQLite file if it does not exist),
  2. loads the taxonomy, the study track and the default settings,
  3. imports the questions and lessons of the content bank.

Every step is idempotent, so it is safe to run on every start (the Docker demo does).
Usage: python scripts/init_db.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import current_app  # noqa: E402
from flask_migrate import upgrade  # noqa: E402

from app import create_app  # noqa: E402
from config import BASE_DIR, INSTANCE_DIR  # noqa: E402

import import_questions  # noqa: E402
import seed_taxonomy  # noqa: E402


def main():
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    app = create_app()
    with app.app_context():
        upgrade(directory=os.path.join(BASE_DIR, "migrations"))
        seed_taxonomy.seed()
        total, lessons = import_questions.import_all()
        print(f"Banco pronto: {total} questões e {lessons} lições de {current_app.config['CONTENT_BANK_DIR']}.")


if __name__ == "__main__":
    main()
