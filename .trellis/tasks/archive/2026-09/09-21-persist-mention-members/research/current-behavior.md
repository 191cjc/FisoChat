# Current Mention-Member Behavior

## Stored Identity

- Incoming gateway records already persist the group, member OpenID, username,
  event type, recall state, and local record ID.
- The current schema has an index on
  `(group_openid, member_openid, record_id DESC)`, so latest-per-member lookup is
  supported without migration.
- Member OpenIDs use the existing restrictive `MEMBER_OPENID_RE`; QQ message IDs
  remain a separate opaque identity contract.

## Terminal Limitation

- Initial group selection loads the latest 50 message records.
- `FisoChatApp._refresh_members()` derives completion members only from the
  active in-memory message cache, selecting the newest loaded eligible record
  for each sender key.
- `/older` can expand that cache, but it is capped at 2,000 records. Therefore a
  previously observed member can be absent even though their OpenID is durable
  in SQLite.

## Existing Trust Boundary

- `MentionMember` retains a local record ID and display metadata; outgoing spans
  contain `record_id`, `start`, and `end` only.
- The admin handler resolves each record through
  `get_by_record_id(group_id, record_id)`, then `_can_mention()` requires an
  incoming gateway event, an unrecalled row, and a valid member OpenID.
- QQ markup is built from the server-resolved `member_openid`. The terminal never
  supplies a raw OpenID, preventing arbitrary and cross-group mention targets.
- Incoming other-bot records can be mentioned. FisoChat's own outbound records
  use `BOT_*` event types and cannot be mention targets.

## Minimal Extension

- Query one latest eligible stored gateway row per member OpenID for the selected
  group and expose only the record anchor plus display metadata through a new
  authenticated loopback endpoint.
- Seed terminal completion from that projection on group selection.
- Upsert completion state from newly synchronized messages so new speakers and
  nickname changes appear without polling the complete member projection every
  two seconds.
- Reuse the existing send-time record lookup and `_can_mention()` validation.

## Compatibility

- No schema, configuration, or data migration is required.
- Existing databases act as the historical member source immediately.
- `/at <record_id>` remains record-oriented; persistent historical discovery is
  limited to the interactive `@` completion list.
