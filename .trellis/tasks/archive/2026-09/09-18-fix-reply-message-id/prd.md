# Fix QQ Reply Message ID Validation

## Goal

Make terminal `/reply <record_id>` accept the opaque message IDs actually
issued by QQ, so selecting a valid recent incoming message can reach QQ's
native reply API instead of failing local validation. Confirm that the existing
JPEG sticker contract remains working.

## Background

- The terminal correctly resolves the displayed local record number to the
  stored QQ `message_id`; it does not send the `#<record_id>` value to QQ.
- Production incoming message IDs are currently 137 characters and contain
  punctuation such as `.` and sometimes `!`.
- `src/fisochat/interfaces/web/admin_messages.py` currently validates reply IDs
  with `^[A-Za-z0-9_-]{1,256}$`, so production IDs are rejected before the
  repository lookup or QQ request.
- The same restrictive expression is also reused for member OpenIDs. Reply
  message validation must be separated so mention-target validation is not
  unintentionally weakened.
- The repository currently permits reply context only for unrecalled messages
  that explicitly mention the bot, are under five minutes old, and still have
  one of reply sequence numbers 1 through 5 available. This task intentionally
  expands the source set to any incoming user message that satisfies the same
  group, recall, time, and sequence constraints.
- The installed QQ SDK documents a five-minute lifetime and unique
  `msg_id + msg_seq` requirement; its method documentation does not state that
  the source must explicitly mention the bot.
- Sticker storage already accepts validated JPEG bytes and canonicalizes them
  to `.jpg`; focused tests already cover JPEG inspection and persistence.

## Requirements

### R1. Opaque QQ Reply IDs

- Treat a QQ message ID as an opaque value rather than assuming it uses the
  OpenID character set.
- Accept persisted production-shaped IDs containing `.` and `!`, preserve them
  byte-for-byte through the internal request, repository lookup, and QQ sender.
- Continue rejecting missing, non-string, over-limit, whitespace-bearing, or
  control-character-bearing reply IDs before repository access.
- Keep group and member OpenID validation unchanged.

### R2. Reply Context Safety

- A selected source must belong to the active group, be an incoming unrecalled
  gateway message, be less than five minutes old, and have an unused sequence
  number from 1 through 5.
- Both ordinary group messages and messages that explicitly @ the bot are valid
  sources; an explicit bot mention is no longer required.
- A local validation failure must remain distinguishable from an unavailable or
  expired reply context and from a QQ send failure.
- Ambiguous QQ send outcomes must not be retried automatically.

### R3. JPEG Verification

- Preserve the existing PNG/JPEG-only sticker policy, including `.jpg` and
  `.jpeg` source names whose decoded bytes are valid JPEG.
- Run the focused JPEG storage tests and full regression suite. No sticker code
  change is required unless those checks expose a reproducible defect.

### R4. Deployment

- After automated checks pass, restart `fisochat.service` and verify that it is
  active and connected.
- Do not initiate a real QQ reply or sticker send automatically; live delivery
  remains an operator action.

## Acceptance Criteria

- [x] AC1: A production-shaped reply ID containing `.` and `!` passes internal
      validation unchanged and is used for the exact repository lookup.
- [x] AC2: Empty, non-string, too-long, whitespace-bearing, and control-bearing
      reply IDs return `400 invalid_reply_context` without calling the sender.
- [x] AC3: Group and member OpenID validation retains its existing restrictive
      character rules.
- [x] AC4: Valid context still enforces active-group ownership, no recall,
      five-minute expiry, and reply sequence uniqueness from 1 through 5, while
      allowing an ordinary incoming message that did not @ the bot.
- [x] AC5: Focused reply tests, JPEG sticker tests, the full suite, compile,
      lock, diff, and build checks pass.
- [x] AC6: The production service restarts successfully and reports an active
      QQ connection without the assistant sending a live QQ message.

## Out of Scope

- Replying to bot-authored, recalled, cross-group, older-than-five-minute, or
  sequence-exhausted messages.
- Simulated quote text for messages QQ no longer accepts as native replies.
- GIF/WebP sticker storage, arbitrary local-file import, or automatic image
  collection.
- Automatic live QQ reply/sticker sends during verification.
