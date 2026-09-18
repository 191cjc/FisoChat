# Parent Execution Plan

1. Complete and independently check `09-18-multiline-terminal-composer`.
2. Complete and independently check `09-18-terminal-mention-notification`
   against the resulting multiline terminal state.
3. Run a parent-level integration check across all changed backend/terminal
   layers and the full project quality gate.
4. Update long-lived specs, commit coherent work batches, restart the service,
   verify health and QQ connectivity, archive both children and the parent, and
   record the session.

Do not send a real QQ message or manufacture a production @ event during
validation.
