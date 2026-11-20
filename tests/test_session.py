import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.schemas import TranscriberSettingsRead
from app.db import session as database
from app.db.models import Base, TranscriberSettings


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = (Path(temporary.name) / "test.db").as_posix()
        self.engine = database.create_database_engine(f"sqlite+aiosqlite:///{path}")
        self.addAsyncCleanup(self.engine.dispose)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def test_sqlite_configuration(self):
        async with self.engine.connect() as connection:
            self.assertEqual((await connection.execute(text("PRAGMA foreign_keys"))).scalar(), 1)
            self.assertEqual((await connection.execute(text("PRAGMA journal_mode"))).scalar(), "wal")

    async def test_dependency_commits_and_rolls_back(self):
        with patch.object(database, "SessionLocal", self.factory):
            dependency = database.get_async_db()
            session = await anext(dependency)
            settings = TranscriberSettings()
            session.add(settings)
            await session.flush()
            settings_id = settings.id
            with self.assertRaises(StopAsyncIteration):
                await anext(dependency)

            async with self.factory() as session:
                stored = await session.get(TranscriberSettings, settings_id)
                self.assertEqual(TranscriberSettingsRead.model_validate(stored).batch_size, 1)

            dependency = database.get_async_db()
            session = await anext(dependency)
            rejected = TranscriberSettings()
            session.add(rejected)
            await session.flush()
            rejected_id = rejected.id
            with self.assertRaisesRegex(RuntimeError, "request failed"):
                await dependency.athrow(RuntimeError("request failed"))

            async with self.factory() as session:
                self.assertIsNone(await session.get(TranscriberSettings, rejected_id))
