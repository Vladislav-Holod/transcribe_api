import unittest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from aio_pika import DeliveryMode

from app.api.schemas import TranscriptionCommand
from app.rabbit.publisher import TaskPublisher


class PublisherTests(unittest.IsolatedAsyncioTestCase):
    async def test_publishes_persistent_task_id_to_configured_queue(self):
        rabbit = Mock()
        rabbit.settings.queue_name = "transcription.tasks"
        rabbit.channel.is_closed = False
        publish = AsyncMock()
        rabbit.channel.default_exchange.publish = publish
        task_id = uuid4()

        await TaskPublisher(rabbit).publish(task_id)

        publish.assert_awaited_once()
        message = publish.call_args.args[0]
        self.assertEqual(TranscriptionCommand.model_validate_json(message.body).task_id, task_id)
        self.assertEqual(message.message_id, str(task_id))
        self.assertEqual(message.delivery_mode, DeliveryMode.PERSISTENT)
        self.assertEqual(publish.call_args.kwargs["routing_key"], "transcription.tasks")
        self.assertTrue(publish.call_args.kwargs["mandatory"])

    async def test_missing_or_closed_channel_is_rejected(self):
        rabbit = Mock()
        for channel in (None, Mock(is_closed=True)):
            rabbit.channel = channel
            with self.subTest(channel=channel), self.assertRaises(RuntimeError):
                await TaskPublisher(rabbit).publish(uuid4())
