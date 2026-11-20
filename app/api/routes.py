from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.schemas import TranscriptionTaskRead
from app.api.dependencies import get_audio_storage, get_task_publisher
from app.db.repository import TranscriptionTaskRepository
from app.db.session import SessionDep
from app.services.storage import AudioStorage
from app.rabbit.publisher import TaskPublisher
from app.services.transcription import TaskCreationService, TaskPublishError, TranscriberInactiveError, TranscriberNotFoundError

router = APIRouter()


@router.get("/health", tags=["health"])
@router.get("/helth", tags=["health"], include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/tasks",
    response_model=TranscriptionTaskRead,
    status_code=status.HTTP_201_CREATED,
    tags=["tasks"],
)
async def create_task(
    session: SessionDep,
    storage: Annotated[AudioStorage, Depends(get_audio_storage)],
    publisher: Annotated[TaskPublisher, Depends(get_task_publisher)],
    file: Annotated[UploadFile, File()],
) -> TranscriptionTaskRead:
    if not file.filename or not file.filename.strip():
        raise HTTPException(422, "Не указано имя файла")
    if file.size == 0:
        raise HTTPException(422, "Аудиофайл пуст")

    try:
        task = await TaskCreationService(session, storage, publisher).create(
            original_filename=file.filename,
            source=file.file,
        )
    except TranscriberNotFoundError:
        raise HTTPException(503, "Транскрибатор по умолчанию не настроен") from None
    except TranscriberInactiveError:
        raise HTTPException(503, "Транскрибатор по умолчанию отключён") from None
    except TaskPublishError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Задача и файл сохранены, но отправка в очередь не подтверждена. Не загружайте файл повторно.",
                "task_id": str(error.task_id),
            },
        ) from error
    return TranscriptionTaskRead.model_validate(task)


@router.get(
    "/tasks/{task_id}",
    response_model=TranscriptionTaskRead,
    tags=["tasks"],
)
async def get_task(
    task_id: UUID,
    session: SessionDep,
) -> TranscriptionTaskRead:
    task = await TranscriptionTaskRepository(session).get_by_id(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    return TranscriptionTaskRead.model_validate(task)
