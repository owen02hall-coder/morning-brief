# morning-brief

## Report to Wingman (Owen's Central Hub)

Owen tracks every Claude session in Wingman, in his Atlas hub. Report there so he never has to check this session by hand.

- Repo key: `morning-brief`. Area: `personal`. Ref: `project:morning-brief`.
- When you start real work: write a `progress` item. When you finish: set it to `done` with a one-line `result`.
- When you need Owen (a decision, an approval, a merge you cannot do, anything that sends a message or touches money): write a `needs` item with a plain `action` saying what happens on Approve. Do not do the thing until he approves.
- When you are stuck (failing CI you cannot fix, missing access or keys): write a `needs` item that says what is blocking you.
- Item id: `code-morning-brief-<YYYYMMDD-HHMM>`, reused for updates to the same piece of work.
- Fields: `agent` "code", `kind` (progress | needs | done), `title` (one short line), `detail` (one or two short lines), `area`, `ref`, `link` (https, e.g. the PR) and `linkLabel`, `status` (open | done), `createdAt` and `updatedAt` (ISO). For `needs` also `action` and `status` open.
- How to write: if `~/.central-hub.env` exists, POST `{"ops":[{"op":"merge","col":"brain","id":"<id>","data":{...}}]}` to `$HUB_URL/api/write` with `Authorization: Bearer $HUB_TOKEN`. Otherwise use the Neon connector on project `jolly-grass-18463699`:
  `insert into hub_docs (col, id, data) values ('brain', '<id>', '<json>'::jsonb) on conflict (col, id) do update set data = hub_docs.data || excluded.data, updated_at = now()`
- If neither works, skip it and say so in your final message. Never ask Owen for keys in chat.
- Keep it short. No em dashes. Full schema: `docs/claude-update-rule.md` in owen02hall-coder/central-hub.
- After meaningful work, update `PROJECT.md` (goal, milestones, next step) so the hub and the next session can see where things stand.
