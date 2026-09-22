# Persistent Mention-Member Contracts

## 1. Scope / Trigger

Use these contracts whenever code changes member discovery, terminal `@`
completion, stored group-member identity, the loopback member endpoint, or
mention target validation.

FisoChat does not fetch a complete QQ group roster. A member becomes available
for completion after at least one incoming gateway message from that member has
been stored in the group history.

## 2. Signatures

Repository boundary:

```python
await repository.mentionable_members(
    group_id: str,
) -> tuple[StoredGroupMessage, ...]
```

Authenticated loopback API:

```text
GET /internal/group-members?group=<group-openid>
Authorization: Bearer <admin-token>
```

Response projection:

```json
{
  "members": [
    {
      "record_id": 123,
      "sender_key": "24-character-group-scoped-hash",
      "username": "display name"
    }
  ]
}
```

Terminal client boundary:

```python
await ConsoleClient.members(group: str) -> list[dict[str, Any]]
```

The outgoing message contract remains a list of mention spans containing only
`record_id`, `start`, and `end`. It does not accept `member_openid`.

## 3. Contracts

- `group_messages` is the durable source of truth. Do not create a second member
  table, startup backfill, or independent member cache in SQLite.
- Select only unrecalled `GROUP_MESSAGE_CREATE` and
  `GROUP_AT_MESSAGE_CREATE` rows in the requested group with a non-empty member
  OpenID. Choose the latest eligible `record_id` for each member OpenID and
  order the result by descending record ID.
- The current `(group_openid, member_openid, record_id DESC)` database index must
  remain available for the latest-per-member query.
- The web boundary applies the same restrictive member OpenID eligibility check
  used during sending. Invalid OpenIDs are omitted from the projection.
- The response exposes a local record anchor, group-scoped sender key, and
  display name. It never exposes the raw member OpenID.
- Incoming records from other bots are valid targets. FisoChat's own outbound
  `BOT_*` records are not.
- Group selection seeds the terminal member directory from the endpoint. Newly
  synchronized eligible messages replace older entries with the same sender key
  when their record ID is newer, so new speakers and renamed members appear
  without reopening the group.
- Member aliases, completion filtering, flat mention offsets, multiline input,
  per-group drafts, and failed-send restoration follow the terminal composer
  contracts.
- Send-time validation remains authoritative: resolve every record anchor with
  `get_by_record_id(group_id, record_id)`, apply mention eligibility again, and
  derive QQ markup from the stored member OpenID.
- `/at <record_id>` remains limited to a currently loaded message. Persistent
  historical discovery belongs to interactive `@` completion.

## 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Non-loopback request | `403`; no repository query |
| Missing or invalid Bearer token | `401`; no repository query |
| Missing, duplicate, malformed, or extra `group` query value | `400 invalid_group` |
| Valid group with no observed members | `200` with `{"members": []}` |
| Same member has several eligible rows | Return only the latest row |
| Member belongs only to another group | Do not return or resolve that member |
| Latest row is recalled but an older eligible row exists | Use the latest unrecalled row |
| Empty or invalid stored member OpenID | Omit the candidate |
| Incoming other-bot gateway row | Include the candidate |
| FisoChat outbound row | Omit the candidate |
| Anchor becomes invalid before send | Reject through existing mention validation; no QQ send |

Successful member responses use `Cache-Control: no-store`.

## 5. Good / Base / Bad Cases

- Good: A member last spoke before the terminal's latest 50 records. Typing `@`
  finds the member immediately from existing SQLite history, and sending uses
  the projected record anchor to recover the stored OpenID on the server.
- Base: A new message changes a known member's display name. Normal incremental
  history synchronization updates that sender's completion entry to the newer
  anchor and name.
- Bad: Do not send raw member OpenIDs to the terminal, trust a terminal-supplied
  OpenID, mix candidates across groups, or require `/older` to populate the
  persistent directory.

## 6. Tests Required

- Repository tests assert per-group deduplication, latest unrecalled anchor and
  username selection, descending order, gateway-event eligibility, other-bot
  support, and exclusion of outbound or missing-identity rows.
- Handler tests assert loopback and Bearer authorization, exact group-query
  validation, invalid OpenID filtering, stable projection fields, no raw OpenID
  disclosure, and `Cache-Control: no-store`.
- Real application tests assert route registration and client request shape.
- Terminal tests assert discovery outside loaded history, live add and rename,
  group isolation, duplicate-name aliases, draft preservation, record-only send
  payloads, and unchanged `/at` behavior.
- Run the full unittest suite, compileall, lock check, diff check, and package
  build.

## 7. Wrong vs Correct

### Wrong

```python
# The client can forge or reuse an identity from another group.
payload["mentions"] = [{"member_openid": selected.openid, ...}]
```

### Correct

```python
# The client sends only the local anchor and flat text range.
payload["mentions"] = [
    {"record_id": selected.record_id, "start": start, "end": end}
]

# The server resolves the anchor inside the requested group and revalidates it.
record = await repository.get_by_record_id(group_id, selected_record_id)
if record is None or not _can_mention(record):
    reject()
```
