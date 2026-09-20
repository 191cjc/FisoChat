# Fix Uppercase Sticker Save Shortcut

## Goal

Make the image preview's visible `S 收藏` shortcut work whether the operator
presses lowercase `s` or uppercase `S` (`Shift+S`).

## Background

- The sticker library, six stored PNG/JPEG files, authenticated API, and
  lowercase save flow are intact.
- `ImageScreen` displays `S 收藏` but currently binds only `s`
  (`src/fisochat/console.py:227`).
- A Textual reproduction confirms lowercase `s` calls the save callback while
  `Shift+S` does nothing.
- The existing regression covers only lowercase `s`
  (`tests/test_stickers.py:348`).

## Requirements

- Lowercase `s` and uppercase `S` must invoke the same manual save action from
  an eligible received-image preview.
- One key press must create at most one save request.
- Preserve all existing eligibility rules: only an incoming, unrecalled image
  in the selected group exposes collection.
- Preserve PNG/JPEG validation, deduplication feedback, draft state, preview
  navigation, and `/stickers` behavior.
- Do not change the backend API, filesystem format, QQ sender, or supported
  image formats.

## Acceptance Criteria

- [x] Pressing `Shift+S` in an eligible image preview calls the save callback
      once with the same one-based attachment index as lowercase `s`.
- [x] Lowercase `s` continues to save and duplicate feedback remains correct.
- [x] Closing the preview still preserves the current multiline draft.
- [x] Focused sticker tests and the full project quality gate pass.

## Out of Scope

- Saving bot-authored or recalled images.
- Adding GIF/WebP collection, automatic collection, deletion controls, or a
  second save entry point outside the image preview.
