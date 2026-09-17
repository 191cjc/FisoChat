import asyncio
import tempfile
import sqlite3
import unittest
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fisochat.database.connection import SQLiteConnection
from fisochat.database.group_messages import (
    GroupMessageRepository,
    _merge_gateway_messages,
    _MessageWrite,
)
from fisochat.database.migrations import (
    FISOCHAT_SCHEMA_VERSION,
    LEGACY_BACKUP_SUFFIX,
    GroupMessageSchemaError,
    IncompatibleAiQQDatabaseError,
)


LEGACY_COLUMNS = (
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
)


def create_legacy_database(path: Path, *, include_recalled: bool) -> tuple:
    recalled_column = ", recalled_at TEXT NOT NULL DEFAULT ''" if include_recalled else ""
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"""
            CREATE TABLE group_messages (
                record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL UNIQUE,
                event_id TEXT NOT NULL DEFAULT '', event_type TEXT NOT NULL,
                group_openid TEXT NOT NULL, member_openid TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '', member_role TEXT NOT NULL DEFAULT '',
                is_bot INTEGER NOT NULL DEFAULT 0, content TEXT NOT NULL DEFAULT '',
                message_type INTEGER, sent_at TEXT NOT NULL DEFAULT '',
                received_at TEXT NOT NULL, payload_json TEXT NOT NULL
                {recalled_column}
            )
            """
        )
        fields = LEGACY_COLUMNS + (("recalled_at",) if include_recalled else ())
        values = (
            7,
            "old-message",
            "old-event",
            "BOT_MESSAGE_CREATE",
            "old-group",
            "member-old",
            "旧用户",
            "owner",
            1,
            "保留原有聊天记录",
            2,
            "2026-09-01T00:00:00+00:00",
            "2026-09-01T00:00:01+00:00",
            '{"content":"保留原有聊天记录","msg_seq":1}',
        ) + (("2026-09-01T00:01:00+00:00",) if include_recalled else ())
        placeholders = ", ".join("?" for _ in fields)
        connection.execute(
            f"INSERT INTO group_messages ({', '.join(fields)}) "
            f"VALUES ({placeholders})",
            values,
        )
        connection.execute(
            "UPDATE sqlite_sequence SET seq = 40 WHERE name = 'group_messages'"
        )
    return values


def backup_path(path: Path) -> Path:
    return path.with_name(path.name + LEGACY_BACKUP_SUFFIX)


def unique_keys(path: Path) -> set[tuple[str, ...]]:
    with sqlite3.connect(path) as connection:
        indexes = connection.execute("PRAGMA index_list(group_messages)").fetchall()
        return {
            tuple(
                row[2]
                for row in connection.execute(
                    f'PRAGMA index_info("{index[1]}")'
                ).fetchall()
            )
            for index in indexes
            if index[2]
        }


class LegacyDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_pre_recall_aiqq_schema_migrates_without_losing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            original = create_legacy_database(path, include_recalled=False)
            repository = GroupMessageRepository(SQLiteConnection(path))
            try:
                await repository.initialize()
                records = await repository.recent("old-group")
                self.assertEqual(records[0].content, "保留原有聊天记录")
                self.assertEqual(records[0].record_id, 7)
                self.assertEqual(records[0].recalled_at, "")
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            finally:
                await repository.close()

            with sqlite3.connect(path) as connection:
                migrated = connection.execute(
                    f"SELECT {', '.join(LEGACY_COLUMNS)}, recalled_at "
                    "FROM group_messages"
                ).fetchone()
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(migrated, original + ("",))
            self.assertEqual(version, FISOCHAT_SCHEMA_VERSION)
            self.assertEqual(
                unique_keys(path), {("group_openid", "message_id")}
            )

    async def test_current_legacy_schema_preserves_fields_sequence_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            original = create_legacy_database(path, include_recalled=True)
            repository = GroupMessageRepository(SQLiteConnection(path))
            try:
                await repository.initialize()
                await repository.add_bot_message(
                    message_id="next-message",
                    group_openid="old-group",
                    username="AiQQ",
                    content="next",
                    message_type=0,
                    sent_at="2026-09-01T00:02:00+00:00",
                    payload={"content": "next"},
                )
            finally:
                await repository.close()

            saved_backup = backup_path(path)
            self.assertTrue(saved_backup.is_file())
            self.assertEqual(saved_backup.stat().st_mode & 0o777, 0o600)
            with sqlite3.connect(path) as connection:
                migrated = connection.execute(
                    f"SELECT {', '.join(LEGACY_COLUMNS)}, recalled_at "
                    "FROM group_messages WHERE message_id = 'old-message'"
                ).fetchone()
                next_id = connection.execute(
                    "SELECT record_id FROM group_messages "
                    "WHERE message_id = 'next-message'"
                ).fetchone()[0]
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
            self.assertEqual(migrated, original)
            self.assertEqual(next_id, 41)
            self.assertEqual(unique_keys(saved_backup), {("message_id",)})
            with sqlite3.connect(saved_backup) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM group_messages"
                    ).fetchone()[0],
                    1,
                )

            backup_bytes = saved_backup.read_bytes()
            second = GroupMessageRepository(SQLiteConnection(path))
            try:
                await second.initialize()
                await second.initialize()
            finally:
                await second.close()
            self.assertEqual(saved_backup.read_bytes(), backup_bytes)

    async def test_empty_legacy_and_current_databases_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.db"
            create_legacy_database(path, include_recalled=True)
            with sqlite3.connect(path) as connection:
                connection.execute("DELETE FROM group_messages")
                connection.execute("DELETE FROM sqlite_sequence")
            repository = GroupMessageRepository(SQLiteConnection(path))
            try:
                await asyncio.gather(
                    repository.initialize(), repository.initialize()
                )
            finally:
                await repository.close()
            self.assertFalse(backup_path(path).exists())
            self.assertEqual(
                unique_keys(path), {("group_openid", "message_id")}
            )

            second = GroupMessageRepository(SQLiteConnection(path))
            try:
                await second.initialize()
            finally:
                await second.close()
            self.assertFalse(backup_path(path).exists())

    async def test_failed_migration_rolls_back_and_keeps_first_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            create_legacy_database(path, include_recalled=True)
            repository = GroupMessageRepository(SQLiteConnection(path))
            with patch(
                "fisochat.database.migrations._verify_current_table",
                new=AsyncMock(side_effect=RuntimeError("injected failure")),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected failure"):
                    await repository.initialize()
            await repository.close()

            saved_backup = backup_path(path)
            first_backup = saved_backup.read_bytes()
            self.assertEqual(unique_keys(path), {("message_id",)})
            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT content FROM group_messages"
                    ).fetchone()[0],
                    "保留原有聊天记录",
                )

            retry = GroupMessageRepository(SQLiteConnection(path))
            try:
                await retry.initialize()
            finally:
                await retry.close()
            self.assertEqual(saved_backup.read_bytes(), first_backup)
            self.assertEqual(
                unique_keys(path), {("group_openid", "message_id")}
            )

    async def test_sequence_verification_failure_rolls_back_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            create_legacy_database(path, include_recalled=True)
            repository = GroupMessageRepository(SQLiteConnection(path))
            with patch(
                "fisochat.database.migrations._restore_sequence",
                new=AsyncMock(),
            ):
                with self.assertRaisesRegex(
                    GroupMessageSchemaError, "autoincrement sequence"
                ):
                    await repository.initialize()
            await repository.close()

            self.assertEqual(unique_keys(path), {("message_id",)})
            with sqlite3.connect(path) as connection:
                sequence = connection.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name = 'group_messages'"
                ).fetchone()[0]
            self.assertEqual(sequence, 40)

    async def test_backup_failure_prevents_schema_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            create_legacy_database(path, include_recalled=True)
            database = SQLiteConnection(path)
            repository = GroupMessageRepository(database)
            with patch.object(
                database,
                "backup_once",
                new=AsyncMock(side_effect=OSError("backup unavailable")),
            ):
                with self.assertRaisesRegex(OSError, "backup unavailable"):
                    await repository.initialize()
            await repository.close()
            self.assertEqual(unique_keys(path), {("message_id",)})
            self.assertFalse(backup_path(path).exists())

    async def test_invalid_existing_backup_prevents_schema_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            create_legacy_database(path, include_recalled=True)
            saved_backup = backup_path(path)
            saved_backup.write_text("not a sqlite database", encoding="utf-8")
            repository = GroupMessageRepository(SQLiteConnection(path))
            try:
                with self.assertRaisesRegex(
                    RuntimeError, "existing database backup is invalid"
                ):
                    await repository.initialize()
            finally:
                await repository.close()
            self.assertEqual(unique_keys(path), {("message_id",)})
            self.assertEqual(
                saved_backup.read_text(encoding="utf-8"),
                "not a sqlite database",
            )

    async def test_existing_backup_must_be_a_legacy_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            create_legacy_database(path, include_recalled=True)
            saved_backup = backup_path(path)
            current = GroupMessageRepository(SQLiteConnection(saved_backup))
            try:
                await current.initialize()
            finally:
                await current.close()

            repository = GroupMessageRepository(SQLiteConnection(path))
            try:
                with self.assertRaisesRegex(
                    RuntimeError, "not a supported legacy schema"
                ):
                    await repository.initialize()
            finally:
                await repository.close()

            self.assertEqual(unique_keys(path), {("message_id",)})
            self.assertEqual(
                unique_keys(saved_backup), {("group_openid", "message_id")}
            )

    async def test_existing_backup_cannot_alias_the_source_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            create_legacy_database(path, include_recalled=True)
            saved_backup = backup_path(path)
            saved_backup.hardlink_to(path)

            repository = GroupMessageRepository(SQLiteConnection(path))
            try:
                with self.assertRaisesRegex(
                    RuntimeError, "aliases the source database"
                ):
                    await repository.initialize()
            finally:
                await repository.close()

            self.assertTrue(path.samefile(saved_backup))
            self.assertEqual(unique_keys(path), {("message_id",)})

    async def test_aiqq_event_ledger_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aiqq.db"
            create_legacy_database(path, include_recalled=True)
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE group_message_events "
                    "(event_record_id INTEGER PRIMARY KEY)"
                )
                journal_mode = connection.execute(
                    "PRAGMA journal_mode"
                ).fetchone()[0]
            repository = GroupMessageRepository(SQLiteConnection(path))
            try:
                with self.assertRaisesRegex(
                    IncompatibleAiQQDatabaseError, "event-ledger"
                ):
                    await repository.initialize()
            finally:
                await repository.close()
            self.assertEqual(unique_keys(path), {("message_id",)})
            self.assertFalse(backup_path(path).exists())
            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA journal_mode").fetchone()[0],
                    journal_mode,
                )

    async def test_unknown_group_message_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE group_messages "
                    "(record_id INTEGER PRIMARY KEY, message_id TEXT)"
                )
            repository = GroupMessageRepository(SQLiteConnection(path))
            try:
                with self.assertRaisesRegex(
                    GroupMessageSchemaError, "unsupported group_messages schema"
                ):
                    await repository.initialize()
            finally:
                await repository.close()

    async def test_current_like_schema_with_weakened_constraints_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "incomplete.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TABLE group_messages (
                        record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        message_id TEXT NOT NULL,
                        event_id TEXT NOT NULL DEFAULT '',
                        event_type TEXT NOT NULL,
                        group_openid TEXT NOT NULL,
                        member_openid TEXT NOT NULL DEFAULT '',
                        username TEXT NOT NULL DEFAULT '',
                        member_role TEXT NOT NULL DEFAULT '',
                        is_bot INTEGER NOT NULL DEFAULT 0,
                        content TEXT DEFAULT '',
                        message_type INTEGER,
                        sent_at TEXT NOT NULL DEFAULT '',
                        received_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        recalled_at TEXT NOT NULL DEFAULT '',
                        UNIQUE (group_openid, message_id)
                    )
                    """
                )
            repository = GroupMessageRepository(SQLiteConnection(path))
            try:
                with self.assertRaisesRegex(
                    GroupMessageSchemaError, "unsupported group_messages schema"
                ):
                    await repository.initialize()
            finally:
                await repository.close()

    async def test_unknown_future_schema_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.db"
            create_legacy_database(path, include_recalled=True)
            with sqlite3.connect(path) as connection:
                connection.execute("PRAGMA user_version = 99")
            repository = GroupMessageRepository(SQLiteConnection(path))
            try:
                with self.assertRaisesRegex(
                    GroupMessageSchemaError, "unsupported group_messages schema"
                ):
                    await repository.initialize()
            finally:
                await repository.close()
            self.assertEqual(unique_keys(path), {("message_id",)})
            self.assertFalse(backup_path(path).exists())


def group_event(
    message_id: str,
    *,
    event_type: str = "GROUP_MESSAGE_CREATE",
    group_id: str = "group-1",
    content: str = "hello",
    image: bool = False,
):
    data = {
        "id": message_id,
        "group_openid": group_id,
        "content": content,
        "message_type": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "author": {
            "member_openid": f"member-{message_id}",
            "username": f"user-{message_id}",
            "member_role": "member",
            "bot": False,
        },
        "attachments": [],
    }
    if image:
        data["attachments"] = [
            {
                "content_type": "image/jpeg",
                "filename": "photo.jpg",
                "url": "https://private.qq.example/photo.jpg",
            }
        ]
    return event_type, {"id": f"event-{message_id}", "d": data}


class GroupMessageRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "group_messages.db"
        self.repository = GroupMessageRepository(SQLiteConnection(self.path))
        await self.repository.initialize()

    async def asyncTearDown(self):
        await self.repository.close()
        self.temporary.cleanup()

    async def add_event(self, message_id, **kwargs):
        event_type, payload = group_event(message_id, **kwargs)
        self.assertTrue(
            await self.repository.add_gateway_event(event_type, payload)
        )

    async def test_reference_contains_non_at_messages_and_bot_final_replies(self):
        await self.add_event("plain", content="not mentioned")
        await self.add_event(
            "mentioned", event_type="GROUP_AT_MESSAGE_CREATE", content="question"
        )
        await self.repository.add_bot_message(
            message_id="bot-final",
            group_openid="group-1",
            username="AiQQ",
            content="final answer",
            message_type=2,
            sent_at="2026-09-09T12:00:01+08:00",
            payload={"content": "final answer"},
            source_message_id="mentioned",
        )
        await self.add_event(
            "current", event_type="GROUP_AT_MESSAGE_CREATE", content="current"
        )

        history = await self.repository.list_for_reference(
            "group-1", before_message_id="current", limit=50
        )

        self.assertEqual(
            [item.content for item in history],
            ["not mentioned", "question", "final answer"],
        )
        self.assertEqual([item.role for item in history], ["user", "user", "assistant"])

    async def test_progress_and_recalled_messages_are_not_reference_material(self):
        await self.add_event("first", image=True)
        await self.repository.add_bot_message(
            message_id="progress",
            group_openid="group-1",
            username="AiQQ",
            content="searching",
            message_type=0,
            sent_at="2026-09-09T12:00:01+08:00",
            payload={"content": "searching"},
            progress=True,
        )
        await self.repository.add_bot_message(
            message_id="recalled",
            group_openid="group-1",
            username="AiQQ",
            content="temporary final",
            message_type=0,
            sent_at="2026-09-09T12:00:02+08:00",
            payload={"content": "temporary final"},
        )
        self.assertTrue(
            await self.repository.mark_recalled(
                group_id="group-1", message_id="recalled"
            )
        )

        history = await self.repository.list_for_reference(
            "group-1", before_message_id="", limit=50
        )

        self.assertEqual([item.content for item in history], ["hello"])
        self.assertTrue(history[0].has_image)

    async def test_reference_image_urls_are_group_scoped_and_include_quotes(self):
        event_type, payload = group_event(
            "image-message", group_id="group-a", image=True
        )
        payload["d"]["msg_elements"] = [
            {
                "attachments": [
                    {
                        "content_type": "image/jpeg",
                        "url": "https://images.example/quoted.jpg",
                    },
                    {
                        "content_type": "text/plain",
                        "url": "https://images.example/not-image.txt",
                    },
                ]
            }
        ]
        await self.repository.add_gateway_event(event_type, payload)
        record = (await self.repository.recent("group-a"))[0]

        urls = await self.repository.list_image_urls("group-a", record.record_id)

        self.assertEqual(
            urls,
            (
                "https://private.qq.example/photo.jpg",
                "https://images.example/quoted.jpg",
            ),
        )
        self.assertEqual(
            await self.repository.list_image_urls("group-b", record.record_id), ()
        )

    async def test_recall_ownership_is_group_scoped_and_bot_only(self):
        await self.add_event("user-message")
        await self.repository.add_bot_message(
            message_id="bot-message",
            group_openid="group-1",
            username="AiQQ",
            content="reply",
            message_type=0,
            sent_at="2026-09-09T12:00:01+08:00",
            payload={"content": "reply"},
        )
        self.assertFalse(
            await self.repository.is_owned_bot_message(
                group_id="group-1", message_id="user-message"
            )
        )
        self.assertFalse(
            await self.repository.is_owned_bot_message(
                group_id="other-group", message_id="bot-message"
            )
        )
        self.assertTrue(
            await self.repository.is_owned_bot_message(
                group_id="group-1", message_id="bot-message"
            )
        )

    async def test_equal_message_ids_remain_independent_across_groups(self):
        await self.add_event(
            "shared-user",
            group_id="group-a",
            event_type="GROUP_AT_MESSAGE_CREATE",
            content="from a",
        )
        await self.add_event(
            "shared-user", group_id="group-b", content="from b"
        )
        await self.repository.add_bot_message(
            message_id="shared-bot",
            group_openid="group-a",
            username="AiQQ",
            content="bot a",
            message_type=0,
            sent_at="2026-09-09T12:00:01+08:00",
            payload={"content": "bot a"},
        )
        await self.repository.add_bot_message(
            message_id="shared-bot",
            group_openid="group-b",
            username="AiQQ",
            content="bot b",
            message_type=0,
            sent_at="2026-09-09T12:00:02+08:00",
            payload={"content": "bot b"},
        )

        group_a = await self.repository.recent("group-a")
        group_b = await self.repository.recent("group-b")
        self.assertEqual(
            {record.content for record in group_a}, {"from a", "bot a"}
        )
        self.assertEqual(
            {record.content for record in group_b}, {"from b", "bot b"}
        )
        group_a_user = next(
            record for record in group_a if record.message_id == "shared-user"
        )
        self.assertIsNone(
            await self.repository.get_by_record_id(
                "group-b", group_a_user.record_id
            )
        )

        self.assertTrue(
            await self.repository.mark_recalled(
                group_id="group-a", message_id="shared-bot"
            )
        )
        self.assertFalse(
            await self.repository.is_owned_bot_message(
                group_id="group-a", message_id="shared-bot"
            )
        )
        self.assertTrue(
            await self.repository.is_owned_bot_message(
                group_id="group-b", message_id="shared-bot"
            )
        )
        self.assertIsNotNone(
            await self.repository.find_console_reply_context(
                "group-a", message_id="shared-user"
            )
        )
        self.assertIsNone(
            await self.repository.find_console_reply_context(
                "group-b", message_id="shared-user"
            )
        )

    async def test_reference_cursor_with_equal_ids_is_group_scoped(self):
        await self.add_event("older-a", group_id="group-a", content="a old")
        await self.add_event("older-b", group_id="group-b", content="b old")
        await self.add_event("boundary", group_id="group-a", content="a now")
        await self.add_event("boundary", group_id="group-b", content="b now")

        history_a = await self.repository.list_for_reference(
            "group-a", before_message_id="boundary", limit=50
        )
        history_b = await self.repository.list_for_reference(
            "group-b", before_message_id="boundary", limit=50
        )

        self.assertEqual([item.content for item in history_a], ["a old"])
        self.assertEqual([item.content for item in history_b], ["b old"])

    async def test_rich_gateway_projection_wins_in_either_arrival_order(self):
        for message_id, rich_first in (("rich-first", True), ("sparse-first", False)):
            event_type, rich = group_event(
                message_id,
                event_type="GROUP_MESSAGE_CREATE",
                content="complete message",
                image=True,
            )
            rich["id"] = f"rich-event-{message_id}"
            sparse = {
                "id": "",
                "d": {
                    "id": message_id,
                    "group_openid": "group-1",
                    "content": "",
                    "author": {},
                },
            }
            ordered = (rich, sparse) if rich_first else (sparse, rich)
            for payload in ordered:
                self.assertTrue(
                    await self.repository.add_gateway_event(event_type, payload)
                )

            record = next(
                item
                for item in await self.repository.recent("group-1")
                if item.message_id == message_id
            )
            self.assertEqual(record.event_id, f"rich-event-{message_id}")
            self.assertEqual(record.content, "complete message")
            self.assertEqual(record.username, f"user-{message_id}")
            self.assertEqual(record.payload["attachments"][0]["filename"], "photo.jpg")

    async def test_at_event_priority_is_order_independent_and_enriches_fields(self):
        for message_id, at_first in (("at-first", True), ("plain-first", False)):
            _, plain = group_event(
                message_id,
                event_type="GROUP_MESSAGE_CREATE",
                content="plain detail",
                image=True,
            )
            _, at_event = group_event(
                message_id,
                event_type="GROUP_AT_MESSAGE_CREATE",
                content="",
            )
            at_event["id"] = f"at-event-{message_id}"
            at_event["d"]["author"] = {}
            ordered = (at_event, plain) if at_first else (plain, at_event)
            for payload in ordered:
                event_type = (
                    "GROUP_AT_MESSAGE_CREATE"
                    if payload is at_event
                    else "GROUP_MESSAGE_CREATE"
                )
                await self.repository.add_gateway_event(event_type, payload)

            record = next(
                item
                for item in await self.repository.recent("group-1")
                if item.message_id == message_id
            )
            self.assertEqual(record.event_type, "GROUP_AT_MESSAGE_CREATE")
            self.assertEqual(record.event_id, f"at-event-{message_id}")
            self.assertEqual(record.content, "plain detail")
            self.assertEqual(record.username, f"user-{message_id}")
            self.assertEqual(
                record.payload["attachments"][0]["filename"], "photo.jpg"
            )

    def test_three_conflicting_duplicates_merge_identically_in_every_order(self):
        messages = (
            _MessageWrite(
                message_id="shared",
                event_id="event-a",
                event_type="GROUP_MESSAGE_CREATE",
                group_openid="group-1",
                member_openid="member-a",
                username="",
                member_role="member",
                is_bot=0,
                content="short",
                message_type=0,
                sent_at="2026-09-09T12:00:01+00:00",
                received_at="2026-09-09T12:00:03+00:00",
                payload_json='{"content":"short"}',
                recalled_at="",
            ),
            _MessageWrite(
                message_id="shared",
                event_id="event-b-long",
                event_type="GROUP_AT_MESSAGE_CREATE",
                group_openid="group-1",
                member_openid="",
                username="user-b",
                member_role="owner",
                is_bot=0,
                content="",
                message_type=2,
                sent_at="2026-09-09T12:00:02+00:00",
                received_at="2026-09-09T12:00:02+00:00",
                payload_json='{"content":"","mentions":[{"is_you":true}]}',
                recalled_at="2026-09-09T12:01:00+00:00",
            ),
            _MessageWrite(
                message_id="shared",
                event_id="event-c",
                event_type="GROUP_MESSAGE_CREATE",
                group_openid="group-1",
                member_openid="member-c-long",
                username="",
                member_role="",
                is_bot=0,
                content="the most detailed content",
                message_type=1,
                sent_at="2026-09-09T12:00:03+00:00",
                received_at="2026-09-09T12:00:01+00:00",
                payload_json=(
                    '{"attachments":[{"filename":"photo.jpg",'
                    '"url":"https://example.invalid/photo.jpg"}],'
                    '"content":"the most detailed content"}'
                ),
                recalled_at="",
            ),
        )

        outcomes = set()
        for ordered in permutations(messages):
            merged = _merge_gateway_messages(ordered[0], ordered[1])
            merged = _merge_gateway_messages(merged, ordered[2])
            outcomes.add(merged)

        self.assertEqual(len(outcomes), 1)
        result = outcomes.pop()
        self.assertEqual(result.event_type, "GROUP_AT_MESSAGE_CREATE")
        self.assertEqual(result.event_id, "event-b-long")
        self.assertEqual(result.member_openid, "member-c-long")
        self.assertEqual(result.username, "user-b")
        self.assertEqual(result.content, "the most detailed content")
        self.assertEqual(result.message_type, 2)
        self.assertEqual(result.received_at, "2026-09-09T12:00:01+00:00")
        self.assertEqual(result.recalled_at, "2026-09-09T12:01:00+00:00")
        self.assertIn("photo.jpg", result.payload_json)
        self.assertEqual(_merge_gateway_messages(result, result), result)

    async def test_duplicate_bot_insert_does_not_clear_recall_or_rewrite_record(self):
        self.assertTrue(
            await self.repository.add_bot_message(
                message_id="bot-duplicate",
                group_openid="group-1",
                username="AiQQ",
                content="first success",
                message_type=0,
                sent_at="2026-09-09T12:00:01+08:00",
                payload={"content": "first success"},
            )
        )
        self.assertTrue(
            await self.repository.mark_recalled(
                group_id="group-1", message_id="bot-duplicate"
            )
        )
        before = next(
            record
            for record in await self.repository.recent("group-1")
            if record.message_id == "bot-duplicate"
        )

        self.assertTrue(
            await self.repository.add_bot_message(
                message_id="bot-duplicate",
                group_openid="group-1",
                username="changed",
                content="second projection",
                message_type=2,
                sent_at="2026-09-09T12:00:02+08:00",
                payload={"content": "second projection"},
            )
        )
        after = next(
            record
            for record in await self.repository.recent("group-1")
            if record.message_id == "bot-duplicate"
        )

        self.assertEqual(after.record_id, before.record_id)
        self.assertEqual(after.content, "first success")
        self.assertEqual(after.username, "AiQQ")
        self.assertEqual(after.payload, {"content": "first success"})
        self.assertEqual(after.recalled_at, before.recalled_at)

    async def test_bot_insert_reports_user_identity_conflict_as_unrecorded(self):
        await self.add_event("identity-conflict", content="existing user message")

        recorded = await self.repository.add_bot_message(
            message_id="identity-conflict",
            group_openid="group-1",
            username="AiQQ",
            content="bot projection",
            message_type=0,
            sent_at="2026-09-09T12:00:01+08:00",
            payload={"content": "bot projection"},
        )

        self.assertFalse(recorded)
        record = next(
            item
            for item in await self.repository.recent("group-1")
            if item.message_id == "identity-conflict"
        )
        self.assertFalse(record.is_bot)
        self.assertEqual(record.content, "existing user message")

    async def test_filtering_happens_before_fifty_message_limit(self):
        await self.add_event("valid-old", content="must remain")
        for index in range(60):
            await self.repository.add_bot_message(
                message_id=f"progress-{index}",
                group_openid="group-1",
                username="AiQQ",
                content="temporary",
                message_type=0,
                sent_at="2026-09-09T12:00:01+08:00",
                payload={"content": "temporary"},
                progress=True,
            )
        history = await self.repository.list_for_reference(
            "group-1", before_message_id="", limit=50
        )
        self.assertEqual([item.content for item in history], ["must remain"])

    async def test_console_context_only_uses_recent_mentions_and_free_sequence(self):
        await self.add_event("plain")
        await self.add_event("mention", event_type="GROUP_AT_MESSAGE_CREATE")
        await self.repository.add_bot_message(
            message_id="first-reply",
            group_openid="group-1",
            username="AiQQ",
            content="reply",
            message_type=0,
            sent_at=datetime.now(timezone.utc).isoformat(),
            payload={"msg_seq": 1},
            source_message_id="mention",
        )

        context = await self.repository.find_console_reply_context("group-1")

        self.assertIsNotNone(context)
        self.assertEqual(context.message_id, "mention")
        self.assertEqual(context.next_sequence, 2)

    async def test_console_context_rejects_non_mention_explicit_message(self):
        await self.add_event("plain")
        context = await self.repository.find_console_reply_context(
            "group-1", message_id="plain"
        )
        self.assertIsNone(context)

    async def test_groups_are_sorted_by_latest_message(self):
        await self.add_event("group-one", group_id="group-1", content="older")
        await self.add_event("group-two", group_id="group-2", content="newer")

        groups = await self.repository.groups()

        self.assertEqual(
            [group.group_openid for group in groups], ["group-2", "group-1"]
        )
        self.assertEqual(groups[0].latest_content, "newer")
        self.assertEqual(groups[0].message_count, 1)


if __name__ == "__main__":
    unittest.main()
