# Contributing / Local development

Emendator is a polyglot desktop app: a **Tauri (Rust)** shell hosting a
**React/TypeScript** front, talking to a local **FastAPI (Python)** sidecar.

## Prerequisites

| Tool       | Version | Install                                              |
| ---------- | ------- | --------------------------------------------------- |
| Node       | 22+     | nvm / winget                                         |
| pnpm       | 11+     | `corepack enable` (reads `packageManager` field)    |
| Python     | 3.13+   | winget / pyenv                                       |
| uv         | latest  | `winget install astral-sh.uv`                        |
| Docker     | latest  | required for the Phase 2 runner only                |
| Rust + MSVC| stable  | see **Rust toolchain (Windows)** below              |

## Rust toolchain (Windows)

Tauri compiles a native binary and needs Rust **plus the MSVC C++ linker**.
WebView2 ships with Windows 11 (already present).

1. **MSVC C++ build tools** — add the C++ workload (the linker `link.exe` + MSVC
   toolset). Either modify your existing Visual Studio:

   > Open **Visual Studio Installer** → *Modify* → check
   > **“Desktop development with C++”** → *Modify*.

   …or install the standalone build tools via winget (needs admin / UAC):

   ```powershell
   winget install --id Microsoft.VisualStudio.2022.BuildTools `
     --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
   ```

2. **Rust** (user-scope, no admin):

   ```powershell
   winget install --id Rustlang.Rustup
   rustup default stable-x86_64-pc-windows-msvc
   ```

   Restart the shell, then verify: `cargo --version` and `link` (MSVC linker)
   both resolve.

## Install & run

```bash
# Frontend deps
pnpm install

# Backend deps (creates backend/.venv)
cd backend && uv sync && cd ..

# Run the full app (Vite + Rust shell). Needs the Rust toolchain.
pnpm tauri dev

# Or run the pieces separately:
pnpm dev                                                   # front only, http://localhost:1420
cd backend && uv run uvicorn app.main:app --reload --port 8008
```

## Quality gates (mirror CI)

```bash
# Frontend
pnpm lint            # biome
pnpm typecheck       # tsc
pnpm test            # vitest
pnpm build           # vite production build

# Backend (from backend/)
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest

# Duplication
pnpm dup:ts          # fallow (TS/JS)
pnpm dup             # jscpd (Python + Rust)
pnpm dead-code       # fallow unused-code report

# Rust (from repo root, needs toolchain)
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
cargo clippy --manifest-path src-tauri/Cargo.toml -- -D warnings
```

## Pre-commit hook

```bash
uv tool install pre-commit   # or: pipx install pre-commit
pre-commit install
```

Runs ruff + biome on commit (cargo fmt skips until Rust is installed). Heavier
checks (duplication, typecheck, tests) run in CI, not on commit.

## Workflow

`main` is protected: work on a branch, open a PR, merge once the four CI checks
pass. See `.github/repo-setup.md` for the repository-level security settings.

## Conventions

All artifacts (code, comments, commits, PRs, docs) are in **English**.
Commit messages are plain (no AI-attribution trailer).
