import asyncio
from typing import BinaryIO
from uuid import UUID
from pathlib import Path

import gigaam
import math
import subprocess

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.models import TranscriptionTask
from app.db.repository import TranscriberRepository, TranscriptionTaskRepository
from app.rabbit.publisher import TaskPublisher
from app.services.storage import AudioStorage
from app.core.config import TranscriberConfig, TranscriberSettingsConfig


class TranscriberService:

    @classmethod
    async def from_database(cls, session: AsyncSession) -> "TranscriberService":
        result = await TranscriberRepository(session).get_default()
        if result is None:
            raise TranscriberNotFoundError("Транскрибатор по умолчанию не настроен")
        transcriber, settings = result
        if not transcriber.is_active:
            raise TranscriberInactiveError(transcriber.id)
        config = TranscriberConfig(id=transcriber.id,
                                   is_active=transcriber.is_active,
                                   engine=transcriber.engine,
                                   model_name=transcriber.model_name,
                                   settings=TranscriberSettingsConfig.model_validate(settings))
        return await asyncio.to_thread(cls, config)

    def __init__(self, config: TranscriberConfig):
        if not config.is_active:
            raise TranscriberInactiveError(config.id)
        self.transcriber_id = config.id
        self.settings = config.settings

        if not self.settings.use_vad:
            raise ValueError("Для GigaAM transcribe_longform нужно включить use_vad в настройках транскрибатора")

        if self.settings.chunk_overlap_seconds != 0:
            raise NotImplementedError("GigaAM transcribe_longform не поддерживает настройку перекрытия частей")

        # Сервис создаётся один раз при запуске worker.
        self.model = gigaam.load_model(model_name=config.model_name, device=self.settings.device, fp16_encoder=False)
        if not isinstance(self.model, gigaam.GigaAMASR):
            raise ValueError("Выбранная модель не предназначена для распознавания речи")

    def transcribe(self, audio_path: Path) -> tuple[str, float]:
        if not audio_path.is_file():
            raise FileNotFoundError(f"Аудиофайл не найден: {audio_path}")

        # ffprobe читает длительность, не изменяя и не перекодируя файл.
        probe = subprocess.run(["ffprobe",
                                "-v", "error",
                                "-show_entries",
                                "format=duration",
                                "-of",
                                "default=noprint_wrappers=1:nokey=1",
                                str(audio_path)],
                               capture_output=True,
                               text=True,
                               check=True,
                               timeout=30)

        duration = float(probe.stdout.strip())
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Не удалось определить длительность аудио")
        result = self.model.transcribe_longform(str(audio_path),
                                                fr_batch_size=self.settings.batch_size,
                                                word_timestamps=self.settings.word_timestamps,
                                                max_duration=self.settings.chunk_duration_seconds,
                                                min_duration=min(15.0, self.settings.chunk_duration_seconds),
                                                strict_limit_duration=self.settings.chunk_duration_seconds)
        return result.text, duration

class TranscriberNotFoundError(Exception):
    pass


class TranscriberInactiveError(Exception):
    pass


class TaskPublishError(Exception):
    def __init__(self, task_id: UUID):
        self.task_id = task_id
        super().__init__(f"Не удалось отправить задачу {task_id}")


class TaskCreationService:
    def __init__(self, session: AsyncSession, storage: AudioStorage, publisher: TaskPublisher):
        self.session = session
        self.storage = storage
        self.publisher = publisher

    async def create(self, original_filename: str, source: BinaryIO) -> TranscriptionTask:
        configured = await TranscriberRepository(self.session).get_default()
        if configured is None:
            raise TranscriberNotFoundError("Транскрибатор по умолчанию не настроен")
        transcriber, _ = configured
        transcriber_id = transcriber.id
        if not transcriber.is_active:
            raise TranscriberInactiveError(transcriber_id)
        file_saved = False

        try:
            task = await TranscriptionTaskRepository(self.session).create(transcriber_id=transcriber_id, original_filename=original_filename)
            file_uuid = task.file_uuid
            await asyncio.to_thread(self.storage.save, file_uuid, source)
            file_saved = True
            await self.session.commit()
        except Exception:
            if file_saved:
                try:
                    await asyncio.to_thread(self.storage.delete, file_uuid)
                except Exception:
                    logger.exception("Не удалось удалить файл {} после ошибки", file_uuid)

            await self.session.rollback()
            raise
        logger.info("Создана задача {} с файлом {}", task.id, file_uuid)

        try:
            await self.publisher.publish(task.id)
        except Exception as error:
            logger.exception("Задача {} сохранена, но публикация в RabbitMQ не подтверждена", task.id)
            raise TaskPublishError(task.id) from error

        logger.info("Задача {} отправлена в RabbitMQ", task.id)
        return task
