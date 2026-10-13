# Implementation Plan

1. Add an exhaustive recall outcome to `logic.models`, update the sender port,
   and change `QQMessageSender.recall_from_group()` to classify success,
   ineligibility, and operational failure without retrying DELETE.
2. Add the authenticated `POST /internal/group-messages/recall` handler and route.
   Validate the exact body, resolve the current-group record, preserve the opaque
   QQ message ID, and map typed outcomes to the documented 200/409/502 contract.
3. Extend `ConsoleClient` with recall-specific request and ambiguous transport
   messaging while leaving existing send behavior unchanged.
4. Add `/recall <record_id>` to command completion/help and terminal dispatch.
   Execute immediately, guard against duplicate actions, update the cached record
   on success, redraw `[已撤回]`, and restore focus/state on every outcome.
5. Extend sender, admin API, standalone route, client, command-completion, and
   terminal interaction tests. Include wrong-group, user-authored, already
   recalled, expired, malformed, QQ failure, ambiguous transport, and successful
   redraw cases with assertions that invalid paths never call DELETE.
6. Run focused checks:

   ```bash
   uv run python -m unittest tests.test_qq_sender tests.test_group_messages -v
   uv run python -m unittest tests.test_admin_messages tests.test_standalone_app -v
   uv run python -m unittest tests.test_console tests.test_console_commands -v
   ```

7. Run the project quality gate:

   ```bash
   uv run python -m unittest discover -s tests -v
   uv run python -m compileall -q src tests
   uv lock --check
   git diff --check
   uv build
   ```

8. Review the final diff for opaque-ID preservation, exact route registration,
   strict validation, no confirmation UI, and no automatic retry. Restart
   `fisochat.service`, verify it is active and QQ reports connected, but do not
   perform a live recall automatically.

## Risky Files and Rollback Points

- `src/fisochat/services/qq/sender.py`: remote destructive operation and ambiguous
  failure classification. Revert the typed outcome and route together.
- `src/fisochat/interfaces/web/admin_messages.py`: authentication, record lookup,
  and API error mapping. Remove the route to disable the feature safely.
- `src/fisochat/console.py`: cached-history mutation and busy-state restoration.
  Focused interaction tests must prove state recovers after all failures.

No migration rollback is required.
