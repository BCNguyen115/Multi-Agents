# syntax=docker/dockerfile:1.7
# Backend image (FastAPI gateway + PEV orchestrator + agents).
#   docker build -t agent-backend .
#   docker build --build-arg INSTALL_BROWSER=false -t agent-backend:slim .   # skip Chromium (~400 MB): disables web crawling
ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------------------
# Stage 1 — builder: compile/install Python deps into an isolated venv
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Dependency layer is cached until requirements.txt / requirements.lock change.
# requirements.lock pins every (transitive) version so two builds of the same commit are the same image.
COPY requirements.txt requirements.lock ./

# torch is pulled in only by sentence-transformers (an optional mem0 extra that this project never imports: embeddings go
# through the API). The default PyPI wheel drags in ~5 GB of CUDA libraries (nvidia-*, triton); installing the CPU build
# first makes pip see torch as satisfied (2.14.0+cpu matches the lock's ==2.14.0) and skip all of them.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=120 --retries 5 "torch==$(grep -E '^torch==' requirements.lock | cut -d= -f3)" \
        --index-url https://download.pytorch.org/whl/cpu

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=120 --retries 5 -r requirements.txt -c requirements.lock

# spaCy model required by mem0ai NLP extras (PyPI wheel fallback if the CDN download fails)
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m spacy download en_core_web_sm \
    || pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim image, non-root user, no compilers
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG INSTALL_BROWSER=true

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:${PATH}" \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home app

COPY --from=builder /opt/venv /opt/venv

# OCR for scanned PDFs (src/ingestion/ocr.py): the tesseract program with Vietnamese and English language data
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Chromium + system libs for Crawl4AI / Playwright (installed as root, readable by `app`)
RUN if [ "${INSTALL_BROWSER}" = "true" ]; then \
        playwright install --with-deps chromium \
        && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app
COPY --chown=app:app src ./src
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app scripts/run_ingestion.py scripts/run_offline_eval.py scripts/migrate.py ./scripts/

USER app
EXPOSE 8000

# stdlib probe: no curl needed in the image
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "src.gateway.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-keep-alive", "300", "--limit-concurrency", "100"]
