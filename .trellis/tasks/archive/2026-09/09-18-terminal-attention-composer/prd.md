# Terminal Attention and Composer Improvements

## Goal

Improve the terminal's ability to attract the operator's attention and accept
real chat content by delivering cross-group @-bot popups and a multiline
composer that preserves pasted line breaks.

## Source Requirements

- Alert in the terminal when any monitored QQ group receives a message that
  explicitly mentions the current bot.
- The alert is a visible popup only: no bell, automatic reply, outgoing @, or
  other QQ side effect.
- Pasting multiline text must retain every line and send the same internal line
  structure.
- `Enter` sends and `Shift+Enter` inserts a newline.
- Existing terminal commands, @ selection, drafts, reply mode, copying, group
  switching, image/sticker workflows, and 2,000-character limit remain usable.

## Task Map and Ordering

| Child | Deliverable | Order |
| --- | --- | --- |
| `09-18-multiline-terminal-composer` | Replace the single-line composer with a compatible multiline editor | First |
| `09-18-terminal-mention-notification` | Add a cross-group cursor feed and visible @-bot popups | Second |

The order is required because both children touch terminal refresh/composer
state and notification tests must assert compatibility with the final
multiline component. Each child remains independently testable and revertible.

## Cross-Child Acceptance Criteria

- [ ] AC1: Multiline paste, `Enter` send, and `Shift+Enter` newline work while
      command completion and @ member selection retain their behavior.
- [ ] AC2: New @-bot messages from active and inactive groups each create one
      visible popup without a bell or QQ send.
- [ ] AC3: Popup refresh cannot alter multiline drafts, cursor/focus,
      selection, mention spans, reply mode, scroll, or active group.
- [ ] AC4: Initial history is silent, reconnect resumes without duplicates,
      and group switching preserves multiline drafts.
- [ ] AC5: Both child quality gates and one final integrated full-suite review
      pass before deployment.

## Out of Scope

- Automatic replies, automated @ mentions, AI-generated text, reactions, or
  any other outbound automation.
- Persistent unread state, desktop/mobile push, webhooks, or browser UI.
- Rich-text editing, attachments pasted from the clipboard, or messages beyond
  the existing 2,000-character limit.
