# Current Mention Flow Evidence

## Gateway and Storage

- The gateway persists both `GROUP_MESSAGE_CREATE` and
  `GROUP_AT_MESSAGE_CREATE` without a schema change.
- Production currently has 34 incoming records whose payload contains a
  `mentions` entry with `is_you=true`.
- Production @-bot messages commonly use `GROUP_MESSAGE_CREATE`; event type
  alone is therefore not a sufficient classifier.
- Outbound records have bot event types and `is_bot=1`; recalled records carry
  a non-empty `recalled_at` value.

## Existing Terminal Refresh

- `FisoChatApp` refreshes every two seconds.
- Every refresh gets summaries for up to 500 groups, including each group's
  `latest_record_id`.
- Only the selected group's message records are fetched incrementally. A
  notification based only on `_merge_messages` would miss inactive groups.
- Initial group selection and `/older` deliberately load history and must not
  trigger new-message notifications.
- Textual exposes `App.notify(...)` for visible popups and `App.bell()`
  separately. The chosen product behavior uses only `notify`.

## Recommended Cursor Contract

Add an authenticated loopback feed that scans global records after a numeric
cursor in ascending `record_id` order. The response filters its scanned page to
qualifying @-bot alerts but advances `next_after` to the last scanned record,
including ordinary messages. This prevents repeated rescans when a busy group
has no mentions and avoids JSON1-specific SQL parsing.

On the first successful terminal refresh, initialize the cursor from the
largest `latest_record_id` in group summaries and do not request historical
alerts. Later refreshes consume the feed in bounded pages. A reconnect retains
the in-memory cursor and therefore delivers only previously unseen records.

## Shared Classification

One shared backend projection should own the untyped payload rule:

```python
event_type == "GROUP_AT_MESSAGE_CREATE" or any(
    isinstance(item, dict) and item.get("is_you") is True
    for item in payload.get("mentions", [])
)
```

The alert endpoint additionally excludes bot-authored and recalled records.
The terminal consumes a typed projection and must not reparse raw QQ payloads.
