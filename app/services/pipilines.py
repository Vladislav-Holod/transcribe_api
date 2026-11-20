import asyncio
from uuid import UUID

from app.core.logging import logger
from app.db.models import TaskStatus
from app.db.repository import TranscriptionTaskRepository
from app.db.session import SessionLocal
from app.services.storage import AudioStorage
from app.services.transcription import TranscriberService


class TranscriptionPipeline:
    def __init__(self, transcriber: TranscriberService, storage: AudioStorage):
        self.transcriber = transcriber
        self.storage = storage

    async def _delete_audio(self, task_id: UUID, file_uuid: UUID) -> None:
        try:
            await asyncio.to_thread(self.storage.delete, file_uuid)
        except OSError:
            logger.exception("Не удалось удалить файл {} задачи {}", file_uuid, task_id)

    async def run(self, task_id: UUID) -> None:
        async with SessionLocal.begin() as session:
            repository = TranscriptionTaskRepository(session)
            task = await repository.get_by_id(task_id)

            if task is None:
                logger.warning("Получено сообщение для отсутствующей задачи {}", task_id)
                return

            if task.status == TaskStatus.FAILED:
                return

            file_uuid = task.file_uuid
            completed = task.status == TaskStatus.COMPLETED

            if not completed:
                task = await repository.claim(task_id)
                if task is None:
                    raise RuntimeError(f"Задача {task_id} уже обрабатывается")

                transcriber_id = task.transcriber_id

        # Повторная доставка завершённой задачи не запускает модель снова.
        if completed:
            await self._delete_audio(task_id, file_uuid)
            return

        try:
            if transcriber_id != self.transcriber.transcriber_id:
                raise ValueError("Задача назначена другому транскрибатору; этот worker обслуживает текущий транскрибатор по умолчанию")

            audio_path = self.storage.get_path(file_uuid)
            text, duration = await asyncio.to_thread(self.transcriber.transcribe, audio_path)
        except Exception as error:
            logger.exception("Ошибка распознавания задачи {}", task_id)
            async with SessionLocal.begin() as session:
                await TranscriptionTaskRepository(session).fail(task_id, str(error))
            return

        # Ошибка сохранения передаётся consumer: сообщение нельзя подтверждать.
        async with SessionLocal.begin() as session:
            await TranscriptionTaskRepository(session).complete(task_id, text, duration)

        await self._delete_audio(task_id, file_uuid)
        logger.info("Задача {} завершена", task_id)