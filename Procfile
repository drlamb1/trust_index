web: uvicorn api.app:create_app --factory --host 0.0.0.0 --port $PORT
worker: celery -A scheduler.tasks worker --beat -l info -Q ingestion,analysis,alerts,delivery,simulation
