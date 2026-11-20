import os
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from yaml import safe_load

from app.db.repository import TranscriberRepository



ROOT = Path(__file__).resolve().parents[2]

load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL") or (f"sqlite+aiosqlite:///{(ROOT / 'data' / 'transcribe.db').as_posix()}")




class ConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True,
                              extra="forbid",
                              from_attributes=True,
                              allow_inf_nan=False,)

class RabbitConfig(ConfigModel):
    queue_name: str = Field(
        default="transcription.tasks",
        min_length=1,
    )
    prefetch_count: int = Field(default=1, ge=1)

class LoggingConfig(ConfigModel):
    file: str = "logs/transcribe.log"
    level: str = "INFO"


class AppConfig(ConfigModel):
    title: str = "Transcription API"
    version: str = "0.1.0"
    debug: bool = False
    docs_enabled: bool = True
    allow_origins: list[str] = Field(default_factory=list)
    allow_credentials: bool = False
    allow_methods: list[str] = Field(default_factory=lambda: ["GET"])
    allow_headers: list[str] = Field(default_factory=lambda: ["Content-Type", "Authorization"])
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    rabbit: RabbitConfig = Field(default_factory=RabbitConfig)

class TranscriberSettingsConfig(ConfigModel):
    device: Literal["cpu", "cuda"]
    chunk_duration_seconds: float = Field(gt=0)
    chunk_overlap_seconds: float = Field(ge=0)
    use_vad: bool
    batch_size: int = Field(gt=0)
    word_timestamps: bool

    @model_validator(mode="after")
    def validate_overlap(self) -> Self:
        if self.chunk_overlap_seconds >= self.chunk_duration_seconds:
            raise ValueError("Перекрытие должно быть меньше длительности фрагмента")
        return self


class TranscriberConfig(ConfigModel):
    id: UUID
    is_active: bool = True
    engine: str
    model_name: str
    settings: TranscriberSettingsConfig


class Config:
    def __init__(self) -> None:
        path = ROOT / "config" / "app.yaml"
        with path.open(encoding="utf-8") as file:
            data = safe_load(file)
        if not isinstance(data, dict):
            raise ValueError(f"В {path} ожидается YAML-объект")
        self.app_config = AppConfig.model_validate(data)
        self.transcriber: TranscriberConfig | None = None

    async def load_transcriber(self, session: AsyncSession) -> None:
        result = await TranscriberRepository(session).get_default()
        if result is None:
            raise RuntimeError("Транскриптор по умолчанию не настроен")
        transcriber, settings = result
        if not transcriber.is_active:
            raise RuntimeError("Транскрибатор по умолчанию отключён")
        self.transcriber = TranscriberConfig(id=transcriber.id,
                                             engine=transcriber.engine,
                                             model_name=transcriber.model_name,
                                            settings=TranscriberSettingsConfig.model_validate(settings),)


config = Config()
