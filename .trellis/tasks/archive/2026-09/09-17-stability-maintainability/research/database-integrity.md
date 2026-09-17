# Database Integrity Research

## Current Data Flow

```text
QQ gateway payload
  -> ChatRecorderClient._handle_raw_group_message
  -> GroupMessageRepository.add_gateway_event
  -> GroupMessageRepository._upsert
  -> group_messages
  -> repository projections
  -> web viewer / internal API / Textual console
```

Outgoing messages use `QQMessageSender`, which waits for a QQ message ID before
calling `GroupMessageRepository.add_bot_message`. That delivery ordering is
outside the database fix and must remain unchanged.

## Evidence

- `src/fisochat/database/migrations.py:8` creates the single table and declares
  a global `UNIQUE(message_id)` constraint.
- `src/fisochat/database/group_messages.py:358` conflicts on `message_id` and
  replaces every projected field, including `group_openid`, `payload_json`, and
  `recalled_at`.
- `src/fisochat/database/connection.py:14` owns one connection and serializes
  access with an `asyncio.Lock`, so selection and update can stay inside one
  repository transaction without a second database concurrency mechanism.
- `tests/test_group_messages.py:11` already covers migration from the schema
  that predates `recalled_at`; this compatibility fixture must be retained.
- `docs/database-audit-2026-09-16.md` reproduces cross-group overwrite and rich
  event downgrade. It also records that current AiQQ has six related ledger and
  projection tables and that FisoChat's old write path is incompatible.

## Selected Model

Keep `group_messages` as the only FisoChat source of message history, but change
its identity constraint to `UNIQUE(group_openid, message_id)`. This fixes the
known collision without introducing an event-sourcing subsystem that FisoChat's
readers do not require.

Within one group, duplicate gateway events update only when the incoming
projection is more informative. Fidelity is deterministic: explicit at-message
events outrank plain group-message events, then payload/non-empty field
completeness breaks ties. Empty incoming values never erase non-empty stored
values, and `recalled_at` is preserved. Equal-fidelity repeats are idempotent.

Bot sends use the same composite identity but remain first-success projections;
repeat insertion must not rewrite an already recorded send.

## Migration Constraints

SQLite cannot drop a table-level unique constraint in place. A legacy database
therefore requires a table rebuild:

1. Inspect the table, columns, indexes, and known AiQQ ledger tables.
2. For a non-empty legacy FisoChat database, create a consistent one-time backup
   through SQLite's backup API into a sibling file with mode `0600`.
3. In one transaction, create the replacement table, copy every row including
   `record_id`, replace the old table, recreate indexes, and update the schema
   version marker.
4. Verify row count, ID bounds, composite uniqueness, and foreign-key status
   before commit.

Explicit `record_id` insertion into an `AUTOINCREMENT` table preserves IDs and
advances `sqlite_sequence` to at least the copied maximum. Tests must also prove
that the next insert uses a larger ID.

The backup is created before the rebuild and is never overwritten. A temporary
backup filename plus atomic rename prevents a partial backup from being exposed
as the rollback artifact. If backup or migration fails, service startup fails
before HTTP or QQ gateway startup.

## Compatibility Boundary

The presence of AiQQ ledger tables such as `group_message_events`,
`message_versions`, or `message_delivery_attempts` means writes must fail with a
clear compatibility error. Merely changing FisoChat's conflict target would make
the write execute while silently bypassing AiQQ's ledger invariants.

Read-only support for current AiQQ databases is not added in this phase. The
existing documented workflow remains: point FisoChat at its own database or a
legacy-model snapshot/copy.

## Deferred Alternative

Porting AiQQ's raw event, processing, version, attachment, and delivery tables
would provide replay and forensic conflict history. It was rejected for this
phase because it multiplies migration, gateway, sender, recovery, and query
contracts while the requested outcome is to protect the current standalone
tool's message history.

