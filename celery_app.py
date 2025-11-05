"""
Celery Application Configuration for OBYRA
"""
import os
from celery import Celery


def make_celery(app_name=__name__):
    """Create and configure Celery app"""

    # Get Redis URL from environment
    broker_url = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/1')
    result_backend = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/2')

    celery_app = Celery(
        app_name,
        broker=broker_url,
        backend=result_backend,
        include=[]  # Add task modules here when you create them
    )

    # Celery configuration
    celery_app.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='America/Argentina/Buenos_Aires',
        enable_utc=True,
        task_track_started=True,
        task_time_limit=30 * 60,  # 30 minutes
        worker_prefetch_multiplier=4,
        worker_max_tasks_per_child=1000,
    )

    return celery_app


# Create Celery app instance
celery = make_celery('obyra')


# Example task - you can add more tasks here or in separate files
@celery.task(name='celery_app.test_task')
def test_task():
    """Test task to verify Celery is working"""
    return 'Celery is working!'


# Import tasks from other modules if they exist
try:
    from tasks import *  # noqa: F401, F403
except ImportError:
    pass  # No tasks module yet


if __name__ == '__main__':
    celery.start()
