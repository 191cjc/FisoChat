# Implementation Plan

## 1. Establish Shared Image Contracts

- Extract attachment classification, protected URL resolution, bounded download,
  and decoded image inspection from console_images.py into a neutral service.
- Keep ConsoleError translation and preview rendering in the console layer so
  existing messages and tests remain compatible.
- Add PNG/JPEG-only sticker validation while preserving the broader preview
  format allowlist.
- Cover DNS/private-address rejection, redirects, timeout, byte/pixel limits,
  malformed images, PNG/JPEG acceptance, and GIF/WebP sticker rejection.

Rollback point: existing console image tests must pass before adding storage or
changing routes.

## 2. Implement the Filesystem StickerStore

- Add typed sticker metadata and a store rooted at the configured directory.
- Create the root with private permissions and implement atomic mode-0600
  content-addressed writes.
- Deduplicate by SHA-256 bytes under a mutation lock.
- Scan fresh for list and lookup; validate name, regular-file status, symlink
  status, size, digest, extension, and image format.
- Treat manual deletion and deletion races as normal not-found outcomes.
- Add focused temporary-directory tests for restart persistence, concurrent
  duplicate saves, cleanup after failure, invalid injected entries, symlinks,
  and manual deletion.

Rollback point: the store module remains independent from HTTP and QQ and can be
removed without affecting the current app.

## 3. Add Configuration and Signed Retrieval

- Remove browser username/password fields and aliases from AppConfig.
- Require the terminal management token for the terminal-only product.
- Add sticker directory, validated HTTPS public base URL, and repr-safe signing
  secret configuration.
- Add five-minute HMAC URL creation and strict constant-time validation.
- Add the public byte route with no-store/nosniff headers and no listing.
- Update .env.example with secret generation and public URL examples.
- Test malformed URLs, partial/missing config, secret redaction, expiry bounds,
  tampering, unknown IDs, traversal, symlinks, and valid retrieval.

Rollback point: configuration and signed-route tests must pass before wiring the
route into the recorder lifecycle.

## 4. Add Authenticated Sticker APIs

- Extend the admin repository protocol with group-scoped record lookup.
- Add save, list, internal preview, and send handlers under /internal/stickers.
- Reuse the existing loopback/Bearer check and the existing terminal send lock.
- Resolve save sources from incoming unrecalled records and the one-based
  attachment index; reject arbitrary request fields.
- Return stable error codes and safe Chinese messages for source, validation,
  storage, configuration, missing-file, and QQ failures.
- Add ConsoleClient methods for JSON operations and bounded authenticated image
  bytes; retain the no-auto-retry wording for all send POST failures.

## 5. Add Proactive QQ Image Sending

- Extend GroupMessageSender with send_proactive_image.
- Reuse QQMessageSender's file upload and _send_and_record path.
- Store stable sticker metadata without signed URL/query data.
- Test exactly one upload and one message call, missing file_info, QQ rejection,
  ambiguous exception propagation, and database-record failure.

Rollback point: sender and admin API tests must prove no retry before terminal
send controls are enabled.

## 6. Add Terminal Save and Picker UX

- Add S to ImageScreen with a cancellable exclusive save worker and visible
  saved/duplicate/error status.
- Hide or reject save for recalled and bot-authored messages, while relying on
  backend validation as the authority.
- Add /stickers to command completion and help.
- Implement a responsive temporary StickerPicker with keyboard list navigation,
  authenticated preview loading, Enter-to-send, Escape-to-cancel, empty state,
  and in-flight state protection.
- Preserve active group, drafts, cursor, scroll, replies, aliases, selection,
  and copy behavior across save/picker operations.
- Refresh history after confirmed send; retain explicit unknown-outcome guidance
  and never auto-retry.
- Add Textual pilot tests for manual-only save, image navigation, duplicate
  notice, empty library, preview switching, cross-group use, send success,
  deletion race, cancellation, and ambiguous failure.

## 7. Retire the Browser Product Surface

- Move _element_texts and _safe_http_url to a neutral display helper.
- Delete group_messages.py and test_group_message_viewer.py.
- Remove viewer route registration, root redirect, Basic Auth/CSRF configuration,
  read-only application construction, --web-only CLI routing, and tests.
- Update project/package descriptions and remove “continue on web” terminal
  messages.
- Narrow Nginx to health plus the signed sticker path; keep /internal routes
  inaccessible from the public proxy.
- Add route-absence tests for / and /group-messages while preserving terminal
  API and health behavior.

## 8. Documentation and Deployment Review

- Rewrite README setup, terminal image/sticker usage, configuration, HTTP
  boundaries, Nginx deployment, validation, and rollback sections.
- Document data/stickers permissions, manual deletion, PNG/JPEG limit, digest
  deduplication, signed URL lifetime, and secret generation.
- Update MIGRATION.md or historical audit references only where they describe
  current browser availability; do not rewrite historical findings.
- Confirm deploy/fisochat.service still grants only the required data write path.

## 9. Validation Gate

Run focused tests first:

    uv run python -m unittest tests.test_console_images tests.test_stickers -v
    uv run python -m unittest tests.test_admin_messages tests.test_standalone_app -v
    uv run python -m unittest tests.test_qq_sender -v
    uv run python -m unittest tests.test_console tests.test_console_commands -v

Then run full project checks:

    uv run python -m unittest discover -s tests -v
    uv run python -m compileall -q src tests
    uv lock --check
    git diff --check
    uv build

Review the final route table and grep for group-messages, FISOCHAT_VIEW_*,
AIQQ_GROUP_MESSAGE_VIEW_*, --web-only, browser-viewer text, persisted
signature/expires query values, and accidental public /internal proxying.

Do not use the production database as a fixture, restart the live service,
reload Nginx, fetch external private resources, or send a real QQ message during
automated validation.

## Risky Files and Review Focus

- src/fisochat/services/images.py: SSRF, DNS rebinding, redirect and resource
  limits must remain at least as strict as the existing preview path.
- src/fisochat/services/stickers.py: path containment, symlinks, atomic writes,
  digest/format agreement, deletion races, HMAC construction, and secret safety.
- src/fisochat/interfaces/web/admin_messages.py and app.py: loopback auth versus
  the one intentionally public signed route; send-lock and error semantics.
- src/fisochat/services/qq/sender.py: exactly-once upload/send attempts and no
  signed URL persistence.
- src/fisochat/console.py and console_client.py: modal lifecycle, cancellation,
  active-group capture, binary preview, and unknown-outcome wording.
- src/fisochat/config.py, deploy/nginx-fisochat-locations.conf, and README.md:
  breaking viewer removal, required deployment settings, and no public internal
  API exposure.
