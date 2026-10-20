# Voice agent worker. Built from the repository root so it can be deployed with `lk agent create` (LiveKit Cloud)
# or run anywhere Docker runs. Only the packages the agent needs are installed (docs/decision.md D-073).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONPATH=/app/apps/agent-worker:/app/packages/core \
    HF_HOME=/app/.cache/huggingface

# libgomp is needed by the speech-timing model's runtime; nothing else is needed because audio libraries ship in wheels.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

# Run as a normal user, not root.
RUN useradd --create-home --uid 10001 agent && mkdir -p /app && chown agent /app
USER agent
WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY --chown=agent pyproject.toml uv.lock ./
RUN --mount=type=cache,id=uv,target=/home/agent/.cache/uv,uid=10001 uv sync --frozen --no-default-groups --no-install-project

COPY --chown=agent apps/agent-worker apps/agent-worker
COPY --chown=agent packages/core packages/core
COPY --chown=agent agents agents

# Download the turn-detection and voice-activity models now, so the first call does not wait for them.
RUN uv run --no-sync python -m agent_worker.agent download-files

# "start" is production mode. A named worker only receives rooms that ask for it (docs/decision.md D-060).
CMD ["uv", "run", "--no-sync", "python", "-m", "agent_worker.agent", "start"]
