# Design: Recall a Specific Group Message

## Architecture

The feature follows the existing terminal-to-QQ path:

```text
/recall <record_id>
  -> ConsoleClient (current group + local record ID)
  -> loopback authenticated admin route
  -> group-scoped stored-message lookup
  -> BotSentGroupMessage (opaque QQ message ID)
  -> QQMessageSender DELETE
  -> repository recalled marker
  -> terminal cache update and redraw
```

The local record number stops at the repository lookup. Only the opaque stored
QQ `message_id` may enter the sender and DELETE route.

## Logic and Sender Contract

Add a typed recall outcome in the logic layer with three exhaustive states:

- `recalled`: QQ DELETE succeeded and the local row was marked recalled.
- `not_recallable`: the target was not recorded, is expired, is not an owned
  unrecalled bot message in the supplied group, or no longer qualifies after a
  concurrent check.
- `failed`: ownership lookup failed, QQ DELETE failed or became ambiguous, or
  local persistence failed after DELETE.

Change `GroupMessageSender.recall_from_group()` to return this outcome. Preserve
the existing sender-side time and ownership checks as defense in depth. It must
perform at most one DELETE attempt.

## Admin API Contract

Register:

```text
POST /internal/group-messages/recall
Authorization: Bearer <admin-token>

{"group_openid": "<current-group>", "record_id": 31}
```

Apply the existing loopback and Bearer authorization before parsing. Require an
exact two-field JSON object, the existing group-ID format, and an integer record
ID in `1..2^63-1` (excluding booleans).

Under the handler's existing message-operation lock:

1. Resolve the record with `get_by_record_id(group_id, record_id)`.
2. Reject a missing, cross-group, recalled, or non-bot record as
   `409 not_recallable` without calling the sender.
3. Parse its stored timestamp and construct `BotSentGroupMessage` with the opaque
   message ID and `recorded=True`; invalid timestamps are not recallable.
4. Call the sender once and map `recalled` to HTTP 200,
   `not_recallable` to `409 not_recallable`, and `failed` to
   `502 qq_recall_failed`.

The 502 copy must cover both definite failure and uncertain remote outcome, and
must advise inspection rather than retry. A successful response is
`{"ok": true, "record_id": <id>}` with `Cache-Control: no-store`.

## Terminal Behavior

Add `/recall 31` to completion and help. Dispatch accepts exactly one positive
decimal record number and requires:

- a selected group;
- a currently loaded record with that number;
- `is_bot=true` and `recalled=false`.

Once those local checks pass, invoke the client immediately without a
confirmation screen. While the request is in flight, reuse the app's busy/input
guard so duplicate submissions and group switching cannot race the operation.

`ConsoleClient.recall()` posts the group and local record ID. Transport failure
uses recall-specific uncertain-result copy rather than send-specific copy and is
never retried automatically.

On success, set `recalled=true` on the matching cached projection, redraw history
while preserving normal navigation and reply state, and show a success notice.
On failure, retain the history state and display the server/client error. Always
restore input focus and the busy guard.

## Compatibility and Migration

- No database or configuration migration.
- Existing send, reply, sticker, mention-alert, image, copy, and multiline
  composer contracts remain unchanged.
- Existing low-level sender tests migrate from boolean assertions to typed
  outcome assertions.
- No browser UI is added; the product remains terminal-only.

## Risks and Rollback

- A DELETE can succeed remotely while the response or local mark fails. Report an
  uncertain failure and never retry automatically; the operator must inspect QQ.
- Two requests can race eligibility. The handler lock plus the sender's ownership
  check ensures only one eligible operation proceeds in this process.
- Rollback removes the terminal command/client/route and restores the sender's
  prior boolean return contract; no stored data needs reversal.
