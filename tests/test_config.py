import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Config
from app.db.models import Base, ServiceSettings, Transcriber, TranscriberSettings
from app.db.session import create_database_engine


class ConfigTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_database_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(self.engine.dispose)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def test_default_is_loaded_as_snapshot_and_can_be_reloaded(self):
        config = Config()
        async with self.factory.begin() as session:
            settings = TranscriberSettings()
            session.add(settings)
            await session.flush()
            transcriber = Transcriber(
                engine="gigaam", model_name="v3_e2e_rnnt", settings_id=settings.id,
            )
            session.add(transcriber)
            await session.flush()
            session.add(ServiceSettings(default_transcriber_id=transcriber.id))
        async with self.factory() as session:
            await config.load_transcriber(session)
            with patch.object(session, "execute", new_callable=AsyncMock) as execute:
                self.assertEqual(config.transcriber.engine, "gigaam")
                self.assertEqual(config.transcriber.settings.chunk_duration_seconds, 20)
                self.assertEqual(config.transcriber.settings.device, "cpu")
                execute.assert_not_called()
        async with self.factory.begin() as session:
            settings = TranscriberSettings(chunk_duration_seconds=15, device="cuda")
            session.add(settings)
            await session.flush()
            replacement = Transcriber(engine="gigaam", model_name="v3_ctc", settings_id=settings.id)
            session.add(replacement)
            await session.flush()
            stored = await session.get(ServiceSettings, 1)
            stored.default_transcriber_id = replacement.id
        self.assertEqual(config.transcriber.model_name, "v3_e2e_rnnt")
        async with self.factory() as session:
            await config.load_transcriber(session)
        self.assertEqual(config.transcriber.model_name, "v3_ctc")
        self.assertEqual(config.transcriber.settings.chunk_duration_seconds, 15)
        self.assertEqual(config.transcriber.settings.device, "cuda")

    async def test_missing_default_fails_clearly(self):
        config = Config()
        async with self.factory() as session:
            with self.assertRaisesRegex(RuntimeError, "не настроен"):
                await config.load_transcriber(session)
        self.assertIsNone(config.transcriber)

    async def test_lifespan_loads_default(self):
        from app import main

        async with self.factory.begin() as session:
            settings = TranscriberSettings()
            session.add(settings)
            await session.flush()
            transcriber = Transcriber(engine="gigaam", model_name="v3_e2e_rnnt", settings_id=settings.id)
            session.add(transcriber)
            await session.flush()
            session.add(ServiceSettings(default_transcriber_id=transcriber.id))
        config = Config()
        with patch.object(main, "SessionLocal", self.factory), patch.object(main, "engine", self.engine), patch.object(main, "config", config), patch.object(main, "RabbitConnection", autospec=True) as rabbit_class, patch.dict(os.environ, {"RABBITMQ_URL": "amqp://test:test@localhost/"}):
            async with main.lifespan(main.app):
                self.assertEqual(config.transcriber.id, transcriber.id)
                rabbit_class.return_value.connect.assert_awaited_once()
                self.assertIs(main.app.state.task_publisher.rabbit, rabbit_class.return_value)
            rabbit_class.return_value.close.assert_awaited_once()


class YAMLConfigTests(unittest.TestCase):
    def test_flat_yaml_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            path = root / "config" / "app.yaml"
            path.write_text("title: Test API\ndocs_enabled: false\n", encoding="utf-8")
            with patch("app.core.config.ROOT", root):
                config = Config()
                self.assertEqual(config.app_config.title, "Test API")
                self.assertFalse(config.app_config.docs_enabled)
                path.write_text("unknown_setting: true\n", encoding="utf-8")
                with self.assertRaises(ValidationError):
                    Config()
