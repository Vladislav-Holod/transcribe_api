import unittest
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Base, Transcriber, TranscriberSettings
from app.db.session import create_database_engine, get_async_db
from app.main import app


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
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

        async def override_get_async_db():
            async with self.session_factory() as session:
                try:
                    yield session
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
            json={
                "transcriber_id": str(self.transcriber_id),
                "original_filename": "audio.wav",
                "audio_path": "data/audio/audio.wav",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()
        self.assertEqual(created["status"], "queued")
        self.assertEqual(created["original_filename"], "audio.wav")

        response = await self.client.get(f"/tasks/{created['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], created["id"])

    async def test_missing_task_or_transcriber_returns_404(self):
        response = await self.client.get(f"/tasks/{uuid4()}")
        self.assertEqual(response.status_code, 404)

        response = await self.client.post(
            "/tasks",
            json={
                "transcriber_id": str(uuid4()),
                "original_filename": "audio.wav",
                "audio_path": "data/audio/audio.wav",
            },
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()