# Document reader + test worker + hourly cleanup, in one small container with a health page (for Render's free plan,
# which wants a web address). Build context is the repository root.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONPATH=/app/apps/agent-worker:/app/apps/ingestion-worker:/app/packages/core:/app

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

RUN useradd --create-home --uid 10001 worker && mkdir -p /app && chown worker /app
USER worker
WORKDIR /app

COPY --chown=worker pyproject.toml uv.lock ./
# The agent's packages (the test worker imports the agent) plus the document readers.
RUN --mount=type=cache,id=uv,target=/home/worker/.cache/uv,uid=10001 uv sync --frozen --no-default-groups --group ingestion --no-install-project

COPY --chown=worker apps/agent-worker apps/agent-worker
COPY --chown=worker apps/ingestion-worker apps/ingestion-worker
COPY --chown=worker packages/core packages/core
COPY --chown=worker evals evals
COPY --chown=worker agents agents
COPY --chown=worker deploy/run_background.py deploy/run_background.py

# Render sets PORT. The health page answers there; the workers run alongside it.
CMD ["uv", "run", "--no-sync", "python", "deploy/run_background.py"]
