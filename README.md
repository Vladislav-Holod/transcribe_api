# Transcribe Service

Асинхронный API-сервис — единый слой для работы с локальными движками распознавания речи. Клиент отправляет задачу через API, а сервис управляет её хранением и обработкой независимо от конкретной ASR-модели.

В текущей конфигурации планируется использовать **GigaAM** — семейство моделей распознавания речи от Sber, ориентированное в том числе на русский язык. Репозиторий проекта: [salute-developers/GigaAM](https://github.com/salute-developers/GigaAM). Сервис можно разворачивать отдельно от клиентского приложения — в том числе на другом сервере — и интегрировать с другими проектами через API. При этом распознаватель можно подключать или заменять, не меняя клиентский интерфейс.

Сервис построен на FastAPI, SQLAlchemy, SQLite и Alembic.

## Запуск

Нужны Python 3.12 и [uv](https://docs.astral.sh/uv/).

```powershell
uv sync
Copy-Item .env.example .env
uv run alembic upgrade head
```

После настройки default-транскрибатора запустить worker и API в отдельных терминалах:

```powershell
uv run python -m app.worker
```

```powershell
uv run uvicorn app.main:app --reload
```

Перед запуском API в базе должен быть настроен транскрибатор по умолчанию.

## API

- `GET /health` — проверить, что API отвечает.
- `POST /tasks` — создать задачу: `multipart/form-data` с полем `file`. Используется default-транскрибатор, настроенный в БД.
- `GET /tasks/{task_id}` — получить статус задачи.
- `/docs` — Swagger UI.

Проверки: `uv run python -m unittest`.

## Проверка загрузки аудио

Применить миграции и запустить API:

```powershell
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Если default-транскрибатор ещё не настроен, создать его:

```powershell
@'
import asyncio
from app.db.models import ServiceSettings, Transcriber, TranscriberSettings
from app.db.session import SessionLocal, engine

async def main():
    try:
        async with SessionLocal.begin() as session:
            settings = TranscriberSettings()
            session.add(settings)
            await session.flush()
            transcriber = Transcriber(
                engine="gigaam", model_name="v3_e2e_rnnt", settings_id=settings.id,
            )
            session.add(transcriber)
            await session.flush()
            service_settings = await session.get(ServiceSettings, 1)
            if service_settings is None:
                session.add(ServiceSettings(default_transcriber_id=transcriber.id))
            else:
                service_settings.default_transcriber_id = transcriber.id
        print(f"Default transcriber configured: {transcriber.id}")
    finally:
        await engine.dispose()

asyncio.run(main())
'@ | uv run python -
```

Этот скрипт создаёт запись транскрибатора для проверки API; модель распознавания он не устанавливает.

После настройки default-транскрибатора перезапустить worker, затем открыть http://127.0.0.1:8000/docs и загрузить аудиофайл через `POST /tasks`. Либо отправить из PowerShell:

```powershell
curl.exe -X POST http://127.0.0.1:8000/tasks -F "file=@C:/audio/test.wav"
```

Ожидается `201`, статус `queued` и `file_uuid`. Файл `data/audio/{file_uuid}` должен совпадать с загруженным. `GET /tasks/{id}` возвращает задачу. Пустой файл возвращает `422`; если default-транскрибатор не настроен — `503`.

Worker читает задачи из RabbitMQ, передаёт аудио в GigaAM, сохраняет результат и удаляет аудиофайл после обработки. При старте worker возвращает незавершённые задачи default-транскрибатора в очередь. Запускайте один worker-процесс.

При создании задачи API публикует её ID в RabbitMQ после сохранения файла и фиксации БД. В `.env` требуется `RABBITMQ_URL`; при запуске создаётся очередь `transcription.tasks`.

Если отправка в RabbitMQ не подтверждена, API возвращает `503` и `detail.task_id`. Задача и аудиофайл остаются сохранёнными; статус можно проверить через `GET /tasks/{id}`. Повторно загружать файл не нужно. Автоматическая повторная публикация пока не реализована.

## Распознавание длинных записей

`TranscriberService.from_database(session)` загружает транскрибатор, выбранный в `service_settings.default_transcriber_id`, и проверяет `is_active`. Модель и устройство берутся из его настроек БД. Создавайте сервис один раз при запуске worker.

Распознавание использует публичный `GigaAM.transcribe_longform()`: VAD, нарезка и батчи выполняются библиотекой. Нужны зависимости `gigaam[longform,torch]` (`uv sync --dev`), FFmpeg/ffprobe в PATH и `use_vad=True` в настройках выбранного транскрибатора. Перекрытие частей этим методом не поддерживается; `chunk_overlap_seconds` должно быть 0. Размер батча передаётся из `batch_size`.

Для первой загрузки VAD-модели примите условия доступа https://huggingface.co/pyannote/segmentation-3.0 и задайте `HF_TOKEN` с правом чтения в локальном `.env`. Секрет не добавляйте в Git. Если модель уже закэширована, токен для её загрузки не требуется. Длительность исходной записи читается через ffprobe; сервис не создаёт WAV-файлов и не переписывает исходный MP3. Внутреннюю подготовку аудио выполняет GigaAM.
