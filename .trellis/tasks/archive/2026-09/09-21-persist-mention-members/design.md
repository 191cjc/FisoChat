# Design: Persistent Mentionable Group Members

## Architecture

Use the existing append-only group message history as the only durable source:

```text
QQ gateway message
  -> existing group_messages row (group + member_openid + username)
  -> repository latest eligible row per member
  -> authenticated GET /internal/group-members?group=<group>
  -> terminal member directory
  -> existing MentionMember / MentionSpan completion
  -> existing POST /internal/group-messages record-anchor validation
  -> QQ member mention markup
```

No member table or schema version is added. This prevents a second persistent
projection from drifting when gateway duplicates merge, usernames change, or an
operator starts with an existing database.

## Repository Contract

Add a group-scoped repository query that returns the latest eligible gateway row
for each non-empty `member_openid`:

- filter to `GROUP_MESSAGE_CREATE` and `GROUP_AT_MESSAGE_CREATE`;
- filter to unrecalled rows before choosing the latest record;
- partition/deduplicate by `member_openid` within the supplied group;
- order final rows by `record_id DESC`;
- leave the restrictive OpenID format check at the web projection boundary so it
  uses the same validator as send-time mention validation.

The existing member-record index covers the query shape. The returned stored row
provides the record anchor, latest username, member OpenID, and event metadata
without introducing another cross-layer model.

## HTTP Contract

Register an authenticated loopback endpoint:

```text
GET /internal/group-members?group=<group_openid>
```

Successful response:

```json
{
  "members": [
    {
      "record_id": 123,
      "sender_key": "stable-group-scoped-hash",
      "username": "display name"
    }
  ]
}
```

Apply the same remote-address and Bearer-token checks as all `/internal/*`
routes. Require one valid `group` value. Project only display metadata and a local
record anchor; do not expose `member_openid`. Reuse the same group-scoped
`sender_key` derivation and `_can_mention()` predicate used by message views.
Return candidates in descending anchor order and set `Cache-Control: no-store`.

## Terminal State

Add `ConsoleClient.members(group)` and load it alongside recent messages during
group selection. Maintain the active group's mention directory keyed by
`sender_key`:

- endpoint results seed the directory;
- a newer eligible message projection replaces the same sender's anchor/name;
- candidates are sorted by descending `record_id` before calling
  `CommandInput.set_members()`;
- group switches replace the active directory while existing per-group drafts
  retain their selected `MentionSpan` objects;
- failed sends keep the current draft and selected anchors unchanged.

This retains local `@query` filtering and duplicate-name alias behavior. The
normal two-second message synchronization supplies immediate new-speaker and
nickname updates without refetching the full member directory each interval.

## Send Boundary

Do not change the outgoing mention payload. It remains a list of
`record_id/start/end` spans. `AdminMessageHandler` continues to resolve each
record inside the requested group and build `member_mention()` from the stored
OpenID. Missing, recalled, invalid, or cross-group anchors fail before QQ send.

## Compatibility And Migration

- No SQLite migration or startup backfill.
- Existing history becomes available on the first member-endpoint request.
- `/at <record_id>` stays limited to loaded records.
- Reply, alerts, stickers, image preview, history paging, and sending contracts
  remain unchanged.

## Risks And Rollback

- A group with a long history can contain many unique speakers. The response is
  still bounded by actual distinct group participants and carries only three
  small fields per member; avoid an arbitrary limit that would violate the
  feature's promise.
- A selected draft anchor could become unavailable before send. Existing
  send-time validation rejects it safely; do not trust cached member state.
- Rollback removes the endpoint/client member load and restores member derivation
  solely from loaded messages. No stored data requires reversal.
