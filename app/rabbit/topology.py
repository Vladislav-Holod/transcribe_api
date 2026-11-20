from aio_pika.abc import AbstractChannel, AbstractQueue

from app.core.config import RabbitConfig


async def declare_task_queue(channel: AbstractChannel,settings: RabbitConfig,) -> AbstractQueue:
    return await channel.declare_queue(settings.queue_name,durable=True,)
