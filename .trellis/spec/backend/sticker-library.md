# Sticker Library Contracts

## Scenario: Terminal Sticker Collection and Sending

### 1. Scope / Trigger

Use these contracts whenever code changes received-image collection, the global
sticker directory, terminal sticker APIs, signed public retrieval, or QQ sticker
sending. The feature crosses recorded messages, network image validation,
filesystem state, HTTP, the terminal, and QQ delivery.

The library is intentionally global and filesystem-backed. Operators may delete
managed files directly, so each list, preview, public fetch, and send must resolve
current disk state instead of trusting an index or a previous picker result.

### 2. Signatures

Authenticated loopback API:

```text
POST /internal/stickers
GET  /internal/stickers
GET  /internal/stickers/{sticker_id}
POST /internal/stickers/{sticker_id}/send
```

Public QQ retrieval API:

```text
GET /stickers/{sticker_id}?expires=<unix-seconds>&signature=<base64url-hmac>
```

Core Python boundaries:

```python
await StickerStore.save(data: bytes) -> tuple[Sticker, bool]
await StickerStore.list() -> tuple[Sticker, ...]
await StickerStore.get(sticker_id: str) -> StoredSticker
StickerSigner.signed_url(sticker_id: str) -> str
StickerSigner.validate(sticker_id: str, expires: str, signature: str) -> bool
await GroupMessageSender.send_proactive_image(...)
```

### 3. Contracts

Save request:

```json
{"group_openid": "...", "record_id": 123, "attachment_index": 1}
```

- Fields are exact; arbitrary URLs are never accepted.
- `attachment_index` is one-based and selects the same normalized image list as
  the terminal preview.
- The record must belong to the named group and be an incoming, unrecalled QQ
  gateway record.
- Success returns `ok`, `duplicate`, and a sticker projection.

Sticker projection fields are `id`, `filename`, `content_type`, `size`, and
`saved_at`. The ID is the lowercase SHA-256 digest of the original bytes. The
only canonical filenames are `<digest>.png` and `<digest>.jpg`.

Send request:

```json
{"group_openid": "..."}
```

The sender uploads one five-minute signed HTTPS URL with `post_group_file`, then
sends one `msg_type=7` group message. The stored outbound attachment contains
only stable `sticker_id`, `filename`, and `content_type`; it must not contain the
signed URL, signature, expiry, local path, or signing secret. Ambiguous failures
are returned without automatic retry.

Required service environment:

```text
FISOCHAT_ADMIN_TOKEN or FISOCHAT_ADMIN_TOKEN_FILE
FISOCHAT_STICKER_DIR=data/stickers
FISOCHAT_STICKER_PUBLIC_BASE_URL=https://public.example/fisochat
FISOCHAT_STICKER_SIGNING_SECRET=<at least 32 UTF-8 bytes>
```

The public base URL must be HTTPS, have a host, contain no credentials, query, or
fragment, and reject localhost and non-global literal IP addresses. Secrets are
excluded from representations and logs.

Storage accepts only validated PNG/JPEG bytes up to 10 MB and 20 million pixels.
Create the root as mode `0700`, publish files as mode `0600`, and fsync before and
after atomic publication. Reject symlinked path components and pin the initialized
root directory identity. All child opens and replacements use that directory
descriptor plus no-follow behavior.

The public signature is base64url HMAC-SHA256 over:

```text
fisochat-sticker-v1\n<sticker-id>\n<expires>
```

The public route accepts exactly one `expires` and one `signature` value, checks
the five-minute future bound with the documented clock tolerance, and fails
closed with 404 for every invalid or unavailable object.

### 4. Validation & Error Matrix

| Condition | API result |
| --- | --- |
| Missing/wrong Bearer token or non-loopback internal request | `401` / `403` |
| Unknown request fields, invalid group/record/index | `400` |
| Missing, bot-authored, recalled, or wrong-event source record | `409 invalid_sticker_source` |
| Malformed, oversized, over-pixel, GIF, or WebP save data | `422` with a stable image code |
| Expired/unavailable source download | `502` with no source URL disclosure |
| Sticker deleted before preview/send | `404 sticker_not_found` |
| Sticker directory unavailable or replaced | `500` storage error, never a QQ error |
| QQ rejection or ambiguous upload/send outcome | `502 qq_send_failed`, no retry |
| Invalid, duplicate, expired, or tampered public query | `404` and no bytes |

### 5. Good / Base / Bad Cases

- Good: Saving the same valid PNG through two received records produces one
  digest file and returns `duplicate=true` on the second save.
- Base: Manually deleting a digest file removes it from the next list and causes
  a stale preview/send to return `sticker_not_found` without retry.
- Bad: Do not accept a terminal-supplied source URL, follow a symlinked sticker
  entry, retain an oversized final file, or persist a signed URL in message JSON.

### 6. Tests Required

- Store unit tests assert PNG/JPEG acceptance, GIF/WebP rejection, byte/pixel
  limits, atomic deduplication, private modes, restart persistence, and no
  residual managed or temporary file after failure.
- Filesystem tests assert invalid names, digest/extension mismatch, symlinked
  files, symlinked parents, runtime root replacement, and manual deletion.
- HTTP tests assert exact request/query keys, duplicate query rejection,
  authentication, source ownership, expiry/tamper handling, safe headers, and
  current-disk lookup.
- Sender tests assert exactly one upload and one message call, no retries, and no
  signature or URL in the persisted payload.
- Terminal tests assert that explicit lowercase `s` and `Shift+S` each trigger
  one save, alongside duplicate feedback, global cross-group selection,
  deletion refresh, draft preservation, and ambiguous send warnings.
- Full project tests, compile, lock check, diff check, and package build must pass.

### 7. Wrong vs Correct

#### Wrong

```python
# A path join still follows a replaced parent directory, and validation after
# publication can leave an invalid managed file behind.
path = root / filename
path.write_bytes(data)
validate(data)
```

#### Correct

```python
if not 0 < len(data) <= MAX_IMAGE_BYTES:
    raise StickerError("too_large", "...")
metadata = inspect_sticker(data)
root_fd = open_and_verify_initialized_root()
publish_atomically_relative_to(root_fd, digest + metadata.extension, data)
```

Validate bytes before publication, bind operations to the initialized directory,
and re-read the managed entry before returning success.
