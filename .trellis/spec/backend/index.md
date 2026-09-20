# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

This directory contains guidelines for backend development. Fill in each file with your project's specific conventions.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | To fill |
| [Database Guidelines](./database-guidelines.md) | ORM patterns, queries, migrations | To fill |
| [Error Handling](./error-handling.md) | Error types, handling strategies | To fill |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging, log levels | To fill |
| [Sticker Library Contracts](./sticker-library.md) | Storage, API, signing, terminal and QQ delivery contracts | Active |
| [QQ Reply Context Contracts](./reply-context.md) | Opaque message IDs, reply eligibility, sequence allocation, and cross-layer forwarding | Active |
| [Terminal Composer Contracts](./terminal-composer.md) | Multiline editing, paste normalization, limits, completion, drafts, and submission | Active |
| [Terminal Bot-Mention Alert Contracts](./terminal-mention-alerts.md) | Global cursors, alert API, session popup state, and no-send guarantees | Active |
| [Terminal History Copy Contracts](./terminal-history-copy.md) | Logical write boundaries, visual wrapping, selection, and clipboard behavior | Active |

---

## How to Fill These Guidelines

For each guideline file:

1. Document your project's **actual conventions** (not ideals)
2. Include **code examples** from your codebase
3. List **forbidden patterns** and why
4. Add **common mistakes** your team has made

The goal is to help AI assistants and new team members understand how YOUR project works.

---

**Language**: All documentation should be written in **English**.
