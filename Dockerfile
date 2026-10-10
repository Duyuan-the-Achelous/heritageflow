FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HERITAGEFLOW_STORAGE=dynamodb

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM base AS runtime
RUN useradd --create-home appuser && mkdir -p /data && chown appuser:appuser /data
USER appuser

EXPOSE 8000
CMD ["uvicorn", "heritageflow.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS test
COPY tests ./tests
RUN pip install --no-cache-dir ".[dev]"
CMD ["python", "-m", "pytest", "-m", "integration", "-q"]

