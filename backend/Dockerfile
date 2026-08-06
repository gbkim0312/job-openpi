FROM python:3.13-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --upgrade pip && /opt/venv/bin/pip install --no-cache-dir .
FROM python:3.13-slim
ENV PATH="/opt/venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY profiles ./profiles
COPY scripts ./scripts
RUN chmod +x scripts/entrypoint.sh
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["api"]
