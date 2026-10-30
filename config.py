import os
import secrets

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
SAMPLE_BANK_DIR = os.path.join(BASE_DIR, "sample_bank")
PRIVATE_BANK_DIR = os.path.join(BASE_DIR, "content_bank")


def _env_flag(name, default=False):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


def resolve_content_bank_dir():
    """GMAT_CONTENT_DIR if set; else the private bank (content_bank/, kept out of git) when it
    exists; else the sample bank that ships with the repository."""
    explicit = os.environ.get("GMAT_CONTENT_DIR")
    if explicit:
        return os.path.abspath(explicit)
    return PRIVATE_BANK_DIR if os.path.isdir(PRIVATE_BANK_DIR) else SAMPLE_BANK_DIR


class Config:
    DEMO_MODE = _env_flag("DEMO_MODE")
    # Local use can live with a fixed key; a public demo without SECRET_KEY gets a random one per boot.
    SECRET_KEY = os.environ.get("SECRET_KEY") or (secrets.token_hex(32) if DEMO_MODE else "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(INSTANCE_DIR, "gmat_trainer.sqlite3")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CONTENT_BANK_DIR = resolve_content_bank_dir()
    # Public demo (served over HTTPS): no curation UI, and session cookies sent only over HTTPS.
    if DEMO_MODE:
        SESSION_COOKIE_SECURE = True


class TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    CONTENT_BANK_DIR = SAMPLE_BANK_DIR
