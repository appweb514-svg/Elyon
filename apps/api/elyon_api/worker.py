import os

from celery import Celery

celery = Celery("elyon", broker=os.environ.get("ELYON_REDIS_URL", "redis://localhost:6379/0"))
celery.conf.broker_connection_retry_on_startup = True
celery.conf.task_acks_late = True
celery.conf.task_default_queue = "elyon"


def process_media(media_id: str) -> dict:
    from sqlalchemy import select

    from elyon_api.config import Settings
    from elyon_api.db import build_session_factory
    from elyon_api.models import JobStatus, Media, MediaProcessingJob
    from elyon_api.services import media_processing
    from elyon_api.services.storage import build_storage

    settings = Settings()
    factory = build_session_factory(settings)
    with factory() as session:
        media = session.get(Media, media_id)
        if media is None:
            return {"status": "missing"}
        job = session.scalar(
            select(MediaProcessingJob).where(MediaProcessingJob.media_id == media_id)
        )
        if job is None:
            job = MediaProcessingJob(media_id=media_id, task_type="process")
            session.add(job)
            session.flush()
        job.status = JobStatus.RUNNING
        job.attempts += 1
        session.commit()
        try:
            media_processing.process_media(media, settings, build_storage(settings))
            job.status = JobStatus.DONE
            session.commit()
            return {"status": "done", "media_id": media_id}
        except Exception as exc:  # noqa: BLE001
            from elyon_api.models import MediaStatus

            media.status = MediaStatus.FAILED
            job.status = JobStatus.FAILED
            job.last_error = str(exc)
            session.commit()
            return {"status": "failed", "media_id": media_id, "error": str(exc)}


@celery.task(name="elyon.process_media", bind=True, max_retries=2)
def process_media_task(self, media_id: str) -> dict:
    result = process_media(media_id)
    if result["status"] == "failed":
        # Re-tente avec un backoff ; au-delà de max_retries Celery abandonne.
        raise self.retry(exc=RuntimeError(result["error"]), countdown=30)
    return result