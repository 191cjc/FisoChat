# Persist mentionable group members

## Goal

Allow the operator to mention any member who has ever produced a stored gateway
message in the active group, even when that member's messages are outside the
terminal's currently loaded history.

The feature should reuse FisoChat's durable message history as the source of
truth. It must not require a complete QQ group roster or weaken the current
server-side validation of mention targets.

## Background

- Every incoming `GROUP_MESSAGE_CREATE` and `GROUP_AT_MESSAGE_CREATE` record
  already stores `group_openid`, `member_openid`, `username`, and `record_id` in
  `group_messages` ([group_messages.py](../../../src/fisochat/database/group_messages.py#L95)).
- The existing `(group_openid, member_openid, record_id DESC)` index supports a
  group-scoped latest-record query without a schema change
  ([migrations.py](../../../src/fisochat/database/migrations.py#L81)).
- Mention completion currently derives candidates only from the active
  terminal's loaded `messages` cache ([console.py](../../../src/fisochat/console.py#L967)).
  Initial history contains 50 records and the cache is capped at 2,000, so an
  older speaker disappears from completion until `/older` reaches them.
- The terminal sends a local `record_id`, not a raw `member_openid`. The admin
  handler resolves that record inside the requested group and applies
  `_can_mention()` before constructing QQ markup
  ([admin_messages.py](../../../src/fisochat/interfaces/web/admin_messages.py#L328)).
- Existing behavior intentionally permits incoming messages from other bots as
  mention targets while excluding FisoChat's own outbound records
  ([test_console_mentions.py](../../../tests/test_console_mentions.py#L41)).

## Requirements

- Provide a loopback-authenticated, group-scoped member projection containing
  every distinct valid `member_openid` that has appeared in a stored incoming
  group-message event.
- Derive the member projection from existing `group_messages` rows. Existing
  databases must gain the behavior immediately, without a new member table,
  backfill job, or schema migration.
- Identify members by `member_openid` within a group. For duplicate appearances,
  use the latest eligible record as the validation anchor and display that
  record's username, with the existing `群成员` fallback. Order candidates by
  most recent eligible activity.
- Exclude FisoChat's outbound records, records with invalid or missing member
  OpenIDs, and recalled records. Preserve the existing ability to mention other
  bots whose messages arrived through the QQ gateway.
- Load the persistent member projection when selecting a group. A newly observed
  speaker or later username must update completion after the corresponding live
  message is synchronized, without requiring a group switch or restart.
- Preserve local filtering and insertion behavior for `@` completion, including
  aliases for duplicate display names, flat mention offsets, multiline input,
  per-group drafts, and failed-send restoration.
- Preserve the existing trust boundary: outgoing mention spans carry a local
  record anchor; the backend re-resolves it within the supplied group and derives
  the real `member_openid`. The terminal must not be allowed to submit an
  arbitrary member OpenID.
- Keep `/at <record_id>` compatible with its current meaning: it targets a
  currently loaded record. Persistent historical discovery is provided through
  `@` completion.

## Acceptance Criteria

- [ ] After starting against an existing database, typing `@` can find a member
      whose only message lies outside the latest 50 records, without using
      `/older`.
- [ ] Each group exposes one candidate per valid `member_openid`; members from
      another group never appear or resolve in the active group.
- [ ] A member's latest eligible username and record anchor are shown, and
      candidates are ordered by latest eligible activity.
- [ ] A new speaker and a later nickname become available after normal live
      synchronization, without reopening the group.
- [ ] Selecting a persistent candidate produces the existing display mention and
      sends exactly one server-validated QQ mention for the correct stored
      `member_openid`.
- [ ] Invalid/missing OpenIDs, recalled rows, and FisoChat's outbound rows are
      excluded, while incoming messages authored by other bots remain eligible.
- [ ] Cross-group anchors and stale or invalid records are rejected by the
      existing send boundary; raw member OpenIDs are never accepted from the
      terminal.
- [ ] Existing reply, `/at`, command completion, multiline editing, draft
      switching, mention-offset, failure recovery, history, and alert tests keep
      passing.
- [ ] Repository, admin API, console client, route registration, and terminal
      tests cover historical discovery, deduplication, latest-name selection,
      group isolation, live updates, and invalid candidates.

## Out of Scope

- Fetching or displaying the complete QQ group roster.
- Tracking members who joined but have never sent a message.
- Member removal, manual member-directory editing, expiry, or retention policies.
- A browser UI or changes to QQ mention syntax.
- Changing `/at` from a record-oriented command into a member search command.
