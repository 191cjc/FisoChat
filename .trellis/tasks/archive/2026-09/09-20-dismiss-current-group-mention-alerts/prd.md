# Dismiss Current-Group Mention Alerts

## Goal

Keep @ popups meaningful by showing them only while their source group is not
the group currently being read.

## Background

- The terminal consumes a global mention feed and currently calls
  `notify(..., timeout=8)` for every accepted record after advancing its cursor
  (`src/fisochat/console.py:780-829`).
- `_select_group()` changes the active group but does not inspect or dismiss
  notifications (`src/fisochat/console.py:843-864`).
- Textual 6.12 exposes `clear_notifications()` publicly, but targeted removal
  requires retaining notification identity and using its lower-level removal
  path. This matters only when several groups have simultaneous alerts.

## Requirements

- Consume and advance the global mention cursor normally for every valid alert,
  including alerts from the selected group.
- Do not present a popup when the alert's `group_openid` already equals the
  selected group.
- When group selection completes, remove any still-visible @ popup associated
  with that group immediately.
- Dismissal must not make an alert eligible for replay and must not alter the
  selected group, draft, focus, reply/@ state, scroll position, messages, or QQ
  sender behavior.
- Preserve popups for groups that remain unread.

## Acceptance Criteria

- [x] A new qualifying @ record in the selected group advances the cursor but
      creates no visible popup.
- [x] A popup from another group disappears after switching to that group.
- [x] Switching away and refreshing does not replay the dismissed popup.
- [x] Alerts for groups that are not selected retain existing text, safety,
      timeout, deduplication, reconnect, and no-send behavior.
- [x] Focused terminal tests and the full project quality gate pass.

## Out of Scope

- Persistent read state, unread badges, alert history, or cross-process state.
- Automatic group switching, replies, reactions, sounds, or QQ sends.
- Backend feed, database, classifier, or API contract changes.

## Key Decisions

- When several groups have visible @ popups, selecting one group removes only
  that group's popups. Unrelated unread-group alerts remain visible.
