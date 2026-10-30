"""Dev helper: drops and recreates all tables. Requires --confirm."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402


def main():
    if "--confirm" not in sys.argv:
        print("Isso apaga TODOS os dados locais (progresso, simulados, respostas).")
        print("Rode novamente com --confirm para prosseguir: python scripts/reset_db.py --confirm")
        return
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
    print("Banco recriado do zero. Rode seed_taxonomy.py e import_questions.py em seguida.")


if __name__ == "__main__":
    main()
