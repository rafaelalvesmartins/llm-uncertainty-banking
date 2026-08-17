# REFERENCE artifact — Track D scale deployment (ENGINEERING_HARDENING_PLAN.md §D.5).
# ⚠️  The app is NOT stateless yet.  Running multiple replicas of this image
#     before completing SCALE_WIRING.md (D.1 adapters) will diverge in-process
#     state (_AUDIT deque, _CACHE, _RATE_LIMITER).  Use single-replica mode
#     (deploy.replicas: 1) until each adapter is wired and load-tested.
#
# Build context: bridge-ui/backend   (docker-compose.scale.yml sets context: ../backend)
# The repo root (two levels up) is NOT part of the build context.
# The lub package is therefore installed directly from PyPI or via a COPY + pip
# install of the local wheel — see the pip install step below.

FROM python:3.12-slim

LABEL org.opencontainers.image.title="bridge-ui backend (scale reference)" \
      org.opencontainers.image.description="FastAPI BFF for the Bridge demo — Track D reference image"

# ---- system deps ----
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- install the lub library (the flagship package) ----
# IMPORTANT: `lub` is only the IMPORT name; the DISTRIBUTION name is
# `llm-uncertainty-banking` (repo-root pyproject [project].name). Do NOT
# `pip install lub` — that name is not this project on PyPI and would pull an
# unrelated / squatted package, and the container's `import lub` would break.
#
# Provide the built wheel in the build context. From the repo root:
#   python -m build --wheel --outdir bridge-ui/backend/dist .
# (or `pip wheel . -w bridge-ui/backend/dist`), then build the image with this
# Dockerfile so the COPY below finds it:
COPY dist/llm_uncertainty_banking-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/llm_uncertainty_banking-*.whl

# ---- install bridge-ui backend dependencies ----
COPY requirements.txt requirements-scale.txt ./

# Install base deps + all Track-D scale deps (Redis, Postgres, Prometheus-client).
# requirements-scale.txt is safe to always install — the adapters are flag-gated
# at runtime via env vars (REDIS_URL, DATABASE_URL); unused drivers add ~10 MB
# and zero overhead at idle.
RUN pip install --no-cache-dir \
        -r requirements.txt \
        -r requirements-scale.txt

# ---- copy application code ----
COPY . .

# ---- runtime ----
EXPOSE 8000

# Multi-worker note: uvicorn's --workers N forks N OS processes.  Each process
# gets its OWN copy of every in-process global (_AUDIT, _CACHE, etc.).  This
# is correct ONLY after the stateless adapters in SCALE_WIRING.md are wired —
# until then keep --workers 1.  Use `--workers $(nproc)` once D.1 is done.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
