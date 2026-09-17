"""Schema inspection and id-preserving group-message migrations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import aiosqlite


FISOCHAT_SCHEMA_VERSION = 1
LEGACY_BACKUP_SUFFIX = ".pre-composite-key.bak"

GROUP_MESSAGE_COLUMNS = (
    "record_id",
    "message_id",
    "event_id",
    "event_type",
    "group_openid",
    "member_openid",
    "username",
    "member_role",
    "is_bot",
    "content",
    "message_type",
    "sent_at",
    "received_at",
    "payload_json",
    "recalled_at",
)
PRE_RECALL_COLUMNS = GROUP_MESSAGE_COLUMNS[:-1]
GROUP_MESSAGE_COLUMN_CONTRACT = (
    ("record_id", "INTEGER", False, 1),
    ("message_id", "TEXT", True, 0),
    ("event_id", "TEXT", True, 0),
    ("event_type", "TEXT", True, 0),
    ("group_openid", "TEXT", True, 0),
    ("member_openid", "TEXT", True, 0),
    ("username", "TEXT", True, 0),
    ("member_role", "TEXT", True, 0),
    ("is_bot", "INTEGER", True, 0),
    ("content", "TEXT", True, 0),
    ("message_type", "INTEGER", False, 0),
    ("sent_at", "TEXT", True, 0),
    ("received_at", "TEXT", True, 0),
    ("payload_json", "TEXT", True, 0),
    ("recalled_at", "TEXT", True, 0),
)
PRE_RECALL_COLUMN_CONTRACT = GROUP_MESSAGE_COLUMN_CONTRACT[:-1]
AIQQ_LEDGER_TABLES = frozenset(
    {
        "group_message_events",
        "message_event_processing",
        "message_versions",
        "message_attachments",
        "message_delivery_attempts",
    }
)

CREATE_GROUP_MESSAGES_SQL = """
    CREATE TABLE {table_name} (
        record_id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT NOT NULL,
        event_id TEXT NOT NULL DEFAULT '',
        event_type TEXT NOT NULL,
        group_openid TEXT NOT NULL,
        member_openid TEXT NOT NULL DEFAULT '',
        username TEXT NOT NULL DEFAULT '',
        member_role TEXT NOT NULL DEFAULT '',
        is_bot INTEGER NOT NULL DEFAULT 0,
        content TEXT NOT NULL DEFAULT '',
        message_type INTEGER,
        sent_at TEXT NOT NULL DEFAULT '',
        received_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        recalled_at TEXT NOT NULL DEFAULT '',
        UNIQUE (group_openid, message_id)
    )
