from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.schemas import TranscriptionTaskCreate, TranscriptionTaskRead
from app.core.logging import logger
from app.db.models import Transcriber
from app.db.repository import TranscriptionTaskRepository
from app.db.session import SessionDep

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
    payload: TranscriptionTaskCreate,
    session: SessionDep,
) -> TranscriptionTaskRead:
    transcriber = await session.get(Transcriber, payload.transcriber_id)
    if transcriber is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcriber not found",
        )

    task = await TranscriptionTaskRepository(session).create(
        transcriber_id=payload.transcriber_id,
        original_filename=payload.original_filename,
        audio_path=payload.audio_path,
    )
    logger.info("Created transcription task {}", task.id)
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