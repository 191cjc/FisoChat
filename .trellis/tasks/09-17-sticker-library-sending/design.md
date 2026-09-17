# Technical Design

## Scope and Boundaries

This change adds a backend-owned filesystem sticker library, authenticated
terminal APIs, a signed public retrieval route, proactive QQ image sending, and
Textual save/picker interactions. It also deletes the browser viewer and
read-only web mode.

The message database schema does not change. The terminal never reads the
sticker directory directly, never receives the signing secret, and never asks
the backend to fetch an arbitrary URL.

## Architecture

    recorded received message
      -> terminal /image preview
      -> S with group + record + attachment index
      -> loopback authenticated API
      -> repository resolves attachment URL
      -> safe downloader validates PNG/JPEG
      -> atomic content-addressed file in data/stickers

    /stickers
      -> loopback list + preview API
      -> operator selects one item
      -> loopback send API with active group
      -> five-minute signed HTTPS URL
      -> QQ post_group_file
      -> QQ post_group_message (msg_type=7)
      -> outbound message record with stable sticker metadata

### Image Service

Move public URL validation, protected DNS resolution, redirect handling, byte
limits, and format inspection from console_images.py into a neutral image
service. It exposes:

- normalized image-attachment extraction used by both terminal and backend;
- bounded public download returning original bytes and inspected metadata;
- PNG/JPEG storage validation;
- preview decoding used by the existing terminal image screen.

The service raises an image-domain error. Console adapters translate it to
ConsoleError; HTTP adapters map known validation failures to stable JSON error
codes without exposing URLs or internal paths.

The preview format set remains unchanged. Sticker storage has a narrower
PNG/JPEG allowlist and does not convert GIF/WebP or strip metadata, so the bytes
hashed are the bytes stored and later served.

### StickerStore

StickerStore owns one configured directory and an async mutation lock.

On initialization it creates the directory with mode 0700. Each successful save:

1. Validates the downloaded bytes and canonicalizes the format to .png or .jpg.
2. Computes the lowercase SHA-256 digest over the original bytes.
3. Treats an existing valid digest file as a duplicate.
4. Writes a random same-directory temporary file with mode 0600.
5. Flushes and fsyncs the file, atomically publishes the digest filename, and
   cleans up the temporary file on every failure path.

List and lookup operations scan the directory rather than reading an index.
They accept only names matching a 64-character lowercase hex digest plus the
canonical extension, reject symlinks/non-regular files, verify size bounds, and
ensure the bytes still hash to the filename. Items are ordered by descending
mtime and then ID. Invalid unmanaged files are ignored and logged only by error
category, never by content.

Manual deletion therefore needs no database reconciliation. A file deleted
between list and preview/send becomes a not-found result. The API refreshes the
picker after that result and does not reuse stale bytes.

## API Contracts

All /internal routes reuse AdminMessageHandler's exact loopback and constant-time
Bearer-token checks.

### Save

POST /internal/stickers

Request:

    {"group_openid": "...", "record_id": 123, "attachment_index": 1}

The handler validates all fields, loads that record within the named group,
requires an incoming non-bot unrecalled gateway record, extracts the same
ordered image attachment list shown by /image, and selects the one-based index.
The source URL is never accepted from the request body.

Response:

    {"ok": true, "duplicate": false, "sticker": { ... }}

Duplicate saves return HTTP 200 with duplicate=true. Invalid source identity,
format, download, and storage failures receive distinct 4xx/5xx error codes and
safe Chinese messages.

### List and Preview

GET /internal/stickers returns:

    {"stickers": [
      {"id": "<sha256>", "filename": "<sha256>.png",
       "content_type": "image/png", "size": 1234,
       "saved_at": "<UTC ISO-8601>"}
    ]}

GET /internal/stickers/{id} returns the selected bytes with the validated
content type, Cache-Control: no-store, and X-Content-Type-Options: nosniff. It
exists only on loopback with Bearer authentication and supports terminal
preview, not public QQ retrieval.

### Send

POST /internal/stickers/{id}/send

Request:

    {"group_openid": "..."}

The handler validates the active group, resolves the file fresh, creates a
signed URL, and invokes GroupMessageSender.send_proactive_image while holding
the same send lock used for terminal text sends. Success uses the existing
message response projection. A missing file is a 404; an unconfigured or invalid
public origin is a 503; QQ rejection or ambiguous failure is a 502 and is never
retried.

### Public Retrieval

GET /stickers/{id}?expires=<unix-seconds>&signature=<base64url-hmac>

The signer uses HMAC-SHA256 with a separate configured secret and this canonical
message:

    fisochat-sticker-v1\n<sticker-id>\n<expires>

The URL lifetime is five minutes. The handler requires an expiry later than the
current time and no farther than five minutes plus a small processing tolerance,
then compares the expected signature in constant time. It accepts only the
documented query keys and ID syntax. It resolves the store entry again after
signature validation, serves no directory index, and returns no-store/nosniff
headers.

## QQ Sender Contract

