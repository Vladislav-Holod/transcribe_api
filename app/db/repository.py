from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ServiceSettings,
    TaskStatus,
    Transcriber,
    TranscriberSettings,
    TranscriptionTask,
)


class TranscriberRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_default(self) -> tuple[Transcriber, TranscriberSettings] | None:
        query = (
            select(Transcriber, TranscriberSettings)
            .select_from(ServiceSettings)
            .join(Transcriber, Transcriber.id == ServiceSettings.default_transcriber_id)
            .join(TranscriberSettings, TranscriberSettings.id == Transcriber.settings_id)
            .where(ServiceSettings.id == 1)
        )
        row = (await self.session.execute(query)).one_or_none()
        if row is None:
            return None
        return row[0], row[1]

    async def get_by_id(self, transcriber_id: UUID) -> Transcriber | None:
        return await self.session.get(Transcriber, transcriber_id)


class TranscriptionTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self,*,transcriber_id: UUID,original_filename: str,audio_path: str,
    ) -> TranscriptionTask:
        task = TranscriptionTask(
            transcriber_id=transcriber_id,
            original_filename=original_filename,
            audio_path=audio_path,
            status=TaskStatus.QUEUED,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def get_by_id(self, task_id: UUID) -> TranscriptionTask | None:
        return await self.session.get(TranscriptionTask, task_id)

    async def claim(self, task_id: UUID) -> TranscriptionTask | None:
        result = await self.session.execute(
            update(TranscriptionTask)
            .where(TranscriptionTask.id == task_id,
                TranscriptionTask.status == TaskStatus.QUEUED,
            )
            .returning(TranscriptionTask.id)
            .values(
                status=TaskStatus.PROCESSING,
                started_at=func.now(),
                attempt_count=TranscriptionTask.attempt_count + 1,
            )
        )
        claimed_id = result.scalar_one_or_none()
        if claimed_id is None:
            return None

        await self.session.flush()
        return await self.session.get(
            TranscriptionTask,
            claimed_id,
            populate_existing=True,
        )
