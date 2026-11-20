from contextlib import asynccontextmanager
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import config
from app.core.logging import setup_logger
from app.db.session import SessionLocal, engine

from app.rabbit.connection import RabbitConnection
from app.rabbit.publisher import TaskPublisher

setup_logger(config.app_config.logging)


@asynccontextmanager
async def lifespan(app: FastAPI):
    rabbit_url = os.getenv("RABBITMQ_URL")
    if not rabbit_url:
        raise RuntimeError("В .env не задан RABBITMQ_URL")

    rabbit = RabbitConnection(url=rabbit_url,settings=config.app_config.rabbit,)
    try:
        async with SessionLocal() as session:
            await config.load_transcriber(session)

        await rabbit.connect()
        app.state.task_publisher = TaskPublisher(rabbit)

        yield
    finally:
        try:
            await rabbit.close()
        finally:
            await engine.dispose()


settings = config.app_config

app = FastAPI(
    title=settings.title,
    version=settings.version,
    debug=settings.debug,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
    lifespan=lifespan,
)

app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_credentials=settings.allow_credentials,
    allow_methods=settings.allow_methods,
    allow_headers=settings.allow_headers,
)
