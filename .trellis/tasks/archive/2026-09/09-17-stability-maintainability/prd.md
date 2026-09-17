# Stability and Maintainability Optimization

## Goal

Prevent known message-history corruption modes and make the affected database
code easier to verify, while preserving FisoChat's current QQ, web, console,
CLI, and deployment behavior.

## Background

- FisoChat is a standalone Python 3.11+ QQ group-message recorder, viewer, and
  sender extracted from AiQQ. It uses `qq-botpy`, `aiohttp`, `aiosqlite`, and
  Textual (`README.md`, `pyproject.toml`).
- The service currently runs through `fisochat.service`; its database and QQ
  gateway were healthy when this task was created.
- The baseline is 105 passing unit and integration tests.
- The repository has no commits yet and contains about 60 uncommitted files.
  Existing user changes must be preserved.
- Backend Trellis guidelines remain placeholders under the separate
  `00-bootstrap-guidelines` task. This task must not overwrite or complete it.

## Confirmed Risks

- The legacy table declares `message_id TEXT NOT NULL UNIQUE`, so equal message
  IDs in different groups conflict (`src/fisochat/database/migrations.py:12`).
- The write path uses `ON CONFLICT(message_id) DO UPDATE` and replaces every
  projected field. A later sparse event can move a row between groups, discard
  richer payload data, or clear recall state
  (`src/fisochat/database/group_messages.py:358`).
- The 2026-09-16 audit reproduced both failure modes and establishes that
  current AiQQ ledger databases are not safe writable targets for FisoChat
  (`docs/database-audit-2026-09-16.md`).
- Database access uses one `aiosqlite` connection guarded by one async lock.
  Reads and writes are serialized, which makes a transaction-scoped merge safe
  at current traffic levels (`src/fisochat/database/connection.py:14`).

## Requirements

- Migrate legacy FisoChat databases from global message-ID uniqueness to a
  `(group_openid, message_id)` unique key.
- Preserve every existing row, `record_id`, user-visible field, raw payload,
  recall state, and autoincrement continuity through migration.
- Create an automatic, consistent, permission-restricted backup before changing
  a non-empty legacy database. Do not overwrite the pre-migration backup on
  later starts.
- Perform the schema rebuild atomically and fail startup without exposing a
  partially migrated database.
- Make migration detection and execution idempotent for fresh, legacy, and
  already-migrated FisoChat databases.
- Reject writable use of a current AiQQ event-ledger database rather than
  bypassing its event, version, attachment, and delivery records.
- Store equal message IDs from different groups as independent records.
- Handle repeat delivery within one group idempotently. Prefer the more
  informative gateway projection and never replace non-empty stored data with
  an empty value or clear an existing recall marker.
- Preserve all documented user workflows and HTTP contracts.
- Preserve the delivery invariant that ambiguous send outcomes are never
  retried automatically.
- Make terminal chat history selectable with the mouse and copyable with
  `Ctrl+C` without clearing the draft or exiting the application. Keep an
  explicit keyboard shortcut and `/quit` command for exiting.
- Do not expose member OpenIDs, credentials, raw event payloads, or admin tokens
  through public routes or new logs.
- Add regression tests for each corrected migration and merge failure mode.
- Do not send real QQ messages or destructively test against production data.

## Acceptance Criteria

- [ ] A pre-recall legacy schema and the current legacy schema both migrate to
      the composite key without changing row count, `record_id` values, stored
      fields, or the next autoincrement value.
- [ ] A non-empty legacy database receives one standalone `0600` SQLite backup
      before migration; a failed migration leaves the source usable and does
      not overwrite a prior backup.
- [ ] Fresh and already-migrated databases initialize repeatedly without data
      or schema churn.
- [ ] The same `message_id` can coexist in two groups and all group-scoped
      reads, recalls, mentions, and replies select the correct row.
- [ ] Sparse/rich duplicate gateway events produce the same rich projection in
      either arrival order, and duplicate delivery never clears recall state.
- [ ] An AiQQ ledger database fails closed with an actionable compatibility
      error before FisoChat writes to it.
- [ ] Web, console, CLI, health, authentication, mention, image-preview, reply,
      send, and read-only behavior remain compatible.
- [ ] Dragging across terminal chat history produces a visible text selection;
      `Ctrl+C` copies it without exiting or changing the draft, while the
      documented exit paths still work.
- [ ] All existing and new tests pass, `git diff --check` passes, and the package
      builds successfully from the locked dependency set.
- [ ] Documentation describes automatic migration, backup location, restore
      procedure, compatibility boundary, and the need for a controlled restart.

## In Scope

- Schema inspection, one-time backup, atomic table rebuild, and rollback docs.
- Composite-key writes and conservative duplicate-event projection selection.
- Focused cleanup that makes the changed database path explicit and testable.
- Database, integration, documentation, and package-build verification.
- A focused terminal interaction fix for selecting and copying chat history.

## Out of Scope

- Full raw-event, message-version, attachment, processing, or delivery ledgers;
  those remain a possible follow-up if forensic replay becomes a requirement.
- New AI features, automatic replies, or third-party message forwarding.
- Web or terminal visual redesign.
- Replacing SQLite or `qq-botpy`.
- Repository-wide refactors, speculative performance work, or unrelated lint
  cleanup.
- Automatic production restart or real QQ delivery during validation.

## Key Decisions

- The user approved an SQLite schema migration with backup, rollback, and
  legacy-database coverage.
- The first optimization phase keeps a corrected single-table current
  projection. It does not port AiQQ's complete event/version ledger.
- Migration runs automatically before the HTTP service or QQ gateway starts.
- A one-time consistent backup and transactional rebuild are preferred over an
  online dual-write migration; startup will take a short, controlled pause.
