# Design: Current-Group Mention Alert Dismissal

## State

FisoChatApp retains the Textual Notification objects created for mention
alerts, grouped by source group_openid. Expired objects are pruned so app-owned
tracking does not grow for the life of the terminal.

## Presentation

After a feed page is fully validated and its cursor advanced:

1. Skip presentation when the alert group already equals selected_group.
2. Otherwise create the same safe, non-markup, eight-second information
   notification used today.
3. Retain its identity under the source group and present it through Textual's
   notification message path.

Cursor progression and duplicate suppression do not depend on whether a popup
is presented.

## Dismissal

After a group becomes selected, remove only tracked notifications belonging to
that group and refresh the toast rack. Encapsulate Textual's lower-level
selective removal behind one local helper because Textual 6.12 exposes only
all-notification clearing as a public application method.

Do not match notifications by rendered text, title, or group-label substring.
Do not call clear_notifications(), because that would discard alerts from other
unread groups.

## Compatibility and Failure Behavior

- Expired or already-removed notification handles are harmless no-ops during
  group selection.
- A failed group selection does not dismiss the target group's popup because the
  operator has not entered that group.
- No persistent read state is added; terminal restart behavior is unchanged.
- No feed, classifier, database, API, or sender code changes.

## Rollback

Remove the grouped notification handles and presentation/dismissal helpers;
global feed and timeout-only popup behavior remain intact.
