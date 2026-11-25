"""Broker construction is explicit and belongs to process startup."""

from celery import Celery

from backend.app.infrastructure.settings import Settings


def create_celery(settings: Settings) -> Celery:
    application = Celery(
        "voxriva", broker=settings.redis_url or "redis://localhost:6379/0"
    )
    application.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_ignore_result=True,
        task_default_queue="email",
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_send_task_events=True,
        task_send_sent_event=True,
        task_track_started=True,
        broker_connection_timeout=3,
        broker_connection_retry_on_startup=True,
        broker_transport_options={
            "visibility_timeout": 300,
            "socket_timeout": 3,
            "socket_connect_timeout": 3,
        },
        task_soft_time_limit=110,
        task_time_limit=120,
    )
    return application
