import unittest
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Base, TaskStatus, Transcriber, TranscriberSettings
from app.db.repository import TranscriptionTaskRepository
from app.db.session import create_database_engine


class TranscriptionTaskRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_database_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(self.engine.dispose)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with self.factory.begin() as session:
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

    async def test_create_get_and_claim_task_once(self):
        async with self.factory.begin() as session:
            repository = TranscriptionTaskRepository(session)
            task = await repository.create(
                transcriber_id=self.transcriber_id,
                original_filename="audio.wav",
            )
            task_id = task.id
            file_uuid = task.file_uuid
            self.assertEqual(task.status, TaskStatus.QUEUED)
            self.assertEqual(task.attempt_count, 0)

        async with self.factory() as session:
            repository = TranscriptionTaskRepository(session)
            stored = await repository.get_by_id(task_id)
            if stored is None:
                self.fail("Created task was not found")
            self.assertEqual(stored.original_filename, "audio.wav")
            self.assertEqual(stored.file_uuid, file_uuid)

            claimed = await repository.claim(task_id)
            if claimed is None:
                self.fail("Queued task was not claimed")
            self.assertEqual(claimed.status, TaskStatus.PROCESSING)
            self.assertEqual(claimed.attempt_count, 1)
            self.assertIsNotNone(claimed.started_at)
            self.assertIsNone(await repository.claim(task_id))

    async def test_get_and_claim_return_none_for_unknown_id(self):
        async with self.factory() as session:
            repository = TranscriptionTaskRepository(session)
            unknown_id = uuid4()
            self.assertIsNone(await repository.get_by_id(unknown_id))
            self.assertIsNone(await repository.claim(unknown_id))

    async def test_recover_requeues_interrupted_tasks_for_default_transcriber(self):
        async with self.factory.begin() as session:
            repository = TranscriptionTaskRepository(session)
            task = await repository.create(
                transcriber_id=self.transcriber_id,
                original_filename="interrupted.wav",
            )
            task_id = task.id

        async with self.factory.begin() as session:
            claimed = await TranscriptionTaskRepository(session).claim(task_id)
            self.assertIsNotNone(claimed)

        async with self.factory.begin() as session:
            recovered_ids = await TranscriptionTaskRepository(session).recover(
                self.transcriber_id
            )
            self.assertEqual(recovered_ids, [task_id])

        async with self.factory() as session:
            recovered = await TranscriptionTaskRepository(session).get_by_id(task_id)
            self.assertEqual(recovered.status, TaskStatus.QUEUED)
            self.assertEqual(recovered.attempt_count, 1)
            self.assertIsNone(recovered.started_at)


if __name__ == "__main__":
    unittest.main()
