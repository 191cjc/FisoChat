# Recall a specific message

## Goal

Add a terminal workflow that lets the operator recall one eligible message sent by
this bot, using the local record number shown in the active group's history.

The workflow must prevent a local record number from being sent to QQ as though it
were QQ's opaque message ID, and must make the result visible in the terminal.

## Background

- Terminal history and existing commands identify messages by a local numeric
  `record_id`; `/reply` and `/image` establish that operator-facing convention
  ([console_commands.py](../../../src/fisochat/console_commands.py)).
- The repository can resolve an unrecalled record only within a supplied group via
  `get_by_record_id(group_id, record_id)`
  ([group_messages.py](../../../src/fisochat/database/group_messages.py#L395)).
- The QQ sender already recalls a recorded, owned bot message through
  `DELETE /v2/groups/{group_openid}/messages/{message_id}` and enforces the
  configured recall window, currently 120 seconds
  ([sender.py](../../../src/fisochat/services/qq/sender.py#L330)).
- Existing sender tests cover a successful recall and rejection of unowned or
  expired targets ([test_qq_sender.py](../../../tests/test_qq_sender.py#L321)).
- The current sender return value is only a boolean, so ineligible targets and QQ
  or persistence failures are not yet distinguishable to a new API consumer.

## Requirements

- Add `/recall <record_id>` to the terminal command catalog and execute it
  immediately, without a confirmation step, only when a group is selected.
- Parse `record_id` as a positive local integer and resolve it within the currently
  selected group. The terminal must target a currently loaded record, and a record
  number from another group must not be usable.
- Permit recall only when the resolved record is an unrecalled message authored by
  this bot and remains inside QQ's allowed recall window.
- Convert the stored record to the existing QQ recall target so that the QQ DELETE
  request always uses the stored opaque `message_id`, never the local `record_id`.
- Expose the operation through the loopback admin boundary used by the terminal,
  preserving its Bearer authentication and strict request validation.
- Return stable failure outcomes that allow the terminal to distinguish a target
  that is missing or not recallable from a failure while contacting QQ. Do not
  retry an ambiguous DELETE result automatically.
- On success, refresh the active group's history so the recalled message is shown
  using the existing recalled-message presentation. Display a concise terminal
  notice for both success and failure.
- Preserve existing reply, image, sticker, mention, history, and message-sending
  behavior.

## Acceptance Criteria

- [ ] `/recall <record_id>` is discoverable in command completion and help.
- [ ] Submitting a valid recall command performs the action immediately without
      opening a confirmation prompt.
- [ ] A valid recent bot-authored message in the selected group is recalled through
      QQ using its opaque stored `message_id`, then marked recalled locally.
- [ ] After a successful command, refreshed terminal history visibly marks that
      record as recalled.
- [ ] Invalid syntax, no selected group, unknown records, cross-group records,
      user-authored records, already recalled records, and expired records do not
      issue a QQ DELETE request and produce a clear terminal error.
- [ ] An upstream QQ recall failure produces a distinct failure response and is not
      retried automatically.
- [ ] The recall endpoint rejects missing or invalid Bearer authentication and
      malformed request bodies consistently with the existing admin API.
- [ ] Automated tests cover the command catalog and dispatch, client/API contract,
      group scoping, ownership and time-window checks, success refresh, and failure
      mapping; the full relevant test suite passes.

## Out of Scope

- Recalling messages authored by group members or by another bot identity.
- Bulk recall, scheduled recall, or recall by QQ's opaque message ID.
- Retrying a recall whose network outcome is unknown.
- Database schema changes or a web UI.
