"""Copies the SQLite database to instance/backups/ with a timestamp.
Run it before migrations or big imports: python scripts/backup_db.py"""

import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "instance", "gmat_trainer.sqlite3")
BACKUP_DIR = os.path.join(BASE_DIR, "instance", "backups")


def main():
    if not os.path.exists(DB_PATH):
        print("Nenhum banco encontrado em", DB_PATH)
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    target = os.path.join(BACKUP_DIR, f"gmat_trainer_{datetime.now():%Y%m%d_%H%M%S}.sqlite3")
    # sqlite3's backup API gives a consistent copy even if the app is running.
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    print("Backup salvo em", target)


if __name__ == "__main__":
    main()
