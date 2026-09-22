# Implementation Plan

1. Add a repository query for the latest unrecalled incoming gateway record per
   member OpenID in one group. Use the existing member-record index and retain
   descending recent-activity order.
2. Extend the admin repository protocol and add authenticated
   `GET /internal/group-members?group=...`. Reuse group validation,
   `_can_mention()`, and the group-scoped sender-key projection; return only
   `record_id`, `sender_key`, and `username`.
3. Add `ConsoleClient.members(group)` with the existing structured error path.
4. Replace completion's dependency on the loaded-message cache with an active
   member directory seeded during group selection. Upsert eligible synchronized
   messages by sender key so new speakers and nickname changes appear live.
5. Preserve `/at`, mention span payloads, draft restoration, group isolation,
   input limits, aliases, and send-time record validation.
6. Add focused repository tests for historical candidates, per-group
   deduplication, latest username/anchor, ordering, recalled rows, outbound rows,
   other bots, and invalid/missing OpenIDs.
7. Add admin/client/route tests for authentication, strict group validation,
   response projection, no OpenID disclosure, and error handling.
8. Add terminal tests proving an unloaded historical speaker is searchable,
   synchronized new speakers and renamed members update in place, group switches
   isolate candidates, and draft/send behavior is unchanged.
9. Run focused checks:

   ```bash
   uv run python -m unittest tests.test_group_messages tests.test_admin_messages -v
   uv run python -m unittest tests.test_console_mentions tests.test_console tests.test_standalone_app -v
   ```

10. Run the full quality gate:

   ```bash
   uv run python -m unittest discover -s tests -v
   uv run python -m compileall -q src tests
   uv lock --check
   git diff --check
   uv build
   ```

11. Review the final diff for group scoping, latest-record semantics, other-bot
    compatibility, absence of raw OpenIDs in terminal payloads, and no schema or
    configuration drift.

## Risky Files And Rollback Points

- `src/fisochat/database/group_messages.py`: latest-per-member SQL must filter
  eligibility before deduplication and stay group-scoped.
- `src/fisochat/interfaces/web/admin_messages.py`: the new projection must reuse
  send-time eligibility and never expose member OpenIDs.
- `src/fisochat/console.py`: member-directory refresh must not disturb drafts,
  selected mention spans, aliases, focus, or concurrent message synchronization.

No migration rollback is required.
