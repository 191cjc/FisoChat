# Design: Cross-Group Terminal Mention Notifications

## Boundaries

The feature spans persisted gateway records, the loopback management API,
`ConsoleClient`, and Textual app state. It adds no database schema, public
route, environment setting, or QQ send path.

```text
QQ gateway -> group_messages -> global cursor feed -> ConsoleClient
           -> FisoChatApp in-memory cursor -> Textual popup
```

## Shared Mention Classifier

Place one classifier beside the existing mention display helpers. It accepts a
stored event type and payload and returns true for
`GROUP_AT_MESSAGE_CREATE` or a mapping in `payload["mentions"]` whose
`is_you` is exactly `True`. API and tests reuse this classifier; terminal code
never inspects raw QQ payloads.

## Repository Scan

Add a repository method that returns up to 100 stored records across all groups
where `record_id > after_record_id`, ordered ascending. It uses the primary-key
cursor and existing row decoder. Filtering remains in the API projection so
malformed JSON is handled by the existing payload decoder and SQLite JSON1 is
not required.

The page includes ordinary and bot records. Advancing across every scanned row
is intentional: otherwise long spans without @ messages would be rescanned on
every two-second poll.

## Loopback API

Add a Bearer-authenticated, loopback-only endpoint:

```text
GET /internal/group-mention-alerts?after=<0..2^63-1>&limit=<1..100>
```

Response:

```json
{
  "mentions": [
    {
      "record_id": 123,
      "group_openid": "...",
      "username": "...",
      "content": "readable bounded text",
      "sent_at": "..."
    }
  ],
  "next_after": 456,
  "has_more": false
}
```

`next_after` is the last scanned record ID, or the supplied cursor for an empty
page. `has_more` is true when the scan filled the requested page. The alert
list includes only incoming, unrecalled records that the shared classifier
identifies as mentioning this bot. Content uses the existing readable mention
projection and is bounded before crossing the API.

Invalid cursor/limit values return `400 invalid_cursor`. Existing authentication
and no-store response behavior apply. No sender dependency is invoked.

## Terminal State

`ConsoleClient` exposes the alert feed without raw payloads. `FisoChatApp`
stores one optional global `_mention_cursor`.

On the first successful group-summary refresh, set the cursor to the greatest
`latest_record_id` (or zero) and emit nothing. On later refreshes, consume a
bounded number of feed pages. Advance the in-memory cursor before presenting
each returned batch so a rendering problem cannot replay the same alerts.
Unconsumed pages remain available for the next two-second refresh.

For every alert call `App.notify` with a static title, `markup=False`,
information severity, and an eight-second timeout. The message includes a
single-line bounded group ID, sender, `#record_id`, and content excerpt. Do not
call `bell`, select a group, mutate the composer, or move the message log.

## Compatibility and Failure Behavior

- Active-group message rendering continues through the existing per-group
  endpoint; alert delivery is independent and may precede or follow it.
- A loopback/feed failure follows existing refresh error handling and retains
  the last successful cursor. Recovery resumes from that cursor.
- Initial history, `/older`, group switching, and redrawing cannot alert because
  they do not consume the global feed.
- Multiple terminal processes maintain independent session cursors and may each
  show the same live alert; no persistent unread state is introduced.
- There is no automatic QQ message, reply, @, retry, or outbound record.

## Rollback

Remove the route, repository scan, client method, and terminal cursor/popup
logic. No data or configuration migration is required.
