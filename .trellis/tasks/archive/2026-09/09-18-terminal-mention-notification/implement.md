# Implementation Plan

Prerequisite: complete and check sibling child
`09-18-multiline-terminal-composer` first so popup isolation tests target the
final composer widget and multiline draft state.

1. Add and test one shared @-current-bot classifier using event type plus
   `mentions[].is_you`, including malformed and other-member payloads.
2. Add and test the ascending cross-group repository cursor scan without a
   schema change.
3. Add the authenticated `/internal/group-mention-alerts` handler, route,
   bounded projection, cursor validation, pagination metadata, and HTTP tests.
4. Add `ConsoleClient` support for the feed.
5. Add the terminal's initial high-water mark, bounded page consumption, safe
   eight-second Textual popup, and no-bell behavior. Test inactive groups,
   duplicate polls, reconnect, initial history, composer/reply state, focus,
   selected group, scroll position, and absence of sends.
6. Update README behavior without adding browser or automatic-reply features.
7. Run focused repository/API/client/terminal tests, the full test suite,
   `compileall`, `uv lock --check`, `git diff --check`, and package build.
8. Run an independent full-scope review. After approval and clean checks,
   update the backend cross-layer contract, commit, restart the service, verify
   health/QQ connectivity, archive the task, and record the session. Do not
   generate a real QQ message during validation.

## Risk and Rollback Points

- Cursor advancement is the loss/duplication boundary. Tests must prove that
  ordinary records advance it, pages remain ordered, and retry after failure
  resumes from the last successful cursor.
- External usernames and content reach a popup. Use existing readable/safe text
  helpers, `markup=False`, single-line normalization, and strict length bounds.
- The refresh worker already serializes polling. Keep alert fetching inside the
  same data lock and cap pages per refresh to avoid starving UI interaction.
- No database/config migration is allowed; rollback is code-only.
