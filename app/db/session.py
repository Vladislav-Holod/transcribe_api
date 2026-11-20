"""Асинхронные сессии и движок sqlite"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import DATABASE_URL


def create_database_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url, connect_args={"timeout": 30})

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(connection, _):
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    return engine


engine = create_database_engine(DATABASE_URL)
SessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as db:
        try:
            yield db
            if db.in_transaction():
                await db.commit()
        except Exception:
            await db.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_async_db, scope="function")]
