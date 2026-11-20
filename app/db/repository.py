from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ServiceSettings,
    TaskStatus,
    Transcriber,
    TranscriberSettings,
    TranscriptionTask,
    Transcription_Text
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

class TranscriptionTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self,*,transcriber_id: UUID,original_filename: str,
    ) -> TranscriptionTask:
        task = TranscriptionTask(
            transcriber_id=transcriber_id,
            original_filename=original_filename,
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
    async def complete(self, task_id: UUID, text: str, duration_seconds: float) -> None:
        task = await self.session.get(TranscriptionTask, task_id)
        if task is None or task.status != TaskStatus.PROCESSING:
            raise RuntimeError("Задача не находится в обработке")

        self.session.add(Transcription_Text(task_id=task_id, text=text, duration_seconds=duration_seconds))
        task.status = TaskStatus.COMPLETED
        task.error_message = None
        task.finished_at = func.now()
        await self.session.flush()

    async def fail(self, task_id: UUID, error_message: str) -> None:
        task = await self.session.get(TranscriptionTask, task_id)
        if task is None or task.status != TaskStatus.PROCESSING:
            raise RuntimeError("Задача не находится в обработке")

        task.status = TaskStatus.FAILED
        task.error_message = error_message
        task.finished_at = func.now()
        await self.session.flush()

    async def recover(self, transcriber_id: UUID) -> list[UUID]:
        # Вызывать при запуске единственного worker.
        await self.session.execute(
            update(TranscriptionTask)
            .where(TranscriptionTask.transcriber_id == transcriber_id, TranscriptionTask.status == TaskStatus.PROCESSING)
            .values(status=TaskStatus.QUEUED, started_at=None, finished_at=None, error_message=None)
        )
        query = select(TranscriptionTask.id).where(TranscriptionTask.transcriber_id == transcriber_id, TranscriptionTask.status == TaskStatus.QUEUED).order_by(TranscriptionTask.created_at)
        return list((await self.session.scalars(query)).all())