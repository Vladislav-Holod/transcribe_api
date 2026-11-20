from uuid import UUID

from aio_pika import DeliveryMode, Message

from app.api.schemas import TranscriptionCommand
from app.rabbit.connection import RabbitConnection


class TaskPublisher:
    def __init__(self, rabbit: RabbitConnection):
        self.rabbit = rabbit

    async def publish(self, task_id: UUID) -> None:
        channel = self.rabbit.channel

        if channel is None or channel.is_closed:
            raise RuntimeError("Канал RabbitMQ не открыт")

        command = TranscriptionCommand(task_id=task_id)

        await channel.default_exchange.publish(
            Message(
                body=command.model_dump_json().encode("utf-8"),
                content_type="application/json",
                message_id=str(task_id),
                delivery_mode=DeliveryMode.PERSISTENT,
            ),
            routing_key=self.rabbit.settings.queue_name,
            mandatory=True,
            timeout=10,
        )