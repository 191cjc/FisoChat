# Technical Design

## Scope and Boundaries

The change is confined to database lifecycle, schema migration, message writes,
targeted tests, and operational documentation. Web routes, JSON response shapes,
Textual behavior, QQ API calls, configuration names, and deployment topology do
not change.

## Schema Contract

`group_messages` keeps its existing columns and indexes. Its message identity
changes from global `UNIQUE(message_id)` to:

```sql
UNIQUE (group_openid, message_id)
```

A FisoChat schema-version marker records the completed rebuild, but structural
inspection remains authoritative for legacy databases whose `user_version` is
zero. Known AiQQ ledger tables are an incompatible writable schema and cause a
fail-closed error.

## Initialization and Migration

`GroupMessageRepository.initialize` gains an initialization lock and performs a
double check so concurrent first-use calls cannot run migration twice.

Initialization follows this state machine:

```text
no group_messages table -> create current schema -> ready
current composite schema -> ensure indexes/version -> ready
legacy FisoChat schema -> backup -> atomic rebuild -> verify -> ready
AiQQ ledger schema -> compatibility error -> no writes
unknown/incomplete schema -> migration error -> no writes
```

The connection layer exposes a narrow consistent-backup operation. For a
non-empty legacy database it writes a sibling pre-migration backup through a
mode-`0600` temporary file and atomically renames it. An existing completed
backup is retained rather than overwritten.

The table rebuild runs in one transaction:

1. Create a replacement table with the current columns and composite key.
2. Copy rows with explicit `record_id`; supply the default recall value when
   migrating the pre-recall schema.
3. Verify source/destination counts and ID bounds.
4. Replace the old table and recreate all indexes.
5. Verify composite uniqueness, foreign keys, and autoincrement state.
6. Set the FisoChat schema marker and commit.

Any exception rolls back the rebuild. Backup failures occur before mutation and
also abort startup.

## Duplicate Event Projection

The repository owns one normalization and fidelity comparison path for gateway
events. The selected projection obeys these invariants:

- identity is `(group_openid, message_id)` and never changes;
- an explicit `GROUP_AT_MESSAGE_CREATE` outranks `GROUP_MESSAGE_CREATE`;
- within the same event class, the projection with more non-empty payload and
  convenience fields wins;
- empty incoming values do not erase non-empty stored values;
- an existing recall timestamp is never cleared by duplicate ingestion;
- equal or lower-fidelity repeats are no-ops apart from safe enrichment;
- bot-message duplicate insertion is idempotent and cannot move groups.

Selection and write happen in one connection transaction. The existing global
database lock provides serialization, so no second lock or retry loop is added.

## Cross-Layer Effects

The stored and returned record shapes do not change. All readers already scope
identity-sensitive queries by `group_openid`; regression tests will cover recent
messages, recalls, mention target lookup, and reply context after cross-group
collisions.

The web viewer, admin API, console, and sender continue consuming the same
`StoredGroupMessage` and `GroupMessageSummary` projections. No response schema or
display behavior changes.

## Terminal History Selection

The terminal message stream keeps its Rich-styled, scrollable presentation but
uses a narrow `RichLog` subclass that supplies the line offsets, selected-text
extraction, and selection highlighting missing from Textual 6.12's base widget.
Mouse selection remains owned by Textual's screen selection model, so clicking
outside a drag still restores composer focus and the draft cursor behavior does
not change.

`Ctrl+C` copies the active screen selection through Textual's clipboard path.
`Ctrl+Q` and `/quit` remain explicit exit paths. Selecting or copying history
must not mutate the composer value, message records, or scroll position.

## Failure Handling and Observability

Migration and compatibility failures surface during repository initialization,
before the HTTP server and QQ login start. Logs may include schema state and
backup paths, but never payloads, credentials, member identifiers, or tokens.

Normal duplicate delivery is not logged as an error. Backup creation and schema
upgrade completion receive one concise structured informational log entry.

## Rollout and Rollback

Implementation validation uses generated legacy fixtures and temporary copies;
the running production database is not a test target. This task does not restart
the production service automatically.

Deployment requires a controlled service restart. Startup creates the one-time
legacy backup before migration. To roll back, stop the service, preserve the
failed current file for diagnosis, restore the standalone backup to the configured
database path, and run the prior source version. Documentation must warn against
copying a live WAL database file directly.

## Trade-offs

The single-table projection stays easy to query and operate, but cannot replay
all raw events or retain every conflicting non-empty version. The conservative
fidelity rules protect known data while keeping scope proportional. A complete
event ledger remains a separate future project.
