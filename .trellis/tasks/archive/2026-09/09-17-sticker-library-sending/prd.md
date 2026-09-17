# Local Sticker Library and Sending

## Goal

Let the operator explicitly save useful received chat images into a durable,
deployment-wide sticker library and send them from the terminal to the active QQ
group, while retiring the browser user interface.

## Background

- FisoChat already records image attachments and previews them in the Textual
  terminal through the \`/image\` command.
- The backend owns QQ credentials, the SQLite repository, sending, and writable
  deployment storage. The terminal is a loopback API client.
- QQ group media upload accepts a public URL rather than a local path or base64
  body, so a durable local sticker needs a narrowly scoped HTTPS retrieval URL
  when it is sent.
- The operator chose a global library, content deduplication, manual collection,
  manual file deletion, PNG/JPEG-only stickers, and complete removal of the
  browser viewer and composer.

## Requirements

### R1. Manual Collection

- Opening an eligible received image with \`/image\` and pressing \`S\` saves the
  currently displayed attachment.
- Only an explicit save action may create a sticker. Receiving, listing, or
  previewing an image must not save it automatically.
- The backend must resolve the source from the recorded group, record ID, and
  attachment index; it must not trust an arbitrary URL supplied by the terminal.
- Recalled messages, bot-authored records, missing attachments, expired URLs,
  invalid images, and unsupported formats must be rejected with actionable
  terminal feedback.

### R2. Durable Global Storage

- Store stickers in a backend-managed \`data/stickers/\` directory that survives
  service and terminal restarts.
- The library is global to the deployment. A sticker saved from one group is
  available while any other group is active.
- Accept only validated PNG and JPEG data, with the existing 10 MB and
  20-million-pixel limits.
- Deduplicate by a cryptographic digest of the downloaded file bytes. Saving the
  same content through the same or a different source URL returns the existing
  item and does not create another file or picker entry.
- Writes must be atomic and must not leave a partial sticker after cancellation,
  validation failure, download failure, or concurrent duplicate saves.

### R3. Terminal Browsing and Sending

- \`/stickers\` opens a temporary terminal picker for the global collection.
- The picker shows the selected sticker preview and enough stable identity and
  date information to distinguish entries.
- Enter sends the selected sticker to the currently active group; Escape closes
  the picker without sending. Sending is unavailable when no group is active.
- A selected sticker is uploaded through the existing QQ group rich-media flow
  and recorded as an outbound image without persisting its signed download URL.
- Ambiguous QQ outcomes must never be retried automatically.

### R4. Manual Cleanup

- The terminal provides no delete or rename action.
- Operators remove unwanted files manually from \`data/stickers/\`.
- Each list or send operation reconciles with the directory so manually deleted,
  invalidly named, non-regular, or symlinked entries do not remain usable or
  crash the application.

### R5. Signed HTTPS Retrieval

- When sending, generate a short-lived, signed, non-enumerable HTTPS URL for the
  selected local file so QQ can fetch it.
- Validate the signature, expiry, sticker identity, and on-disk file before
  serving bytes. Expired, malformed, missing, or tampered requests must fail
  closed.
- Do not expose a directory listing, a permanent unauthenticated asset URL, the
  local file path, the management token, or the signing secret.
- Public base URL and signing-key configuration must be validated and secrets
  must never be logged or included in object representations.

### R6. Terminal-Only Product

- Delete the browser message viewer and browser composer implementation, their
  tests, \`/group-messages\`, the root redirect, Basic Auth/CSRF configuration
  and compatibility aliases, public Nginx page routes, the read-only web mode,
  and browser-viewer documentation.
- Retain the loopback Bearer-authenticated management API used by the terminal,
  the operational health endpoint, and the signed sticker download endpoint.
- Update remaining product descriptions and help text so they no longer direct
  users to the retired webpage.

### R7. Compatibility and Errors

- Preserve existing text sending, replies, mentions, group switching, history
  selection/copying, image preview, database migration, health, and command-line
  sending behavior.
- Saving, listing, previewing, and sending failures must be distinguishable and
  must not discard terminal drafts, change the active group, or create a false
  success record.

## Acceptance Criteria

- [ ] AC1: Pressing \`S\` on an eligible received PNG/JPEG preview creates one
      persistent file in \`data/stickers/\`; no passive workflow creates files.
- [ ] AC2: GIF, WebP, malformed, oversized, over-pixel, recalled, bot-authored,
      unavailable, and non-image sources are rejected without a partial file.
- [ ] AC3: Re-saving byte-identical content reports that it already exists and
      leaves both the file count and picker count unchanged.
- [ ] AC4: \`/stickers\` lists the global library, previews selection, and sends
      the chosen item to the active group.
- [ ] AC5: A sticker saved from one group can be sent to another group without a
      group-specific copy.
- [ ] AC6: A manually deleted file disappears from subsequent picker results;
      a deletion race produces a clear error rather than a crash or wrong send.
- [ ] AC7: Valid unexpired signed URLs return only their selected PNG/JPEG;
      invalid signatures, expired tokens, traversal attempts, symlinks, and
      unknown IDs do not return file bytes.
- [ ] AC8: QQ media upload and message delivery occur once per send action, and
      ambiguous failures are reported without retrying.
- [ ] AC9: Browser-only code, routes, credentials, deployment entries, tests,
      and documentation are gone; the loopback terminal API and health endpoint
      remain operational.
- [ ] AC10: Existing automated tests plus focused storage, signing, HTTP,
      sender, and terminal interaction tests pass.

## Out of Scope

- Automatic collection of incoming images.
- Animated GIF/WebP or other sticker formats; those formats keep their existing
  preview behavior but cannot be saved as stickers.
- Per-group libraries, tags, search, user-defined names, rename, or
  in-application deletion.
- Importing arbitrary local files or arbitrary URLs into the library.
- Permanent public sticker hosting or a browser-based sticker interface.
- Automated production restart, live Nginx reload, or a real QQ send during
  test validation.

## Technical Constraints

- Existing image downloads reject private-network targets and DNS rebinding,
  use no credentials or proxy environment, limit redirects, enforce 10 MB and
  20 million pixels, and decode in memory
  (\`src/fisochat/console_images.py\`).
- The installed \`qq-botpy\` method is
  \`post_group_file(group_openid, file_type, url, srv_send_msg=False)\`; group
  image uploads are documented as PNG/JPG and do not accept local bytes
  (\`src/fisochat/services/qq/sender.py\`).
- The systemd sandbox permits writes below \`/home/ubuntu/FisoChat/data\`.
- The Nginx template currently exposes the browser viewer and health route; it
  must be narrowed to health and the signed sticker path.
