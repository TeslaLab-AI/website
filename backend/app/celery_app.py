import os
from celery import Celery

# Redis broker URL (defaulting to localhost if not specified in env)
broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery_app = Celery(
    "teslalab_worker",
    broker=broker_url,
    backend=result_backend,
    include=["app.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Worker settings
    task_track_started=True,
    task_time_limit=300,        # Hard limit 300 seconds
    task_soft_time_limit=290,   # Soft limit
)
