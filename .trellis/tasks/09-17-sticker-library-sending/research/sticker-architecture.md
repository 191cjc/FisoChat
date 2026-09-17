# Sticker Architecture Research

## Existing Ownership Boundaries

- The Textual application uses ConsoleClient and accepts only loopback HTTP
  origins. Every management request carries the configured Bearer token
  (src/fisochat/console_client.py:16-74).
- AdminMessageHandler separately enforces loopback source and constant-time
  token comparison before message reads or sends
  (src/fisochat/interfaces/web/admin_messages.py:37-75).
- GroupMessageRepository already supports group-scoped record lookup and image
  URL extraction, so a save request can identify an existing message instead of
  accepting a caller-controlled source URL
  (src/fisochat/database/group_messages.py:377-401).
- ImageScreen already owns attachment navigation and cancellable image-preview
  workers. Its modal bindings have room for a dedicated save action
  (src/fisochat/console.py:198-302).

## Image Safety Evidence

The current preview path provides the correct baseline for backend collection:

- public HTTP/HTTPS only, without URL credentials;
- literal private IP rejection plus resolver-level rejection of private DNS
  results, preventing DNS rebinding;
- no environment proxy, no cookies, no management credentials;
- at most four requests across redirects;
- 10 MB compressed-byte limit and 20-million-pixel limit;
- Pillow format allowlist and bounded first-frame preview decoding.

These rules currently live in console_images.py and raise ConsoleError. Backend
storage must not import a terminal exception type. The reusable downloader,
format inspection, and attachment classification should move to a neutral
service module with a domain-specific image error; console_images.py can
translate that error while retaining its current user messages and preview
behavior.

## QQ Media Contract

The installed qq-botpy 1.2.1 signature is:

    post_group_file(group_openid: str, file_type: int, url: str,
                    srv_send_msg: bool = False)

Its implementation sends JSON to /v2/groups/{group_openid}/files and has no
local path, bytes, multipart, or base64 parameter. The SDK documentation labels
file_type=1 as PNG/JPG. QQ returns file_info, which must then be sent with a
group message of msg_type=7.

QQ therefore needs to fetch each local sticker over HTTPS. Existing
QQMessageSender.send_image_reply already implements upload then message send,
and its shared send path never retries ambiguous failures. A proactive-image
method should reuse this behavior, with the signed URL used only on the wire.
The stored outbound payload must use the stable sticker ID and filename instead
of retaining the expiring signature.

## Storage Model

A filesystem-backed collection is sufficient and directly matches the user's
manual-delete requirement:

- root: data/stickers/ by default;
- filename: lowercase SHA-256 digest plus canonical .png or .jpg extension;
- identity/deduplication: digest of the original validated file bytes;
- source of truth: a fresh directory scan for list/send operations;
- ordering: descending file modification time, then sticker ID;
- accepted entries: regular, non-symlink files whose names and decoded format
  match the storage contract;
- creation: same-directory temporary file, mode 0600, flush/fsync, atomic
  publish, directory mode 0700.

No SQLite metadata or sidecar index is needed. This avoids stale rows after
manual deletion and avoids coupling a non-message collection to the message
schema. Manually renamed or injected files are not an import mechanism and are
ignored unless they exactly satisfy the managed filename and validation
contract.

## HTTP Contracts

Loopback Bearer-authenticated routes:

- POST /internal/stickers
  - input: group_openid, record_id, attachment_index (one-based)
  - output: sticker projection plus duplicate boolean
- GET /internal/stickers
  - output: current global sticker projections
- GET /internal/stickers/{sticker_id}
  - output: bytes for terminal preview
- POST /internal/stickers/{sticker_id}/send
  - input: group_openid
  - output: the normal message_id, sent_at, and recorded fields

Public route:

- GET /stickers/{sticker_id}?expires=UNIX&signature=BASE64URL

The public route accepts no management credential. It validates a bounded
future expiry and an HMAC-SHA256 signature over a domain-separated canonical
string containing the sticker ID and expiry. It then re-resolves the file from
the managed store and returns no-store/nosniff headers. A five-minute lifetime
is enough for the immediate QQ fetch without creating durable public access.

The deployment needs FISOCHAT_STICKER_PUBLIC_BASE_URL and a separate
FISOCHAT_STICKER_SIGNING_SECRET. Both are secret-safe configuration fields:
the base URL must be HTTPS with no user info, query, or fragment; the signing
secret must be excluded from repr and logs. Configuration is all-or-nothing so
a partially configured signing boundary cannot start silently.

## Browser Retirement Impact

Browser and terminal routes are registered separately in app.py, so deleting
the viewer does not require deleting the aiohttp process. Full retirement
includes:

- group_messages.py and test_group_message_viewer.py;
- GroupMessageViewer registration and the root redirect;
- Basic Auth, CSRF, view credentials, and AiQQ viewer aliases;
- --web-only, create_read_only_application, and related CLI paths;
- browser routes from the Nginx template and all viewer documentation.

admin_messages.py currently imports _element_texts and _safe_http_url from the
viewer module. Those neutral display helpers must move to message_display.py
before group_messages.py is deleted. The remaining aiohttp application owns the
loopback terminal API, /health, and the signed public sticker fetch only.

## Test Seams

- Store tests can use temporary directories and generated Pillow PNG/JPEG/GIF
  fixtures to verify validation, digest naming, atomicity, deduplication,
  symlink rejection, and external deletion.
- Downloader tests can retain the current local TestServer plus a mocked public
  resolver, proving redirects and byte limits without outside network access.
- HTTP tests can use aiohttp TestClient with a fake clock, fake downloader, and
  fake sender for auth, source ownership, signatures, and send behavior.
- Sender tests can assert exactly one post_group_file and one
  post_group_message call, stable recorded attachment metadata, and no retry.
- Textual pilot tests can exercise S in ImageScreen and /stickers navigation
  without a real terminal image protocol or QQ connection.

## Conclusion

Keep the task as one integrated change rather than parent/child tasks. Sticker
storage, HTTP composition, terminal UX, sender changes, and browser retirement
share app.py, config.py, README.md, and standalone integration tests; splitting
them would create artificial intermediate states that are not deployable.
