# Current Recall Behavior

## Existing Boundary

- `QQMessageSender.recall_from_group()` already issues exactly one
  `DELETE /v2/groups/{group_openid}/messages/{message_id}` request.
- It rejects unrecorded, expired, and unowned targets before DELETE, then marks a
  successful result recalled in the repository.
- Its current boolean result conflates an ineligible target, an ownership lookup
  failure, a QQ DELETE failure, and failure to persist the recalled state.
- No production caller currently invokes `recall_from_group`; only sender tests
  cover it, so replacing the boolean with a typed outcome has a contained blast
  radius.

## Stored Identity and Scope

- Terminal history displays local numeric `record_id` values, while QQ requires
  the opaque stored `message_id`.
- `GroupMessageRepository.get_by_record_id(group_id, record_id)` is group-scoped
  and excludes recalled rows. It therefore prevents a record from another group,
  an already recalled record, or an unknown record from resolving.
- `StoredGroupMessage` retains the group, bot-author flag, opaque message ID,
  timestamp, and recalled state needed to construct a recall target.
- `is_owned_bot_message(group_id, message_id)` provides a second ownership and
  group check immediately before the QQ request.

## Terminal and API Patterns

- Slash commands live in `console_commands.py`; dispatch is centralized in
  `FisoChatApp.command()`.
- `/reply` and `/image` already use the displayed local record number and require
  the record to be loaded in the current terminal history.
- The loopback admin handler enforces local-only access, Bearer authentication,
  exact request fields, strict group IDs, and positive 64-bit record IDs.
- `ConsoleClient._request()` projects structured API errors into `ConsoleError`
  and already supports special messaging for ambiguous message sends.
- Message projections expose `recalled`, and `message_text()` renders it as
  `[已撤回]`; the terminal cache must be updated and redrawn because incremental
  refresh only merges previously unseen record IDs.

## Error Contract

| Condition | Proposed result |
| --- | --- |
| Invalid JSON, fields, group, or record number | `400` with the existing structured error shape |
| Missing, wrong-group, user-authored, recalled, or expired record | `409 not_recallable`; no QQ DELETE |
| QQ rejection, network ambiguity, ownership-check error, or local mark failure | `502 qq_recall_failed`; no automatic retry |
| QQ DELETE and local mark both succeed | `200` with `ok` and `record_id` |

The failure message for `502` must state that the outcome may be uncertain and
that the operator should inspect history rather than immediately retrying.

## Affected Tests

- Sender: typed success, not-recallable, and failed outcomes; exact opaque QQ ID;
  no DELETE for invalid targets; no retry on exceptions.
- Admin API: auth, strict body validation, group scoping, direction/expiry checks,
  response mapping, and route registration.
- Console client and app: request shape, ambiguous failure copy, command discovery,
  immediate dispatch, invalid targets, successful redraw, and error recovery.
- Regression: repository, reply, sticker, mention, multiline input, history copy,
  and the full suite.

## Compatibility

- No schema or configuration migration is required.
- The loopback-only API and existing Bearer token remain unchanged.
- No live QQ recall should be triggered by automated verification.
