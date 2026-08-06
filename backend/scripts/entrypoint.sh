#!/bin/sh
set -eu
case "${1:-api}" in
 api) exec uvicorn job_collector.adapter.inbound.http.app:create_app --factory --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}" --workers "${API_WORKERS:-2}" ;;
 scheduler) exec python -m job_collector.main scheduler ;;
 migrate) exec alembic upgrade head ;;
 *) exec "$@" ;;
esac
