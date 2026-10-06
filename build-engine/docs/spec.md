# TeslaLab Build Engine - Spec (Day 1)

## App types
- `website` - static/marketing site.
- `web_app` - interactive app with server/client logic.
- `ai_agent` - app that wraps LLM/agent behaviour.

## Project folder structure (per project)
Host: `SANDBOX_ROOT/<tenant_id>/<project_id>/`, mounted at `/workspace` in the sandbox.

```
<project>/
  package.json     # Node manifest (stack default: nextjs)
  src/             # source files
  public/          # static assets
  node_modules/    # created by npm install, never touched by the file tools
```

Every tool path is relative to the project root. Absolute paths, `..`, and
symlink escapes are rejected (single helper `sandbox._resolve`).

## Project statuses
`BUILDING | READY | DEPLOYING | LIVE | ERROR | MAINTENANCE`

Allowed transitions (enforced by `models.project.allowed_transition(old, new)`):
- `BUILDING -> READY | ERROR`
- `READY -> DEPLOYING`
- `DEPLOYING -> LIVE | ERROR`
- `LIVE -> MAINTENANCE | ERROR`
- `MAINTENANCE -> LIVE | ERROR`
- `ERROR -> BUILDING`

Create always starts at `BUILDING`.

## Sandbox result format
`run_command(...)` returns a `RunResult` dataclass:

| field | type | meaning |
|---|---|---|
| `ok` | bool | `exit_code == 0` and not `timed_out` |
| `exit_code` | int | process exit code (`124` when timed out) |
| `stdout` | str | last 200 KB of stdout |
| `stderr` | str | last 200 KB of stderr |
| `duration_s` | float | wall-clock seconds |
| `timed_out` | bool | True when the host killed the container on timeout |

Commands are limited to `npm`, `npx`, `node`. Containers run with 1 CPU,
512 MB RAM, 256 pids, the non-root `node` user, and no network unless
`network=True` (only intended for `npm install`).

## API (Day 1)
Caller identity is stubbed from headers `X-Tenant-Id` and `X-User-Id`.
Every query filters by `tenant_id`; another tenant's project returns **404**.

- `POST /projects` -> 201 `ProjectRead`
- `GET /projects/{id}` -> 200 `ProjectRead` | 404
- `GET /projects` -> 200 `list[ProjectRead]` (caller's tenant only)

## Day 2 preview and template

The development preview container has outbound network access; restrict it with an egress allowlist on Day 5. It listens on `0.0.0.0:3000` in the container and is published only on `127.0.0.1`.

Prepare the base template once using the Docker command below; keep `templates/base/node_modules` local-only and out of Git.
Dev server has outbound network access; restrict with an egress allowlist on Day 5.
On Windows, install Linux-compatible template dependencies from the repository root with: `docker run --rm --network bridge --user node --mount "type=bind,source=$($PWD.Path)\templates\base,target=/workspace" -w /workspace teslalab-sandbox:latest npm install`.
