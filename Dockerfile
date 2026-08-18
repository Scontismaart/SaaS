# syntax=docker/dockerfile:1

# -- Stage 1: build dipendenze --------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# -- Stage 2: runtime -------------------------------------------------
FROM python:3.11-slim AS runtime

# Utente non-root: uid/gid fissi per compatibilita' con volume permissions
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -m -s /usr/sbin/nologin appuser

WORKDIR /app

# Solo librerie runtime (niente compiler nello stage finale)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=appuser:appuser --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --chown=appuser:appuser . .

# data/ resta scrivibile a runtime (chroma) ma non porta segreti
# nell'immagine: in docker-compose viene montata come volume esterno,
# questo mkdir e' solo fallback per run standalone.
RUN mkdir -p data/chroma /home/appuser/.local/share && \
    chown -R appuser:appuser /app /home/appuser/.local

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
