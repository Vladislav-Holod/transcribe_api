from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum as SqlEnum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TaskStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TranscriberSettings(Base):
    __tablename__ = "transcriber_settings"
    __table_args__ = (
        CheckConstraint("chunk_duration_seconds > 0", name="ck_chunk_duration"),
        CheckConstraint("chunk_overlap_seconds >= 0 AND chunk_overlap_seconds < chunk_duration_seconds",
            name="ck_chunk_overlap",),
        CheckConstraint("batch_size > 0", name="ck_batch_size"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chunk_duration_seconds: Mapped[float] = mapped_column(default=20)
    chunk_overlap_seconds: Mapped[float] = mapped_column(default=0)
    use_vad: Mapped[bool] = mapped_column(default=False)
    batch_size: Mapped[int] = mapped_column(default=1)
    word_timestamps: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Transcriber(Base):
    __tablename__ = "transcribers"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    engine: Mapped[str] = mapped_column(String(100))
    model_name: Mapped[str] = mapped_column(String(255))
    settings_id: Mapped[UUID] = mapped_column(
        ForeignKey("transcriber_settings.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ServiceSettings(Base):
    __tablename__ = "service_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_service_settings_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    default_transcriber_id: Mapped[UUID] = mapped_column(
        ForeignKey("transcribers.id", ondelete="RESTRICT"),
    )


class TranscriptionTask(Base):
    __tablename__ = "transcription_tasks"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_task_attempt_count"),
        Index("ix_task_status_created_at", "status", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    transcriber_id: Mapped[UUID] = mapped_column(ForeignKey("transcribers.id", ondelete="RESTRICT"), index=True)
    original_filename: Mapped[str] = mapped_column(Text)
    audio_path: Mapped[str] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        SqlEnum(TaskStatus, name="task_status", native_enum=False, create_constraint=True,
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=TaskStatus.QUEUED,
    )
    attempt_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Transcription_Text(Base):
    __tablename__ = "transcriptions_text"
    __table_args__ = (CheckConstraint("duration_seconds >= 0", name="ck_transcription_duration"),)

    task_id: Mapped[UUID] = mapped_column(ForeignKey("transcription_tasks.id", ondelete="CASCADE"), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[float]
