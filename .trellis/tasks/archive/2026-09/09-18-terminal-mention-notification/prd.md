# Terminal Notification for Bot Mentions

## Goal

Make an operator who is running the terminal notice a newly received group
message that explicitly mentions the current QQ bot, without sending any
automatic QQ response.

## Background

- The backend already records all incoming group messages and the terminal
  displays messages from the currently selected group.
- Production data shows that a message mentioning this bot commonly arrives as
  `GROUP_MESSAGE_CREATE`, not only `GROUP_AT_MESSAGE_CREATE`. The reliable
  production marker is a payload `mentions` entry with `is_you=true`; 34 such
  records already exist in the current database.
- The terminal refreshes group summaries every two seconds but fetches message
  records only for the active group. Initial selection and `/older` load
  historical records that must not be mistaken for new alerts.
- Textual provides a visible notification API and a separate terminal bell.
- The user explicitly cancelled automatic replies and the earlier request to @
  a member named “浴火之魄”.

## Requirements

### R1. Mention Classification

- Classify an incoming message as mentioning this bot when its gateway event is
  `GROUP_AT_MESSAGE_CREATE` or its payload contains a `mentions` item whose
  `is_you` value is exactly `true`.
- Do not alert for this bot's outbound records, ordinary messages, malformed
  mention metadata, or another member being mentioned.

### R2. Terminal-Only Notification

- Monitor every recorded group, including groups other than the currently
  selected one.
- Show one visible Textual popup for each qualifying message, with no terminal
  bell. The popup contains a safe, bounded group identifier, sender name,
  record number, and message excerpt and remains visible long enough to scan.
- The alert must not change the active group, input focus, draft, selected @
  spans, reply mode, scroll position, or message persistence.
- Each qualifying record alerts at most once in a terminal session, even when
  refresh results overlap or reconnect. After a temporary disconnect, alert
  for qualifying records not previously seen by that running terminal.
- Establish an initial high-water mark without alerting for historical records;
  `/older`, group switching, redraw, and initial load must not emit alerts.

### R3. No External Side Effect

- Do not call any QQ send API, create an outbound database record, automatically
  reply, or @ any member.
- Existing manual send, reply, @, image, sticker, copy, and group-selection
  behavior must remain unchanged.

## Acceptance Criteria

- [ ] AC1: A newly received `GROUP_AT_MESSAGE_CREATE` record produces one
      visible Textual popup and no terminal bell.
- [ ] AC2: A newly received `GROUP_MESSAGE_CREATE` record with
      `mentions[].is_you=true` also produces one alert.
- [ ] AC3: Ordinary messages, other-member mentions, malformed payloads,
      bot-authored records, and repeated polling produce no alert.
- [ ] AC4: Initial history, `/older`, group switching, and reconnect do not
      replay stale alerts.
- [ ] AC5: Alerts preserve the current group, draft, focus, reply/@ state,
      scroll position, and never call the QQ sender.
- [ ] AC6: Focused API/terminal tests and the full project quality gate pass.

## Out of Scope

- Automatic QQ replies, @ mentions, reactions, AI-generated content, or any
  other outbound action.
- Persistent read/unread state across terminal restarts.
- Desktop/mobile push notifications, email, webhooks, or browser UI.
