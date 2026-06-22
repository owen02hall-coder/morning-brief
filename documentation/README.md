---
title: Documentation Index
source_files: [documentation/]
entry_points: [documentation/architecture.md, documentation/integrations.md, documentation/operations.md]
last_verified: 2026-06-22
---

# Documentation

Developer documentation for the Morning Briefing project. The user-facing setup guide is the
top-level `README.md`. These files cover how the system is built and run.

Note: the project's `docs/` folder is the GitHub Pages web root (it serves the PWA), not a
documentation folder. Developer docs live here in `documentation/` to avoid polluting the live site.

## Files

- `architecture.md` — system overview, data flow, modules, key design decisions, the briefing.json
  schema, and entry points.
- `integrations.md` — every external service (Yahoo Finance, Gemini, ntfy, RSS, GitHub Pages and Actions,
  and the v2-only Twelve Data), what each is used for, where it is invoked, and the env var names.
- `operations.md` — scheduling, one-time deployment, runtime behavior, monitoring, failure modes,
  regression tests, and cost.

## Start here if you want to...

- Understand how the briefing is produced end to end: `architecture.md`.
- Add or swap a data source or change an API key: `integrations.md`.
- Deploy it, change the schedule, or debug a failed run: `operations.md`.
- Set it up as a user for the first time: top-level `README.md`.
- See the v2 breadth plan and why it was deferred: `tmp/ready-plans/2026-06-15-morning-briefing-pwa.md`.

## Scope

This documents v1 (the core briefing). The breadth and oversold-alert feature is v2 and not yet
built. Areas that do not apply to this project are intentionally omitted: there is no database, no
authentication, and no internal API surface.
