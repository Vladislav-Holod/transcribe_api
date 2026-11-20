import aio_pika
from aio_pika.abc import AbstractRobustChannel, AbstractRobustConnection

from app.core.config import RabbitConfig
from app.rabbit.topology import declare_task_queue


class RabbitConnection:
    def __init__(self, url: str, settings: RabbitConfig):
        self._url = url
        self.settings = settings
        self.connection: AbstractRobustConnection | None = None
        self.channel: AbstractRobustChannel | None = None

    async def connect(self) -> None:
        try:
            self.connection = await aio_pika.connect_robust(
                self._url,
                timeout=10,
            )
            self.channel = await self.connection.channel(
                publisher_confirms=True,
                on_return_raises=True,
            )
            await self.channel.set_qos(
                prefetch_count=self.settings.prefetch_count,
            )
            await declare_task_queue(self.channel, self.settings)
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()

        self.channel = None
        self.connection = None