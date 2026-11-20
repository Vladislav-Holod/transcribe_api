from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from app.api.schemas import TranscriptionCommand
from app.core.logging import logger
from app.services.pipilines import TranscriptionPipeline


class TaskConsumer:
    def __init__(self, pipeline: TranscriptionPipeline) -> None:
        self.pipeline = pipeline

    async def handle_message(self, message: AbstractIncomingMessage) -> None:
        try:
            command = TranscriptionCommand.model_validate_json(message.body)
        except (ValidationError, UnicodeDecodeError, ValueError):
            logger.warning("Некорректное сообщение RabbitMQ; сообщение отклонено")
            await message.reject(requeue=False)
            return

        try:
            await self.pipeline.run(command.task_id)
        except Exception:
            logger.exception("Ошибка обработки сообщения задачи {}", command.task_id)
            await message.nack(requeue=True)
            return

        await message.ack()
