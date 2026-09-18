# Reply ID Validation Evidence

## Production Evidence

- Recent persisted incoming QQ `message_id` values are 137 characters.
- They contain `.` and, for some messages, `!`.
- Every sampled persisted payload's `id` exactly matches the repository
  `message_id`, confirming that `d.id` is the value carried through replies.
- The gateway's outer event ID is a different value and commonly contains `:`;
  it must not replace the message ID.

## Root Cause

`src/fisochat/interfaces/web/admin_messages.py` uses
`^[A-Za-z0-9_-]{1,256}$` for `reply_to_message_id`. Production IDs therefore
fail with `400 invalid_reply_context` before repository lookup. The terminal
itself correctly maps a displayed record number to the stored message ID.

The same regular expression is also used to validate mention-target member
OpenIDs. Split opaque message-ID validation from OpenID validation so fixing
replies does not broaden mention targets.

## Reply Context

The installed `qq-botpy` `post_group_message` documentation requires reply
messages to use a source `msg_id`, a unique `msg_seq`, and a source no older
than five minutes. It does not document an explicit-mention requirement.

The repository uses parameterized SQL for exact message-ID lookup. A reply ID
therefore needs bounded opaque-string validation, not an OpenID alphabet.

## JPEG Evidence

- `.trellis/spec/backend/sticker-library.md` defines validated PNG/JPEG as the
  only stored sticker formats.
- `inspect_sticker` recognizes JPEG bytes and canonicalizes the extension to
  `.jpg` and content type to `image/jpeg`.
- `tests/test_stickers.py` already covers JPEG inspection, save, list, and get.
- Verification should run those tests; sticker code changes are conditional on
  a reproducible failure.
