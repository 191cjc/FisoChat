# Journal - chenjiachun (Part 1)

> AI development session journal
> Started: 2026-09-17

---



## Session 1: Harden message storage and terminal history
<!-- trellis-session: v=2 fp=f547b4dae01702e6 -->

**Date**: 2026-09-17
**Task**: Harden message storage and terminal history
**Branch**: `main`

### Summary

Established the FisoChat baseline, added safe composite-key SQLite migration and deterministic duplicate merging, documented controlled rollback, and made terminal chat history selectable and copyable with regression coverage.

### Git Commits

| Hash | Message |
|------|---------|
| `660f6fe` | feat: establish FisoChat with hardened message storage |
| `70bd709` | fix: make terminal chat history selectable |

### Status

[OK] **Completed**


## Session 2: Terminal sticker library and browser retirement
<!-- trellis-session: v=2 fp=b49b47a0f5f674ad -->

**Date**: 2026-09-17
**Task**: Terminal sticker library and browser retirement
**Branch**: `main`

### Summary

Added manual PNG/JPEG sticker collection, global content-addressed storage, signed QQ retrieval and terminal sending; removed the browser viewer and hardened storage, deletion races, and ambiguous send handling.

### Git Commits

| Hash | Message |
|------|---------|
| `cca1777` | feat: add terminal sticker library and sending |

### Status

[OK] **Completed**


## Session 3: Fix QQ reply IDs and verify JPEG stickers
<!-- trellis-session: v=2 fp=42928224e9c3c228 -->

**Date**: 2026-09-18
**Task**: Fix QQ reply IDs and verify JPEG stickers
**Branch**: `main`

### Summary

Accepted production-shaped opaque QQ message IDs, enabled native replies for recent ordinary group messages while preserving safety limits, added cross-layer regression coverage and a reply contract spec, verified JPEG storage/public retrieval, and restarted the connected service.

### Git Commits

| Hash | Message |
|------|---------|
| `4feac6a` | fix: accept opaque QQ reply message IDs |

### Status

[OK] **Completed**


## Session 4: Multiline composer and terminal mention alerts
<!-- trellis-session: v=2 fp=32bd5e1438e1c5be -->

**Date**: 2026-09-18
**Task**: Multiline composer and terminal mention alerts
**Branch**: `main`

### Summary

Added a multiline Textual composer that preserves pasted line breaks and a cross-group, terminal-only popup feed for messages that mention the current bot; verified state isolation, no outbound QQ side effects, and restarted the connected service.

### Main Changes

- Preserved CRLF/CR-normalized multiline paste, Enter send, Shift+Enter newline, commands, mentions, drafts, reply state, copy, and the 2,000-character atomic limit.
- Added an authenticated global record cursor feed and eight-second Textual popups for current-bot mentions across all groups without bells or automatic replies.
- Documented executable composer and mention-alert contracts and archived the parent and child tasks.

### Git Commits

| Hash | Message |
|------|---------|
| `58df9e2` | feat: add multiline composer and mention alerts |

### Testing

- [OK] 162 unittest cases passed; compileall, uv lock --check, git diff --check, and uv build passed.
- [OK] Restarted fisochat.service; /health reported database open and QQ gateway connected.

### Status

[OK] **Completed**


## Session 5: Fix uppercase sticker save shortcut
<!-- trellis-session: v=2 fp=7f234ece4173aebf -->

**Date**: 2026-09-20
**Task**: Fix uppercase sticker save shortcut
**Branch**: `main`

### Summary

Bound both lowercase s and Shift+S to manual sticker collection, added regression coverage for exactly-once saves, duplicate feedback, and draft preservation, and tightened the sticker terminal test contract.

### Git Commits

| Hash | Message |
|------|---------|
| `f3479c6` | fix: support uppercase sticker save shortcut |

### Status

[OK] **Completed**
