#!/usr/bin/env python3
"""Compatibility entry point: uv run python scripts/send_group_message.py ..."""

from fisochat.send import main

if __name__ == "__main__":
    raise SystemExit(main())
