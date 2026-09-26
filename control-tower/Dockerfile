FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg[binary] wheels build cleanly on slim images.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY agent/ agent/
COPY api/ api/
COPY audit/ audit/
COPY configs/ configs/
COPY contracts/ contracts/
COPY dashboard/ dashboard/
COPY guardrails/ guardrails/
COPY investigation_assistant/ investigation_assistant/
COPY knowledge/ knowledge/
COPY scripts/ scripts/
COPY telemetry/ telemetry/
COPY data/ data/

RUN pip install --no-cache-dir -e ".[scale]"

EXPOSE 8000 8501

# docker-compose.yml overrides `command:` per service (api vs dashboard).
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
