# Demo pública (Hugging Face Spaces, SDK "docker"): só o banco de exemplo, banco SQLite recriado a cada boot.
FROM python:3.12-slim

# Hugging Face Spaces roda o contêiner com o usuário de UID 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEMO_MODE=1 \
    GMAT_CONTENT_DIR=/home/user/app/sample_bank \
    PORT=7860

WORKDIR /home/user/app
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
COPY --chown=user . .

EXPOSE 7860
# Um único processo: o app é single-user e guarda o estado da atividade em sessão + SQLite.
CMD ["sh", "-c", "python scripts/init_db.py && exec gunicorn --workers 1 --threads 4 --bind 0.0.0.0:${PORT} run:app"]
