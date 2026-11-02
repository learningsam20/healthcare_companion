# One image for the API, worker, scheduler and MCP services. The compose command
# selects the entrypoint; the workspace install keeps local/prod parity.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CONCURRENT_DOWNLOADS=1 \
    UV_CONCURRENT_INSTALLS=1 \
    UV_HTTP_TIMEOUT=300 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/apps/api:/app/packages/py-common:/app/services/abdm-stub:/app/services/mcp-pii" \
    CONFIG_DIR="/app/config"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 sahyog

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY apps ./apps
COPY packages ./packages
COPY services ./services
COPY config ./config
COPY scripts ./scripts
COPY evals ./evals
COPY docker/keycloak ./docker/keycloak
# Pre-fetched manylinux aarch64 CPU wheels (no nvidia CUDA). See scripts/fetch_pii_wheels.sh.
COPY data/wheels ./data/wheels

# Skip lockfile gliner+torch (PyPI torch 2.15 linux pulls CUDA/nvidia/triton).
# Install CPU torch 2.5.1 + gliner (+wheelhouse deps) from data/wheels only.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --group eval \
         --no-install-package gliner --no-install-package torch \
    && uv pip uninstall -y torch torchvision torchaudio triton \
         nvidia-cublas-cu12 nvidia-cublas-cu13 nvidia-cudnn-cu12 nvidia-cudnn-cu13 \
         nvidia-cuda-runtime-cu12 nvidia-cuda-runtime-cu13 \
         cuda-bindings cuda-toolkit 2>/dev/null || true \
    && uv pip install --python /opt/venv/bin/python --no-index --find-links=/app/data/wheels \
         'torch==2.5.1' 'transformers==4.53.3' 'sentencepiece==0.2.0' \
         'safetensors==0.8.0' 'huggingface-hub==0.31.4' 'gliner==0.2.29' \
    && uv pip install --python /opt/venv/bin/python 'psycopg[binary]==3.3.6' \
    && /opt/venv/bin/python -m spacy download en_core_web_sm \
    && /opt/venv/bin/python -c "import gliner,presidio_analyzer,spacy,torch,en_core_web_sm; v=torch.__version__; assert 'cu' not in v.lower(), v; print('pii-deps-ok', v)" \
    && chown -R sahyog:sahyog /app /opt/venv \
    && rm -rf /app/data/wheels

USER sahyog
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "apps/api"]
