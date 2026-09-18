# Implementation Plan

Prerequisite: implement and check this child before
`09-18-terminal-mention-notification`.

1. Replace the command composer base widget with TextArea and implement
   normalized paste, guarded length, flat offset/location conversion, custom
   submission, and Enter/Shift+Enter behavior.
2. Port command and @ hint/completion behavior, preserving candidate-only key
   overrides and mention edit math.
3. Update `FisoChatApp` submission, drafts, focus, disabled state, selection
   copy, mention payloads, and responsive composer CSS.
4. Update help/README text for multiline paste and Shift+Enter.
5. Add focused tests for CRLF/CR paste normalization, sending, manual newline,
   max length, commands, mentions across lines, drafts, failures, copy/focus,
   and compact/desktop layout.
6. Run focused tests, full suite, `compileall`, `uv lock --check`,
   `git diff --check`, and package build, followed by an independent child
   review. Do not restart the service or send a real QQ message in this child.