"""

INDEX_STATEMENTS = (
    """
    CREATE INDEX IF NOT EXISTS idx_group_messages_group_record
    ON group_messages (group_openid, record_id DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_group_messages_member_record
    ON group_messages (group_openid, member_openid, record_id DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_group_messages_reference
    ON group_messages (group_openid, event_type, recalled_at, record_id DESC)
    """,
)


class GroupMessageSchemaKind(Enum):
    FRESH = "fresh"
    LEGACY_PRE_RECALL = "legacy_pre_recall"
    LEGACY = "legacy"
    CURRENT = "current"


@dataclass(frozen=True)
class GroupMessageSchema:
    kind: GroupMessageSchemaKind
    row_count: int = 0

    @property
    def is_legacy(self) -> bool:
        return self.kind in {
            GroupMessageSchemaKind.LEGACY_PRE_RECALL,
            GroupMessageSchemaKind.LEGACY,
        }


class GroupMessageSchemaError(RuntimeError):
    """Raised when a database is not safely writable by FisoChat."""


class IncompatibleAiQQDatabaseError(GroupMessageSchemaError):
    """Raised when the database contains AiQQ's event-ledger schema."""


async def inspect_group_messages_schema(
    connection: aiosqlite.Connection,
) -> GroupMessageSchema:
    table_names = await _table_names(connection)
    ledger_tables = sorted(table_names.intersection(AIQQ_LEDGER_TABLES))
    if ledger_tables:
        joined = ", ".join(ledger_tables)
        raise IncompatibleAiQQDatabaseError(
            "database contains the current AiQQ event-ledger schema "
            f"({joined}); configure FISOCHAT_DB to use a dedicated FisoChat "
            "database or a legacy single-table snapshot"
        )
    user_version = int(await _scalar(connection, "PRAGMA user_version"))
    if "group_messages" not in table_names:
        if user_version != 0:
            raise GroupMessageSchemaError(
                f"unsupported FisoChat schema version {user_version} without "
                "a group_messages table"
            )
        return GroupMessageSchema(GroupMessageSchemaKind.FRESH)

    columns = await _table_column_contract(connection)
    unique_keys = await _unique_keys(connection)
    row_count = await _row_count(connection, "group_messages")
    global_key = ("message_id",)
    composite_key = ("group_openid", "message_id")

    if (
        columns == GROUP_MESSAGE_COLUMN_CONTRACT
        and unique_keys == {composite_key}
        and user_version in {0, FISOCHAT_SCHEMA_VERSION}
    ):
        return GroupMessageSchema(GroupMessageSchemaKind.CURRENT, row_count)
    if (
        columns == GROUP_MESSAGE_COLUMN_CONTRACT
        and unique_keys == {global_key}
        and user_version == 0
    ):
        return GroupMessageSchema(GroupMessageSchemaKind.LEGACY, row_count)
    if (
        columns == PRE_RECALL_COLUMN_CONTRACT
        and unique_keys == {global_key}
        and user_version == 0
    ):
        return GroupMessageSchema(
            GroupMessageSchemaKind.LEGACY_PRE_RECALL, row_count
        )

    raise GroupMessageSchemaError(
        "unsupported group_messages schema; use a dedicated FisoChat database "
        "or restore a supported legacy single-table snapshot"
    )


async def migrate_group_messages(connection: aiosqlite.Connection) -> None:
    """Create or atomically upgrade the FisoChat group-message projection."""
    await connection.execute("BEGIN IMMEDIATE")
    schema = await inspect_group_messages_schema(connection)
    if schema.kind is GroupMessageSchemaKind.FRESH:
        await connection.execute(
            CREATE_GROUP_MESSAGES_SQL.format(table_name="group_messages")
        )
    elif schema.is_legacy:
        await _rebuild_legacy_table(connection, schema)

    await _create_indexes(connection)
    await connection.execute(f"PRAGMA user_version = {FISOCHAT_SCHEMA_VERSION}")


async def _rebuild_legacy_table(
    connection: aiosqlite.Connection, schema: GroupMessageSchema
) -> None:
    replacement = "group_messages__fisochat_v1"
    await connection.execute(f"DROP TABLE IF EXISTS {replacement}")
    source_stats = await _record_id_stats(connection, "group_messages")
    source_sequence = await _sequence_value(connection, "group_messages")
    await connection.execute(
        CREATE_GROUP_MESSAGES_SQL.format(table_name=replacement)
    )

    source_fields = ", ".join(PRE_RECALL_COLUMNS)
    if schema.kind is GroupMessageSchemaKind.LEGACY:
        destination_fields = ", ".join(GROUP_MESSAGE_COLUMNS)
        select_fields = destination_fields
    else:
        destination_fields = ", ".join(GROUP_MESSAGE_COLUMNS)
        select_fields = f"{source_fields}, ''"
    await connection.execute(
        f"INSERT INTO {replacement} ({destination_fields}) "
        f"SELECT {select_fields} FROM group_messages"
    )

    await _verify_rebuilt_table(connection, replacement, source_stats)
    await connection.execute("DROP TABLE group_messages")
    await connection.execute(
        f"ALTER TABLE {replacement} RENAME TO group_messages"
    )
    expected_sequence = max(source_sequence, source_stats[2] or 0)
    await _restore_sequence(connection, source_sequence, source_stats[2])
    await _create_indexes(connection)
    await _verify_current_table(connection, source_stats, expected_sequence)


async def _verify_rebuilt_table(
    connection: aiosqlite.Connection,
    table_name: str,
    expected_stats: tuple[int, int | None, int | None],
) -> None:
    if await _record_id_stats(connection, table_name) != expected_stats:
        raise GroupMessageSchemaError(
            "group_messages migration verification failed before table replacement"
        )
    duplicate_count = await _scalar(
        connection,
        f"""
        SELECT COUNT(*) FROM (
            SELECT group_openid, message_id
            FROM {table_name}
            GROUP BY group_openid, message_id
            HAVING COUNT(*) > 1
        )
        """,
    )
    if duplicate_count:
        raise GroupMessageSchemaError(
            "group_messages migration found duplicate composite message identities"
        )


async def _verify_current_table(
    connection: aiosqlite.Connection,
    expected_stats: tuple[int, int | None, int | None],
    expected_sequence: int,
) -> None:
    schema = await inspect_group_messages_schema(connection)
    if schema.kind is not GroupMessageSchemaKind.CURRENT:
        raise GroupMessageSchemaError(
            "group_messages migration did not create the expected composite schema"
        )
    if await _record_id_stats(connection, "group_messages") != expected_stats:
        raise GroupMessageSchemaError(
            "group_messages migration changed record identifiers"
        )
    if await _sequence_value(connection, "group_messages") != expected_sequence:
        raise GroupMessageSchemaError(
            "group_messages migration changed the autoincrement sequence"
        )
    async with connection.execute("PRAGMA foreign_key_check") as cursor:
        if await cursor.fetchone() is not None:
            raise GroupMessageSchemaError(
                "database foreign-key verification failed during migration"
            )


async def _create_indexes(connection: aiosqlite.Connection) -> None:
    for statement in INDEX_STATEMENTS:
        await connection.execute(statement)


async def _table_names(connection: aiosqlite.Connection) -> set[str]:
    async with connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ) as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


async def _table_column_contract(
    connection: aiosqlite.Connection,
) -> tuple[tuple[str, str, bool, int], ...]:
    async with connection.execute("PRAGMA table_info(group_messages)") as cursor:
        return tuple(
            (str(row[1]), str(row[2]).upper(), bool(row[3]), int(row[5]))
            for row in await cursor.fetchall()
        )


async def _unique_keys(
    connection: aiosqlite.Connection,
) -> set[tuple[str, ...]]:
    async with connection.execute("PRAGMA index_list(group_messages)") as cursor:
        indexes = await cursor.fetchall()
    keys: set[tuple[str, ...]] = set()
    for index in indexes:
        if not bool(index[2]):
            continue
        index_name = str(index[1]).replace('"', '""')
        async with connection.execute(
            f'PRAGMA index_info("{index_name}")'
        ) as cursor:
            keys.add(tuple(str(row[2]) for row in await cursor.fetchall()))
    return keys


async def _row_count(connection: aiosqlite.Connection, table_name: str) -> int:
    return int(await _scalar(connection, f"SELECT COUNT(*) FROM {table_name}"))


async def _record_id_stats(
    connection: aiosqlite.Connection, table_name: str
) -> tuple[int, int | None, int | None]:
    async with connection.execute(
        f"SELECT COUNT(*), MIN(record_id), MAX(record_id) FROM {table_name}"
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0]), row[1], row[2]


async def _sequence_value(
    connection: aiosqlite.Connection, table_name: str
) -> int:
    async with connection.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = ?", (table_name,)
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row is not None else 0


async def _restore_sequence(
    connection: aiosqlite.Connection,
    source_sequence: int,
    maximum_record_id: int | None,
) -> None:
    sequence = max(source_sequence, maximum_record_id or 0)
    await connection.execute(
        "DELETE FROM sqlite_sequence "
        "WHERE name IN ('group_messages', 'group_messages__fisochat_v1')"
    )
    if sequence:
        await connection.execute(
            "INSERT INTO sqlite_sequence(name, seq) VALUES ('group_messages', ?)",
            (sequence,),
        )


async def _scalar(connection: aiosqlite.Connection, sql: str) -> object:
    async with connection.execute(sql) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise GroupMessageSchemaError("schema inspection returned no result")
    return row[0]
