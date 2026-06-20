# Security Policy

## Reporting a vulnerability

Report security issues privately via **GitHub Security Advisories**
(repo → Security tab → *Report a vulnerability*). Please do not open a public issue.

## Supported versions

Pre-1.0: only the latest `main` branch is supported.

## Project security model

Emendator boots **untrusted Minecraft mod jars** to confirm load-time conflicts.
A mod is arbitrary code. Per `PROJECT.md` §8, every runtime boot runs inside an
**isolated Docker container** (restricted filesystem + network) — never directly
on the host. This isolation is implemented in **Phase 2**; until then the app does
no untrusted execution (static analysis only, Phase 1).
