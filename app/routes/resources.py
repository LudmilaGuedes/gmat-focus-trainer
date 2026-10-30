"""Static pages: GMAC's official prep material, and the exam/strategy guide.

The built-in bank is original content written in the official style. The
official material (practice exams, Official Guide) is the complement: it is
what calibrates the app's estimate (see /progress), and official questions
you own can be added to the bank yourself with `source: official`
(see sample_bank/README.md)."""

from flask import Blueprint, render_template

bp = Blueprint("resources", __name__, url_prefix="/resources")

OFFICIAL_RESOURCES = [
    {
        "name": "GMAT Official Starter Kit + Practice Exams 1 & 2 (grátis)",
        "url": "https://www.mba.com/exam-prep/gmat-official-starter-kit-practice-exams-1-and-2-free",
        "price": "Gratuito",
        "description": (
            "2 simulados adaptativos completos feitos pela própria GMAC (a banca do GMAT) + cerca de "
            "90 questões oficiais de amostra. Use o Exam 1 como diagnóstico no começo e o Exam 2 no meio "
            "da preparação — e registre as notas em Progresso para calibrar a estimativa do app."
        ),
    },
    {
        "name": "GMAT Official Practice Exams 3-6 (pagos)",
        "url": "https://www.mba.com/exam-prep",
        "price": "Pago",
        "description": "Os simulados oficiais mais fiéis que existem. Guarde para as últimas 4-6 semanas.",
    },
    {
        "name": "GMAT Official Guide (livro + banco online)",
        "url": "https://www.mba.com/exam-prep",
        "price": "Pago",
        "description": (
            "Centenas de questões oficiais com explicação, separadas por dificuldade. Se você tiver o "
            "Guide, pode cadastrar as questões dele aqui (source: official) para usar a revisão espaçada."
        ),
    },
    {
        "name": "Prep for the Exam (hub oficial da GMAC)",
        "url": "https://www.mba.com/exams/gmat-focus-edition/prep-for-the-exam",
        "price": "Gratuito / pago",
        "description": "Página oficial com todos os produtos de preparação da GMAC para o GMAT Focus Edition.",
    },
    {
        "name": "GMAT Club — fórum e banco de questões",
        "url": "https://gmatclub.com/forum/",
        "price": "Gratuito",
        "description": (
            "Maior comunidade de GMAT. Questões marcadas por dificuldade e discussões de cada uma. Útil "
            "quando uma explicação daqui não bastou."
        ),
    },
]


@bp.route("/")
def index():
    return render_template("resources.html", resources=OFFICIAL_RESOURCES)


@bp.route("/guia")
def guide():
    """How the GMAT Focus works + how to use this app to prepare."""
    return render_template("guide.html")
