from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import TaskStatus


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid", allow_inf_nan=False)


class TranscriberSettingsCreate(Schema):
    chunk_duration_seconds: float = Field(default=20, gt=0)
    chunk_overlap_seconds: float = Field(default=0, ge=0)
    use_vad: bool = False
    batch_size: int = Field(default=1, gt=0)
    word_timestamps: bool = False

    @model_validator(mode="after")
    def validate_overlap(self) -> Self:
        if self.chunk_overlap_seconds >= self.chunk_duration_seconds:
            raise ValueError("chunk_overlap_seconds must be less than chunk_duration_seconds")
        return self


class TranscriberSettingsRead(TranscriberSettingsCreate):
    id: UUID
    created_at: datetime


class TranscriberCreate(Schema):
    engine: str = Field(min_length=1, max_length=100, pattern=r"\S")
    model_name: str = Field(min_length=1, max_length=255, pattern=r"\S")
    settings_id: UUID


class TranscriberRead(TranscriberCreate):
    id: UUID
    created_at: datetime


class TranscriptionTaskCreate(Schema):
    transcriber_id: UUID
    original_filename: str = Field(min_length=1, pattern=r"\S")
    audio_path: str = Field(min_length=1, pattern=r"\S")


class TranscriptionTaskRead(TranscriptionTaskCreate):
    id: UUID
    status: TaskStatus
    attempt_count: int = Field(ge=0)
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TranscriptionCreate(Schema):
    task_id: UUID
    text: str
    duration_seconds: float = Field(ge=0)


class TranscriptionRead(TranscriptionCreate):
    pass

