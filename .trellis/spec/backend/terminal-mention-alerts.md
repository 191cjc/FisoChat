# Terminal Bot-Mention Alert Contracts

## 1. Scope / Trigger

Use this contract whenever code changes stored group-message projections,
internal terminal APIs, terminal polling, or bot-mention handling. The feature
is terminal-only: it displays newly received @-current-bot messages from every
group and must never produce a QQ-side action.

## 2. Signatures

```python
def mentions_current_bot(event_type: str, payload: Any) -> bool: ...

async def GroupMessageRepository.scan_after(
    after_record_id: int, *, limit: int = 100
) -> tuple[StoredGroupMessage, ...]: ...

GET /internal/group-mention-alerts?after=<cursor>&limit=<1..100>
```

The endpoint uses the existing Bearer admin token and loopback-only server. It
returns:

```json
{
  "mentions": [
    {
      "record_id": 123,
      "group_openid": "group-id",
      "username": "sender",
      "content": "readable bounded text",
      "sent_at": "timestamp"
    }
  ],
  "next_after": 456,
  "has_more": false
}
```

## 3. Contracts

- Scan all groups by the global integer `record_id`, strictly ascending.
- A scan page includes ordinary and bot-authored records. `next_after` is the
  final scanned record ID, even when `mentions` is empty; an empty page returns
  the supplied cursor.
- Classify a record as @-current-bot when its event type is
  `GROUP_AT_MESSAGE_CREATE`, or when a mapping in `payload["mentions"]` has
  `is_you is True`. Truthy substitutes such as `1` or `"true"` do not match.
- Project only incoming, unrecalled qualifying records into `mentions`.
- The terminal initializes its in-memory cursor from the greatest group
  `latest_record_id` on the first successful refresh and emits no historical
  notifications.
- Later refreshes retain the last successful cursor across transient errors and
  show each accepted record at most once per terminal process.
- Validate the complete feed page and every alert projection before advancing
  the cursor or showing any alert. A malformed page is rejected atomically.
- Each alert uses Textual `notify(..., timeout=8, markup=False)` with bounded,
  single-line external text. Do not call `bell()`.
- Alert polling must not change the active group, composer text/cursor/selection,
  mention spans, reply state, message-log scroll position, or persistence.
- This flow must not call the QQ sender, create an outbound record, reply,
  mention another member, or retry any send.

## 4. Validation & Error Matrix

| Condition | Result |
|-----------|--------|
| Missing/invalid Bearer token | Existing `401 unauthorized` response |
| Missing, negative, non-decimal, or `>= 2**63` `after` | `400 invalid_cursor` |
| `limit` outside `1..100` or non-decimal | `400 invalid_cursor` |
| Valid page has no matching records | `200`, empty `mentions`, cursor still advances |
| Bot-authored or recalled matching record | Omit from `mentions`, cursor still advances |
| Feed request fails | Keep the last successful terminal cursor and retry later |
| Feed shape or any alert projection is invalid | Raise `ConsoleError`; keep the cursor and emit no alerts |

Every successful endpoint response uses `Cache-Control: no-store`.

## 5. Good / Base / Bad Cases

- Good: an inactive group's incoming `GROUP_MESSAGE_CREATE` record containing
  `{"is_you": true}` produces one eight-second popup on the next poll.
- Base: ordinary records advance the cursor without displaying anything; a
  terminal restart establishes a new baseline and does not replay them.
- Bad: filtering in SQL before cursor advancement repeatedly rescans ordinary
  records and risks inconsistent malformed-payload behavior.
- Bad: deriving alerts only from the selected group's rendered messages misses
  @ messages from all other groups.

## 6. Tests Required

- Classifier tests cover both accepted markers, malformed payloads, another
  member, and truthy-but-not-boolean `is_you` values.
- Repository tests assert cross-group ascending scans, exclusive cursors, page
  limits, and ordinary-record progression.
- HTTP tests assert authentication, invalid cursor/limit responses, `no-store`,
  projection bounds, bot/recalled filtering, `next_after`, and `has_more`.
- Console client tests assert the exact route and query parameters.
- Textual tests assert initial-history suppression, inactive-group alerts,
  duplicate pages, reconnect recovery, eight-second no-markup notifications,
  no bell, no sends, and preservation of all composer/reply/group/scroll state.
- Invalid-feed tests cover a non-object top level and damaged projection
  fields; assert unchanged cursor and zero partial notifications.
- Run focused repository/API/client/terminal suites and the full test suite.

## 7. Wrong vs Correct

Wrong: inspect raw QQ payloads independently in the endpoint and terminal, or
automatically reply when an @ is found.

Correct: classify raw storage once with `mentions_current_bot`, expose a small
typed read-only feed, and let each terminal process own only its in-memory
high-water mark and popup presentation.
