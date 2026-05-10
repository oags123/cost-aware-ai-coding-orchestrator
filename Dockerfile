FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 orchestrator

WORKDIR /workspace
COPY pyproject.toml README.md ./
COPY coding_orchestrator ./coding_orchestrator
RUN pip install --no-cache-dir -e ".[dev]"
RUN mkdir -p /workspace/logs && chown -R orchestrator:orchestrator /workspace/logs

USER orchestrator
VOLUME ["/workspace/logs"]
CMD ["python", "-m", "coding_orchestrator.app", "report"]
