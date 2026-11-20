import asyncio
import os

from app.core.config import config
from app.core.logging import setup_logger
from app.db.repository import TranscriptionTaskRepository
from app.db.session import SessionLocal, engine
from app.rabbit.connection import RabbitConnection
from app.rabbit.consumer import TaskConsumer
from app.rabbit.publisher import TaskPublisher
from app.services.pipilines import TranscriptionPipeline
from app.services.storage import AudioStorage
from app.services.transcription import TranscriberService


async def run_worker() -> None:
    setup_logger(config.app_config.logging)
    rabbit_url = os.getenv("RABBITMQ_URL")
    if not rabbit_url:
        raise RuntimeError("В .env не задан RABBITMQ_URL")

    rabbit = RabbitConnection(rabbit_url, config.app_config.rabbit)
    try:
        await rabbit.connect()
        async with SessionLocal.begin() as session:
            transcriber = await TranscriberService.from_database(session)
            queued_task_ids = await TranscriptionTaskRepository(session).recover(
                transcriber.transcriber_id
            )

        publisher = TaskPublisher(rabbit)
        for task_id in queued_task_ids:
            await publisher.publish(task_id)

        channel = rabbit.channel
        if channel is None:
            raise RuntimeError("RabbitMQ channel не открыт")

        queue = await channel.get_queue(config.app_config.rabbit.queue_name)
        consumer = TaskConsumer(
            TranscriptionPipeline(transcriber, AudioStorage())
        )
        await queue.consume(consumer.handle_message, no_ack=False)
        await asyncio.Future()
    finally:
        try:
            await rabbit.close()
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_worker())