Add send_proactive_image to GroupMessageSender and QQMessageSender. It:

1. Calls post_group_file once with file_type=1, the signed HTTPS URL, and
   srv_send_msg=False.
2. Requires a non-empty file_info.
3. Calls the existing _send_and_record once with msg_type=7 and no reply ID.

There is no retry around either network operation. The outbound payload records
sticker_id, canonical filename, and MIME type, but never the signed URL,
signature, local path, or secret. If QQ confirms delivery but database recording
fails, the existing recorded=false behavior remains.

## Terminal Interaction

### Saving from ImageScreen

ImageScreen receives an async save callback in addition to the existing message
and attachment state. Binding S starts one exclusive save worker for the current
attachment. The status line displays saving, saved, already-saved, or actionable
error state. Left/right navigation is disabled only while that save request is
in flight; closing the modal cancels the client request without deleting a
completed backend file.

Only incoming, unrecalled messages expose the save hint. The backend repeats the
eligibility check, so stale terminal state cannot bypass the rule.

### Sticker Picker

The /stickers command opens a temporary StickerPicker modal. A ListView provides
stable keyboard navigation, while an adjacent or stacked image area previews
the highlighted item through the authenticated internal byte endpoint. The
layout adapts to narrow terminals using existing fixed/max dimensions rather
than viewport-scaled text.

Enter sends the highlighted sticker to the group that was active when the send
began. Escape closes without sending. While sending, controls are disabled and
the group cannot be switched. A successful send closes the picker, reports the
result, and refreshes history. An unknown outcome keeps the picker open and
explicitly warns the operator to inspect history rather than retrying.

The command list, help screen, and README document /stickers and S. There is no
delete, rename, import, tag, or search control.

## Browser Retirement

- Delete group_messages.py and test_group_message_viewer.py.
- Move neutral message projection helpers needed by admin_messages.py into
  message_display.py.
- Remove GroupMessageViewer, /group-messages, the root redirect, Basic Auth,
  CSRF, view_username/view_password, legacy viewer aliases, --web-only,
  create_read_only_application, and associated tests/help.
- Keep the current aiohttp package and create_web_application name because it
  still composes HTTP management, health, and signed retrieval routes; these are
  transport details rather than a browser UI.
- Remove viewer locations from Nginx. Keep /fisochat/health and add only the
  exact /fisochat/stickers/ prefix proxy needed for signed retrieval; all other
  /fisochat/ paths return 404.
- Remove every README instruction that presents a webpage as a product surface,
  including the “continue on web” terminal message.

## Configuration

AppConfig removes browser credentials and read-only mode. Normal service startup
requires:

- QQ_BOT_APPID and QQ_BOT_SECRET;
- FISOCHAT_ADMIN_TOKEN or its 0600 token file, because the terminal is the only
  operator interface;
- FISOCHAT_STICKER_DIR, default data/stickers;
- FISOCHAT_STICKER_PUBLIC_BASE_URL, an HTTPS URL such as
  https://www.firesoul.cn/fisochat with no user info, query, or fragment;
- FISOCHAT_STICKER_SIGNING_SECRET, a separate high-entropy value excluded from
  repr and logs.

The public base and signing secret are required together and fail configuration
validation before starting the QQ client. The deployment guide includes
generation and rollout instructions. The existing host/port names remain
because they still configure the loopback HTTP service and health endpoint.

## Compatibility and Migration

- No SQLite schema or message data migration occurs.
- Existing image previews retain their accepted formats and safety limits.
- Existing text/reply/mention/send contracts and management endpoint stay
  unchanged.
- /, /group-messages, browser credentials, and --web-only are intentional
  removals and return an error/404 rather than a compatibility redirect.
- Existing files under data/ are untouched. The sticker directory is created on
  first initialization.

## Failure Handling and Observability

Logs use event names and error types only. They may include a sticker ID prefix,
format, byte count, or route status, but never source URLs, signed URLs,
signatures, secrets, raw image bytes, group IDs, member IDs, or message payloads.

Download/validation failure leaves no file. Send failure leaves the saved file
unchanged. Manual deletion and concurrent reads resolve to not-found without
recreation. Startup fails before QQ login when required signing configuration or
directory initialization is invalid.

## Rollout and Rollback

Rollout is not automated by the test task:

1. Generate the signing secret and configure the public base URL.
2. Install and validate the narrowed Nginx locations.
3. Deploy code and perform a controlled service restart.
4. Verify /health, rejected unsigned retrieval, one terminal save, and one
   operator-approved send.

The Nginx signed route may be installed before the code; it returns 404 until
the new service is active. To roll back, restore the prior code and Nginx
template. The old version ignores data/stickers, and no database restoration is
required. Retaining or manually removing sticker files is an operator choice.

## Trade-offs

Filesystem scanning avoids index drift and supports manual deletion, at the
cost of linear listing work. That is appropriate for an operator-sized sticker
library and avoids unnecessary database schema. PNG/JPEG-only storage matches
the documented QQ contract but deliberately excludes animated stickers.
