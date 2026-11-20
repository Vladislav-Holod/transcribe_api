from app.services.storage import AudioStorage
from fastapi import HTTPException, Request

from app.rabbit.publisher import TaskPublisher

def get_audio_storage() -> AudioStorage:
    return AudioStorage()

def get_task_publisher(request: Request) -> TaskPublisher:
    publisher = getattr(request.app.state, "task_publisher", None)

    if publisher is None:
        raise HTTPException(503, "RabbitMQ publisher не инициализирован")

    return publisher