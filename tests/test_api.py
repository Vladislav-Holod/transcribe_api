import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Base, ServiceSettings, Transcriber, TranscriberSettings, TranscriptionTask
from app.api.dependencies import get_audio_storage, get_task_publisher
from app.rabbit.publisher import TaskPublisher
from app.services.storage import AudioStorage
from app.db.session import create_database_engine, get_async_db
from app.main import app


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.storage = AudioStorage(Path(temporary.name))
        self.publisher = AsyncMock(spec=TaskPublisher)
        app.dependency_overrides[get_task_publisher] = lambda: self.publisher
        app.dependency_overrides[get_audio_storage] = lambda: self.storage
        self.engine = create_database_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(self.engine.dispose)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with self.session_factory.begin() as session:
            settings = TranscriberSettings()
            session.add(settings)
            await session.flush()
            transcriber = Transcriber(
                engine="gigaam",
                model_name="v3_e2e_rnnt",
                settings_id=settings.id,
            )
            session.add(transcriber)
            await session.flush()
            self.transcriber_id = transcriber.id
            session.add(ServiceSettings(default_transcriber_id=transcriber.id))
            alternative = Transcriber(
                engine="gigaam",
                model_name="v3_ctc",
                settings_id=settings.id,
            )
            session.add(alternative)
            await session.flush()
            self.alternative_transcriber_id = alternative.id

        async def override_get_async_db():
            async with self.session_factory() as session:
                try:
                    yield session
                    if session.in_transaction():
                        await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_async_db] = override_get_async_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_health_endpoints(self):
        for path in ("/health", "/helth"):
            response = await self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok"})

    async def test_create_and_get_task(self):
        response = await self.client.post(
            "/tasks",
            files={"file": ("audio.wav", b"audio content", "audio/wav")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()
        self.assertEqual(created["status"], "queued")
        self.assertEqual(created["original_filename"], "audio.wav")
        self.assertEqual(str(UUID(created["file_uuid"])), created["file_uuid"])
        self.assertNotIn("audio_path", created)
        self.publisher.publish.assert_awaited_once_with(UUID(created["id"]))
        self.assertEqual(
            self.storage.get_path(UUID(created["file_uuid"])).read_bytes(),
            b"audio content",
        )

        response = await self.client.get(f"/tasks/{created['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], created["id"])
        self.assertEqual(response.json()["file_uuid"], created["file_uuid"])

    async def test_missing_task_returns_404(self):
        response = await self.client.get(f"/tasks/{uuid4()}")
        self.assertEqual(response.status_code, 404)

    async def test_transcriber_is_not_selectable_by_client(self):
        response = await self.client.post(
            "/tasks",
            data={
                "transcriber_id": str(self.alternative_transcriber_id),
            },
            files={"file": ("audio.wav", b"audio content", "audio/wav")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["transcriber_id"], str(self.transcriber_id))

    async def test_missing_default_transcriber_returns_503(self):
        async with self.session_factory.begin() as session:
            await session.delete(await session.get(ServiceSettings, 1))

        response = await self.client.post(
            "/tasks",
            files={"file": ("audio.wav", b"audio content", "audio/wav")},
        )
        self.assertEqual(response.status_code, 503)
        await self.assert_no_tasks_or_files()

    async def test_inactive_transcriber_does_not_create_task_or_publish(self):
        async with self.session_factory.begin() as session:
            transcriber = await session.get(Transcriber, self.transcriber_id)
            transcriber.is_active = False
        response = await self.client.post("/tasks", data={"transcriber_id": str(self.transcriber_id)}, files={"file": ("audio.mp3", b"audio", "audio/mpeg")})
        self.assertEqual(response.status_code, 503, response.text)
        await self.assert_no_tasks_or_files()

    async def assert_no_tasks_or_files(self):
        self.publisher.publish.assert_not_awaited()
        self.assertEqual(list(self.storage.directory.iterdir()), [])
        async with self.session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(TranscriptionTask))
            self.assertEqual(count, 0)

    async def test_empty_or_missing_file_is_rejected(self):
        for files in ({"file": ("audio.wav", b"", "audio/wav")}, None):
            response = await self.client.post(
                "/tasks",
                files=files,
            )
            self.assertEqual(response.status_code, 422, response.text)
        await self.assert_no_tasks_or_files()

    async def test_publish_failure_keeps_task_and_audio(self):
        self.publisher.publish.side_effect = ConnectionError("broker unavailable")
        response = await self.client.post(
            "/tasks",
            files={"file": ("audio.wav", b"audio content", "audio/wav")},
        )
        self.assertEqual(response.status_code, 503, response.text)
        task_id = response.json()["detail"]["task_id"]
        self.publisher.publish.assert_awaited_once_with(UUID(task_id))
        response = await self.client.get(f"/tasks/{task_id}")
        self.assertEqual(response.status_code, 200)
        task = response.json()
        self.assertEqual(task["status"], "queued")
        self.assertEqual(
            self.storage.get_path(UUID(task["file_uuid"])).read_bytes(),
            b"audio content",
        )
        async with self.session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(TranscriptionTask))
            self.assertEqual(count, 1)

    async def test_missing_publisher_returns_503_without_creating_task(self):
        del app.dependency_overrides[get_task_publisher]
        with patch.object(app.state, "task_publisher", None, create=True):
            response = await self.client.post(
                "/tasks",
                files={"file": ("audio.wav", b"audio content", "audio/wav")},
            )
        self.assertEqual(response.status_code, 503)
        await self.assert_no_tasks_or_files()

    async def test_commit_failure_removes_file_and_rolls_back_task(self):
        with patch.object(AsyncSession, "commit", AsyncMock(side_effect=RuntimeError("commit failed"))):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                await self.client.post(
                    "/tasks",
                    files={"file": ("audio.wav", b"audio content", "audio/wav")},
                )
        await self.assert_no_tasks_or_files()

    async def test_storage_failure_rolls_back_task(self):
        with patch.object(self.storage, "save", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                await self.client.post(
                    "/tasks",
                    files={"file": ("audio.wav", b"audio content", "audio/wav")},
                )
        await self.assert_no_tasks_or_files()


if __name__ == "__main__":
    unittest.main()
