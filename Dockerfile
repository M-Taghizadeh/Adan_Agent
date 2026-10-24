FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

RUN useradd --create-home --uid 1000 appuser

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser scripts ./scripts
COPY --chown=appuser:appuser ui ./ui
COPY --chown=appuser:appuser data/documents ./data/documents

RUN mkdir -p data/db data/faiss_index .cache/huggingface \
    && sed -i 's/\r$//' scripts/*.sh \
    && chmod +x scripts/*.sh \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

CMD ["sh", "scripts/entrypoint.sh"]