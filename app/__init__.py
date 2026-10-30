import re

import markdown as markdown_lib
from flask import Flask
from markupsafe import Markup, escape

from config import Config
from app.extensions import db, migrate
from app.levels import LEVEL_INFO

_SUP_RE = re.compile(r"\^(\([^()]{1,30}\)|-?\d+(?:/\d+)?|[a-zA-Z](?![a-zA-Z]))")
_SQRT_RE = re.compile(r"sqrt\(")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def _math_html(html):
    html = _SUP_RE.sub(lambda m: "<sup>" + m.group(1).strip("()") + "</sup>"
                       if m.group(1).startswith("(") else "<sup>" + m.group(1) + "</sup>", html)
    return _SQRT_RE.sub("√(", html)


def mathfmt(text):
    """Plain question text -> HTML: x^2 as superscript, sqrt( as √(, and
    **...** as bold (Critical Reasoning boldface questions)."""
    if text is None:
        return ""
    html = _BOLD_RE.sub(r"<strong>\1</strong>", str(escape(text)))
    return Markup(_math_html(html))


_LIST_LINE_RE = re.compile(r"^(?:I{1,3}|IV|V)\.\s|^\(\d\)\s")


def reflow(text):
    """Text wrapped in the YAML -> real paragraphs: single newlines are joined,
    blank lines become paragraph breaks, and list lines ("I. ...", "(1) ...")
    keep their own line."""
    if not text:
        return ""
    html = []
    for block in re.split(r"\n\s*\n", str(text).strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        parts = [str(mathfmt(lines[0]))]
        for line in lines[1:]:
            parts.append(("<br>" if _LIST_LINE_RE.match(line) else " ") + str(mathfmt(line)))
        html.append("<p>" + "".join(parts) + "</p>")
    return Markup("".join(html))


def render_markdown(text):
    if not text:
        return ""
    html = markdown_lib.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    return Markup(_math_html(html))


def mmss(seconds):
    if seconds is None:
        return "-"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)

    from app import models  # noqa: F401  (registers models on db.metadata)

    app.jinja_env.filters["mathfmt"] = mathfmt
    app.jinja_env.filters["md"] = render_markdown
    app.jinja_env.filters["reflow"] = reflow
    app.jinja_env.filters["mmss"] = mmss
    app.jinja_env.globals["LEVEL_INFO"] = LEVEL_INFO
    from app.services.grading import build_answer_groups

    app.jinja_env.globals["groups_for"] = build_answer_groups

    from app.routes.home import bp as home_bp
    from app.routes.content import bp as content_bp
    from app.routes.learn import bp as learn_bp
    from app.routes.study import bp as study_bp
    from app.routes.review import bp as review_bp
    from app.routes.questions import bp as questions_bp
    from app.routes.mock_exam import bp as mock_exam_bp
    from app.routes.progress import bp as progress_bp
    from app.routes.settings import bp as settings_bp
    from app.routes.reports import bp as reports_bp
    from app.routes.resources import bp as resources_bp

    for bp in (home_bp, content_bp, learn_bp, study_bp, review_bp, questions_bp, mock_exam_bp,
               progress_bp, settings_bp, reports_bp, resources_bp):
        app.register_blueprint(bp)

    @app.context_processor
    def inject_nav_counts():
        from app.services.srs import due_count

        try:
            return {"nav_due_reviews": due_count()}
        except Exception:  # tables not created yet (fresh DB before migrations)
            db.session.rollback()
            return {"nav_due_reviews": 0}

    if not app.config.get("DEMO_MODE"):
        from app.routes.admin_bp import init_admin

        init_admin(app)

    return app
