# Terminal Alert and Copy Behavior

## Goal

Make terminal attention state follow the group the operator is actually reading,
and make copied history preserve logical text rather than terminal-width wrapping.

## Deliverables

| Child task | Outcome |
| --- | --- |
| `09-20-dismiss-current-group-mention-alerts` | Suppress or dismiss @ popups once their group is being viewed. |
| `09-20-copy-history-without-soft-wrap-newlines` | Remove visual-wrap newlines from copied history without merging distinct messages. |

The children are independently implementable and testable. Neither depends on
the other, but both must pass together before this parent is complete.

## Requirements

- A new @ message for the selected group must not leave a popup visible.
- Switching to the group named by an existing @ popup must dismiss that group's
  popup state without replaying it later.
- Copying a selection across visual RichLog wrapping must concatenate the
  wrapped fragments without inserting `\n`.
- Copying across distinct rendered messages must retain their logical newline
  boundary.
- Preserve current message rendering, drafts, focus, reply state, scroll,
  selection highlighting, wide-character handling, alert cursors, and the
  terminal-only/no-send guarantee.

## Acceptance Criteria

- [x] Both child tasks satisfy their own acceptance criteria.
- [x] Alert dismissal and copy behavior coexist in one full terminal test run.
- [x] The full project quality gate passes with no backend API, database, QQ
      sender, or dependency changes.

## Out of Scope

- Persistent unread/read state across terminal restarts.
- Automatically switching groups in response to an @ message.
- Changing popup text, timeout, sound behavior, or QQ-side behavior.
- Copying raw database payloads instead of the currently rendered history.

## Key Decisions

- Entering a group dismisses only that group's @ popups. Alerts from other
  groups remain visible until their normal timeout or until those groups are
  selected.
