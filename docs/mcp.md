# Drive Emendator from your AI client

Emendator ships an [MCP](https://modelcontextprotocol.io) server, so any MCP
client — Claude Code, Claude Desktop, Cursor, … — can scan a modpack, boot it
headless, bisect a crash and apply the precise mixin fix ladder, with your
agent doing the reasoning.

## Connect

**Claude Desktop (one-click):** build or download `emendator.mcpb`
(`scripts/build-mcpb.sh`) and drop it into *Settings → Extensions*.

**Claude Code / any stdio client:** point the client at the sidecar with the
`mcp` argument. From a source checkout:

```json
{
  "mcpServers": {
    "emendator": {
      "command": "uv",
      "args": ["run", "--project", "backend", "python", "-m", "app.mcp"]
    }
  }
}
```

With the installed app, use the bundled binary instead:
`<install dir>/emendator-backend.exe mcp`.

Docker Desktop must be running for the boot/bisect/verify tools.

## Tools

| Tool | What it does |
| --- | --- |
| `scan_instance` | Mods + graded conflict map (mixin `methodDetails` reasoning included) |
| `run_test` | Headless Docker boot → verdict, crash cause, attribution, `runId` |
| `bisect` | Delta-debug a crash to the minimal guilty subset (~log₂(N) boots) |
| `list_runs` / `get_run` / `get_run_log` / `get_run_crash` | The persisted evidence store |
| `plan_mixin_fixes` | The fix ladder: own toggle → filter config → disable, with alternatives |
| `apply_mixin_fixes` | Execute the plan reversibly (merge-aware writes, manifest) |
| `revert_mixin_fixes` | Undo an apply by its manifest |
| `verify_mixin_fixes` | Re-boot and diff against the pre-fix baseline run |
| `disable_mod` / `enable_mod` / `update_mod` / `rollback_mod` | Per-jar levers |

## Guardrails

- **Every mutating tool is dry-run by default.** Without `apply: true` it
  returns a preview and a note to confirm with the user first. Agents should
  show the plan (including each fix's `featureHints` — what the pack loses)
  and get an explicit go-ahead before re-calling with `apply: true`.
- Every mutation is recorded in a revert manifest; `revert_mixin_fixes`
  restores prior file content, re-enables jars and removes installed filter
  mods.
- Errors are structured values (`{"error": ...}`), never raw exceptions.
- `run_test` / `bisect` block for the duration of real boots (minutes);
  live per-boot progress remains on the HTTP API's SSE endpoints, which the
  desktop UI uses.

## A typical agent loop

1. `scan_instance` → read the `error`-severity `mixin_overlap` conflicts.
2. `run_test` → confirm the crash; keep the verdict's `runId`.
3. `plan_mixin_fixes` → show the user the plan + trade-offs.
4. `apply_mixin_fixes(apply=true)` after confirmation.
5. `verify_mixin_fixes(baseline_run_id=<runId>)` → `fixed: true` or iterate
   (different loser via `losers`, rollback, bisect deeper).
