#!/bin/bash
set -e

case "${PROCESS_TYPE}" in
  worker)
    echo "Starting Celery worker + beat..."
    exec celery -A scheduler.tasks worker \
      --beat --loglevel=info --concurrency=4 \
      -Q ingestion,analysis,alerts,delivery,simulation
    ;;
  simulation-worker)
    echo "Starting simulation Celery worker..."
    exec celery -A scheduler.tasks worker \
      --loglevel=info --concurrency=2 \
      -Q simulation
    ;;
  beat)
    echo "Starting Celery beat (standalone)..."
    exec celery -A scheduler.tasks beat --loglevel=info
    ;;
  *)
    echo "Starting uvicorn web server on port ${PORT:-8050}..."
    exec uvicorn api.app:create_app --factory \
      --host 0.0.0.0 --port "${PORT:-8050}"
    ;;
esac
