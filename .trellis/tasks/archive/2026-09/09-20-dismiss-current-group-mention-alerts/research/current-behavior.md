# Current Mention-Alert Behavior

- `FisoChatApp._refresh_mention_alerts()` validates a page, advances
  `_mention_cursor`, deduplicates record IDs within the page, and then calls
  `App.notify()` unconditionally for each accepted alert.
- `FisoChatApp._select_group()` changes `selected_group` and redraws messages,
  but does not alter Textual notifications.
- The application has no other `notify()` call sites, although Textual's
  notification collection is application-wide.
- Textual 6.12 `App.notify()` returns no notification handle.
- Textual 6.12 provides public all-notification clearing through
  `clear_notifications()`. Selective removal exists through notification
  identity and the lower-level `_unnotify()` path.
- The existing test at `tests/test_console.py:557` proves cross-group delivery,
  cursor behavior, duplicate suppression, state preservation, and no QQ send,
  but does not cover current-group suppression or group-switch dismissal.

Implication: current-group suppression is local and straightforward. Selective
dismissal requires app-owned association between each mention notification and
its source group; clearing all notifications would also discard other groups'
alerts.
