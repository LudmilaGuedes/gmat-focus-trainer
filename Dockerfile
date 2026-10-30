# Demo pública (Render, plano gratuito — ver render.yaml): só o banco de exemplo, banco SQLite recriado a cada boot.
FROM python:3.12-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEMO_MODE=1 \
    GMAT_CONTENT_DIR=/home/user/app/sample_bank \
    PORT=10000

WORKDIR /home/user/app
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
COPY --chown=user . .

EXPOSE 10000
# Um único processo: o app é single-user e guarda o estado da atividade em sessão + SQLite.
# O Render define PORT em tempo de execução; o valor acima é só o padrão.
CMD ["sh", "-c", "python scripts/init_db.py && exec gunicorn --workers 1 --threads 4 --bind 0.0.0.0:${PORT} run:app"]
