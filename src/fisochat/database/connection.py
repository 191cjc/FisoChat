"""SQLite connection lifecycle shared by database repositories."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


logger = logging.getLogger(__name__)


class SQLiteConnection:
    def __init__(self, path: str | Path, *, timeout_seconds: int = 10) -> None:
        self.path = Path(path).expanduser()
        self.timeout_seconds = timeout_seconds
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._write_configured = False

    @property
    def is_open(self) -> bool:
        return self._connection is not None

    async def initialize(self) -> None:
        async with self._lock:
            await self._initialize_locked()

    async def _initialize_locked(self) -> aiosqlite.Connection:
        if self._connection is not None:
            return self._connection
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(
            self.path, timeout=self.timeout_seconds
        )
        try:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA busy_timeout=10000")
            await connection.execute("PRAGMA foreign_keys=ON")
        except Exception:
            await connection.close()
            raise
        self._connection = connection
        return connection

    async def configure_for_writes(self) -> None:
        async with self._lock:
            if self._write_configured:
                return
            connection = await self._initialize_locked()
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.execute("PRAGMA synchronous=NORMAL")
            os.chmod(self.path, 0o600)
            self._write_configured = True

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._lock:
            connection = await self._initialize_locked()
            try:
                yield connection
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise

    @asynccontextmanager
    async def read(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._lock:
            yield await self._initialize_locked()

    async def backup_once(self, destination: str | Path) -> bool:
        """Publish one consistent SQLite backup without replacing an old one."""
        destination_path = Path(destination).expanduser()
        async with self._lock:
            source = await self._initialize_locked()
            if destination_path.exists() or destination_path.is_symlink():
                await _validate_existing_backup(
                    destination_path, source_path=self.path
                )
                return False
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination_path.name}.",
                suffix=".tmp",
                dir=destination_path.parent,
            )
            os.close(descriptor)
            temporary_path = Path(temporary_name)
            target: aiosqlite.Connection | None = None
            try:
                os.chmod(temporary_path, 0o600)
                target = await aiosqlite.connect(temporary_path)
                await source.backup(target)
                async with target.execute("PRAGMA integrity_check") as cursor:
                    row = await cursor.fetchone()
                if row is None or row[0] != "ok":
                    raise RuntimeError("SQLite backup integrity check failed")
                await target.close()
                target = None
                os.link(temporary_path, destination_path)
                os.unlink(temporary_path)
                logger.info("event=database_backup_created path=%s", destination_path)
                return True
            except FileExistsError:
                await _validate_existing_backup(
                    destination_path, source_path=self.path
                )
                return False
            finally:
                if target is not None:
                    await target.close()
                temporary_path.unlink(missing_ok=True)

    async def close(self) -> None:
        async with self._lock:
            connection = self._connection
            self._connection = None
            self._write_configured = False
            if connection is not None:
                await connection.close()


async def _validate_existing_backup(path: Path, *, source_path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"existing database backup is not a regular file: {path}")
    if path.samefile(source_path):
        raise RuntimeError(
            f"existing database backup aliases the source database: {path}"
        )
    os.chmod(path, 0o600)
    connection = await aiosqlite.connect(
        f"{path.resolve().as_uri()}?mode=ro", uri=True
    )
    try:
        async with connection.execute("PRAGMA integrity_check") as cursor:
            row = await cursor.fetchone()
        if row is None or row[0] != "ok":
            raise RuntimeError(f"existing database backup is invalid: {path}")
        async with connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'group_messages'"
        ) as cursor:
            if await cursor.fetchone() is None:
                raise RuntimeError(
                    f"existing database backup has no group_messages table: {path}"
                )
        from .migrations import inspect_group_messages_schema

        schema = await inspect_group_messages_schema(connection)
        if not schema.is_legacy:
            raise RuntimeError(
                f"existing database backup is not a supported legacy schema: {path}"
            )
    except aiosqlite.DatabaseError as exc:
        raise RuntimeError(f"existing database backup is invalid: {path}") from exc
    finally:
        await connection.close()
