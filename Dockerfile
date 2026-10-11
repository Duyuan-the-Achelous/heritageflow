FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HERITAGEFLOW_STORAGE=dynamodb

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM base AS runtime
ARG ARMS_AGENT_VERSION=3.1.4
RUN pip install --no-cache-dir "aliyun-bootstrap==1.0.8" \
    && ARMS_REGION_ID=cn-beijing aliyun-bootstrap -a install -v "${ARMS_AGENT_VERSION}" \
    && useradd --create-home appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data
USER appuser

EXPOSE 8000
CMD ["aliyun-instrument", "gunicorn", "--workers", "1", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "heritageflow.main:app"]

FROM base AS test
COPY tests ./tests
RUN pip install --no-cache-dir ".[dev]"
CMD ["python", "-m", "pytest", "-m", "integration", "-q"]

