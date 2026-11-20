# Transcribe Service

Асинхронный API-сервис — единый слой для работы с локальными движками распознавания речи. Клиент отправляет задачу через API, а сервис управляет её хранением и обработкой независимо от конкретной ASR-модели.

В текущей конфигурации планируется использовать **GigaAM** — семейство моделей распознавания речи от Sber, ориентированное в том числе на русский язык. Репозиторий проекта: [salute-developers/GigaAM](https://github.com/salute-developers/GigaAM). Сервис можно разворачивать отдельно от клиентского приложения — в том числе на другом сервере — и интегрировать с другими проектами через API. При этом распознаватель можно подключать или заменять, не меняя клиентский интерфейс.

Сервис построен на FastAPI, SQLAlchemy, SQLite и Alembic.

## Запуск

Нужны Python 3.14 и [uv](https://docs.astral.sh/uv/).

```powershell
uv sync
Copy-Item .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Перед запуском API в базе должен быть настроен транскрибатор по умолчанию.

## API

- `GET /health` — проверить, что API отвечает.
- `POST /tasks` — создать задачу (`transcriber_id`, `original_filename`, `audio_path`).
- `GET /tasks/{task_id}` — получить статус задачи.
- `/docs` — Swagger UI.

Проверки: `uv run python -m unittest`.
