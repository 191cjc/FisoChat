# Implementation Plan

## 1. Establish Migration Fixtures

- Extend database tests with pre-recall, current legacy, current composite, and
  incompatible AiQQ-ledger schema fixtures.
- Add reusable assertions for row identity, stored-field equality, integrity,
  and next autoincrement behavior.
- Confirm the existing migration test remains valid before changing production
  code.

## 2. Add Safe Schema Lifecycle

- Add schema inspection and explicit FisoChat schema state/version constants in
  `database/migrations.py`.
- Add a narrow SQLite backup operation in `database/connection.py` that uses a
  `0600` temporary destination and atomic rename.
- Serialize repository initialization and create a backup only for a non-empty
  legacy FisoChat schema.
- Rebuild the legacy table transactionally with explicit IDs, composite
  uniqueness, preserved defaults, recreated indexes, and post-copy checks.
- Fail closed for known AiQQ ledger or unknown incompatible schemas.

Rollback point: before changing write semantics, run the migration tests against
all generated fixtures and confirm the backup can be opened independently.

## 3. Make Writes Group-Scoped and Non-destructive

- Replace the 14-position generic upsert path with named message-write data so
  identity and merge fields are auditable.
- Conflict on `(group_openid, message_id)` for gateway and bot records.
- Centralize gateway fidelity/completeness comparison and conservative field
  enrichment in the repository layer.
- Preserve recall markers and make bot duplicate writes idempotent.
- Keep every query that accepts a message ID explicitly group-scoped.

Rollback point: run database and sender tests before touching documentation or
deployment instructions.

## 4. Add Cross-Layer Regression Coverage

- Test equal IDs in separate groups through repository reads, recall ownership,
  mention lookup, and reply context.
- Test sparse/rich gateway duplicates in both orders and recall preservation.
- Test migration idempotence, backup non-overwrite, backup permissions, failure
  rollback, and incompatible-ledger rejection.
- Run standalone application tests to prove HTTP response shapes and terminal
  projections remain unchanged.

## 5. Document Operation

- Update `README.md` and `MIGRATION.md` with schema behavior, automatic backup
  naming, controlled restart, integrity verification, and rollback steps.
- Update the database audit cross-reference without rewriting its historical
  point-in-time findings.
- Do not alter systemd or Nginx behavior unless validation proves a required
  operational change.

## 5a. Restore Terminal History Copying

- Add a focused selectable message-log implementation around Textual's
  `RichLog`, preserving Rich styles, wrapping, scrolling, and existing focus
  behavior.
- Bind `Ctrl+C` to copying an active text selection and retain `Ctrl+Q` plus
  `/quit` as explicit exit paths.
- Add a terminal regression that drags over chat history, verifies the copied
  text, and proves the current draft and application remain intact.
- Update terminal shortcut documentation without changing the web viewer.

## 6. Validation Gate

Run, in order:

```bash
uv run python -m unittest tests.test_group_messages -v
uv run python -m unittest tests.test_qq_sender tests.test_standalone_app -v
uv run python -m unittest discover -s tests -v
git diff --check
uv build
```

Then inspect the diff for accidental public API, configuration, deployment, or
unrelated formatting changes. Do not send a real QQ message and do not restart
the production service as part of this task's automated validation.

## Risky Files and Review Focus

- `src/fisochat/database/migrations.py`: atomicity, legacy column handling,
  composite constraint, sequence preservation, incompatible schema detection.
- `src/fisochat/database/connection.py`: backup consistency, permissions,
  temporary-file cleanup, locking.
- `src/fisochat/database/group_messages.py`: group-scoped identity, deterministic
  merge rules, recall preservation, initialization races.
- `tests/test_group_messages.py`: non-tautological fixtures that would fail under
  the old global-conflict implementation.
- `README.md` and `MIGRATION.md`: rollback instructions must match actual backup
  and migration behavior.
