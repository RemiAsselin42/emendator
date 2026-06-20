# One-time repository security setup

These settings live on GitHub, not in the repo, so they can't be committed.
Run once with the `gh` CLI (authenticated as a repo admin). Public repos get
secret scanning + push protection for free.

## Secret scanning + push protection — DONE (2026-06-20)

```bash
echo '{"security_and_analysis":{"secret_scanning":{"status":"enabled"},"secret_scanning_push_protection":{"status":"enabled"}}}' \
  | gh api -X PATCH repos/RemiAsselin42/emendator --input -
```

## Dependabot alerts — DONE (2026-06-20)

```bash
gh api -X PUT repos/RemiAsselin42/emendator/vulnerability-alerts
```

## Branch protection on `main` — DONE (2026-06-20)

Requires a PR + green CI before merging. All four CI jobs are required (Rust was
promoted once verified green).

```bash
gh api -X PUT repos/RemiAsselin42/emendator/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "checks": [
      { "context": "Frontend (lint · types · test · build)" },
      { "context": "Backend (ruff · pyright · pytest)" },
      { "context": "Duplication (fallow · jscpd)" },
      { "context": "Rust (fmt · clippy)" }
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": { "required_approving_review_count": 0 },
  "restrictions": null
}
JSON
```

> Solo dev: `required_approving_review_count: 0` keeps you unblocked while still
> requiring green CI. `enforce_admins: false` lets you bypass in emergencies.
