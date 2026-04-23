---
title: Mac Mini Vault Writer Audit
type: runbook
invariant: CHANDA-9
cadence: monthly
owner: AI Head
updated: 2026-04-23
---

# Mac Mini Vault Writer Audit — CHANDA #9

## Purpose

CHANDA invariant #9 (tier: critical) requires that baker-vault has **exactly one writer**: the Mac Mini at SSH alias `macmini`. Enforcement is infra-level — Render has no push credentials for the vault repo, and no other machine has `github-baker-vault:` SSH config or deploy key.

This runbook verifies the invariant monthly. If any check fails, the invariant is silently weakened and must be restored before the next pipeline write.

## Audit cadence

**Monthly** on the first Monday of the month (co-firing with `ai_head_weekly_audit` cron is acceptable; separate execution preferred).

## Checks

### 1. Mac Mini is reachable + has the vault checkout

```bash
ssh macmini 'cd ~/baker-vault && git remote -v && git rev-parse HEAD'
```

Expect:
- SSH succeeds (no password prompt, alias resolves).
- `git remote -v` lists `origin` pointing at `github-baker-vault:vallen300-bit/baker-vault.git` (or equivalent SSH URL).
- `git rev-parse HEAD` returns a SHA within 48h of the latest origin/main.

### 2. Render has NO push credentials for baker-vault

Via Render MCP or dashboard — list deploy keys + env vars for the Baker service:

```bash
# If Render MCP is available:
curl -s "https://api.render.com/v1/services/${BAKER_SVC_ID}/env-vars" \
  -H "Authorization: Bearer $RENDER_TOKEN" | jq '.[] | select(.key | test("(?i)vault|ssh|deploy"))'
```

**Reject:** any env var named like `BAKER_VAULT_SSH_KEY`, `VAULT_DEPLOY_KEY`, `GITHUB_VAULT_TOKEN` with a populated `value`. Presence of such a var is a CHANDA #9 breach in progress — investigate, rotate, remove.

Also check GitHub repo settings manually (`Settings > Deploy keys` for the vault repo) — confirm only the Mac Mini's public key is listed. Zero other keys.

### 3. No recent vault commits originating from non-Mac-Mini machines

```bash
ssh macmini 'cd ~/baker-vault && git log --format="%H %ae %s" origin/main -20'
```

Review committer emails. Expected committers:
- `dimitry.vallen@...` (Director, manual commits allowed per Inv 9: single AGENT writer, Director writes welcome from any machine)
- `ai-head@brisengroup.com` (AI Head SSH from Mac Mini — verifiable via `git log --format="%cn %ce %cD"` + machine of record)
- Pipeline-bot identities (Mac Mini-origin only)

**Reject:** any commit from an identity tagged as another agent / Render service / CI.

### 4. CHANDA #4 hook is installed + executable on Mac Mini

```bash
ssh macmini 'ls -l ~/baker-vault/.git/hooks/commit-msg ~/baker-vault/.git/hooks/pre-commit 2>/dev/null'
```

Per the 2026-04-23 hook-stage fix (MAC_MINI_WRITER_AUDIT_1 Feature 2), the hook is at `.git/hooks/commit-msg` with mode `-rwxr-xr-x` and size ~3562 bytes. `pre-commit` may exist as `.sample` or removed — either is fine.

Smoke test:

```bash
ssh macmini 'cd /tmp && rm -rf vault-smoketest && git init -q vault-smoketest && cd vault-smoketest && \
  git config user.email "test@test" && git config user.name "test" && \
  printf -- "---\nauthor: director\n---\nbody\n" > hot.md && \
  git add hot.md && git commit -qm seed && \
  printf -- "---\nauthor: director\n---\nmodified\n" > hot.md && \
  git add hot.md && \
  cp ~/baker-vault/.git/hooks/commit-msg .git/hooks/commit-msg && \
  chmod +x .git/hooks/commit-msg && \
  (git commit -m "no marker" 2>&1 || true) | tail -3'
```

Expect: "CHANDA invariant #4" rejection message. Then confirm marker-positive path:

```bash
ssh macmini 'cd /tmp/vault-smoketest && git commit -m "tweak\n\nDirector-signed: \"smoke test\"" 2>&1 | tail -2'
```

Expect: commit succeeds.

### 5. SSH key rotation stale check

```bash
ssh macmini 'stat -f %Sm ~/.ssh/id_ed25519 2>/dev/null || stat -c %y ~/.ssh/id_ed25519 2>/dev/null'
```

If key is >365 days old, note for Director — key rotation is a Director-level action (§4 #13 security policy change).

## Escalation

Any check failing → Slack DM Director at channel `D0AFY28N030` with:
- Which check failed
- Evidence (command output, file state)
- Proposed remediation (but do NOT execute without Director ratify if the fix touches §4 security-policy prerogatives)

## Lessons captured

- **2026-04-23** — Hook stage bug (CHANDA #4 was at pre-commit, needed commit-msg). Surfaced during KBL_SCHEMA_1 vault mirror. Fixed by MAC_MINI_WRITER_AUDIT_1 Feature 2. Future script deployments: test `git commit -F` flow, not only direct-arg `bash .git/hooks/<hook>` invocation.

## Amendment log

| Date | Change | Authority |
|------|--------|-----------|
| 2026-04-23 | Initial creation (MAC_MINI_WRITER_AUDIT_1) | Director "default recom is fine" (2026-04-23) |
