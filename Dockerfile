FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

# Cache dependencies independently of application source; pyproject.toml is the source of truth.
# Persist pip downloads across builds without including the cache in the runtime image.
COPY pyproject.toml ./
RUN --mount=type=cache,id=hkhub-server-pip,target=/root/.cache/pip,sharing=locked \
    python -c 'import subprocess, sys, tomllib; \
    config = tomllib.load(open("pyproject.toml", "rb")); \
    pip = [sys.executable, "-m", "pip", "install"]; \
    subprocess.check_call(pip + config["build-system"]["requires"]); \
    subprocess.check_call(pip + ["--ignore-installed", "--prefix=/install"] + config["project"]["dependencies"])'

# Build only the project wheel after source changes; do not download dependencies again.
COPY app ./app
RUN python -m pip install --no-cache-dir --no-deps --no-build-isolation --prefix=/install .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    DEBUG=false

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser
COPY --from=builder /install /usr/local
COPY app ./app
COPY db/migrations ./db/migrations

# Source archives may have owner-only modes from the deployment umask (077).
# Keep files root-owned while allowing appuser to read code/dependencies and traverse directories.
RUN chmod -R a+rX /app /usr/local

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:8000' + os.environ.get('API_PREFIX', '/api') + '/health', timeout=3)"

# Database credentials are provided at runtime. Apply migrations as a separate release step.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
