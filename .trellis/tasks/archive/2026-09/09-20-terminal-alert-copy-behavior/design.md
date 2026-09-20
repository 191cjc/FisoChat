# Design: Terminal Alert and Copy Behavior

## Boundaries

Both changes stay inside the terminal application and its Textual tests.

```text
mention feed -> FisoChatApp notification state -> selected-group dismissal
rendered message -> SelectableRichLog visual lines + logical boundaries -> clipboard
```

There are no backend API, database, QQ sender, environment, dependency, or
stored-data changes.

## Child Integration

The alert child owns mention-notification lifecycle state. The copy child owns
RichLog line-boundary metadata and selected-text extraction. They share
src/fisochat/console.py and tests/test_console.py, so implementation is
sequential even though their observable behavior is independent.

Implement the copy child first, then the alert child against the resulting
files. Run focused tests after each child and the full project gate after both.

## Compatibility

Keep the existing Textual selection model, message formatting, global mention
cursor, popup contents and timeout, composer behavior, and no-send guarantee.
The active terminal process must be restarted after deployment because key UI
classes and app state are loaded at process startup.

## Rollback

Each child can be reverted independently: remove the logical-boundary metadata
to restore visual-line copying, or remove app-owned mention notification
tracking to restore timeout-only popup behavior.
