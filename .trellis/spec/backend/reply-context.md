# QQ Reply Context Contracts

## Scenario: Terminal Native Reply

### 1. Scope / Trigger

Use these contracts whenever code changes terminal `/reply`, the loopback
message-send API, stored QQ message identity, reply-context selection, or QQ
`msg_id` / `msg_seq` delivery.

The terminal displays a local numeric `record_id`, but QQ replies use the
incoming payload's opaque `message_id`. These identifiers are different and
must never be substituted for one another.

### 2. Signatures

Loopback API:

```text
POST /internal/group-messages
```

Reply request:

```json
{
  "group_openid": "<current-group>",
  "content": "reply text",
  "reply_to_message_id": "<opaque-qq-message-id>",
  "mentions": []
}
```

Core boundaries:

```python
await repository.find_console_reply_context(
    group_id: str, *, message_id: str | None = None
) -> GroupReplyContext | None

await sender.send_text_reply(
    *, group_id: str, source_message_id: str, content: str,
    msg_seq: int, origin: str, ...
)
```

### 3. Contracts

- `/reply <record_id>` resolves the selected record to its stored
  `message_id`; only that message ID crosses the API and QQ sender boundaries.
- `reply_to_message_id` is an opaque string of 1 through 256 characters. Every
  character must be printable and non-whitespace. Punctuation such as `.` and
  `!` is valid and must be forwarded byte-for-byte.
- Omitting `reply_to_message_id` selects proactive delivery. Supplying the key
  with `null`, an empty string, or another invalid value is an invalid reply;
  it must not silently become proactive delivery.
- Group IDs and member OpenIDs keep their restrictive OpenID alphabet. Do not
  reuse their regular expression for opaque QQ message IDs, and do not broaden
  mention-target validation when changing reply validation.
- A reply source must match the requested group, be an incoming
  `GROUP_MESSAGE_CREATE` or `GROUP_AT_MESSAGE_CREATE` record, not be authored by
  this bot, and not be recalled. Both ordinary messages and messages that @ the
  bot are eligible.
- The source timestamp may be at most 30 seconds in the future for clock skew
  and must be less than five minutes old.
- Allocate the first unused sequence in `1..5` for the same group and source
  message. Sequences are derived from recorded bot replies whose
  `source_message_id` matches; exhausted sources are unavailable.
- QQ delivery sends the exact source ID as `msg_id` and the allocated sequence
  as `msg_seq`. Ambiguous send failures are not retried automatically.

### 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Reply key omitted | Proactive send; no reply lookup |
| Reply ID is null, empty, non-string, over 256 chars, whitespace-bearing, or control-bearing | `400 invalid_reply_context`; no lookup/send |
| Source missing, wrong-group, bot-authored, recalled, expired, too far in the future, or sequence-exhausted | `409 no_reply_context`; no QQ send |
| Valid ordinary or @ source | Exact ID lookup, then one QQ send with next sequence |
| QQ definite rejection or ambiguous outcome | `502 qq_send_failed`; no automatic retry |

### 5. Good / Base / Bad Cases

- Good: Selecting local record `#1956` resolves its 137-character ID containing
  `.` and `!`; the same value reaches repository lookup and QQ `msg_id`.
- Base: A valid ordinary message receives sequences 1 through 5; another
  attempt returns `no_reply_context` without calling QQ.
- Bad: Do not send `1956` or `#1956` as `msg_id`, validate message IDs with the
  member OpenID regex, accept explicit `null` as proactive delivery, or reuse a
  sequence after an uncertain outcome.

### 6. Tests Required

- API tests assert production-shaped opaque IDs survive lookup and sender calls
  unchanged; invalid IDs fail before lookup, and omitted versus explicit-null
  semantics differ.
- Repository tests assert ordinary and @ messages are eligible while group,
  direction, recall, five-minute/clock-skew, and sequence constraints remain.
- End-to-end tests assert local capture through the loopback API produces the
  exact QQ `msg_id`, increments `msg_seq`, and blocks cross-group lookup.
- Mention tests assert punctuation accepted for message IDs is still rejected
  for member OpenIDs.
- The full suite, compile, lock, diff, and package build checks must pass.

### 7. Wrong vs Correct

#### Wrong

```python
# QQ message IDs are not OpenIDs; production values contain punctuation.
MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
if reply_to is not None and not MESSAGE_ID_RE.fullmatch(reply_to):
    reject()
```

#### Correct

```python
has_reply_to = "reply_to_message_id" in payload
reply_to = payload.get("reply_to_message_id")
if has_reply_to and not valid_opaque_message_id(reply_to):
    reject()

# Keep a separate restrictive validator for member OpenIDs.
```
