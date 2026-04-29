# BRIEF: CORTEX_MULTI_MATTER_GATE_1 — Cost-gate whitelist by `cortex-config.md` presence

## Context

`triggers/cortex_pre_review_gate.post_gate()` today posts the cost gate for **any** `matter_slug` passed in. The de-facto AO-only behaviour comes from upstream — only the `oskolkov` matter has `baker-vault/wiki/matters/<slug>/cortex-config.md` (verified 2026-04-29: only `oskolkov/cortex-config.md` exists; `hagenauer-rg7`, `kitzbuhel-six-senses`, `movie` folders are config-less).

Wave 1 Tracks 3 + 4 will land `cortex-config.md` for `hagenauer-rg7` and `nvidia-corinthia` shortly. Once those files exist, Cortex must be willing to gate-and-fire on those matters too — and refuse to gate on matters without configs (no point asking Director "approve $4 cycle?" if Phase 2 has nothing to load).

Wave 1 Track 2 per V3 rev 4 roadmap.

## Estimated time: ~2-3h (build 1h + tests 45min + B1 review 30min + post-deploy smoke 15min)
## Complexity: Low-Medium
## Trigger class: HIGH (modifies cost-gate write path; gate disable = uncontrolled spend risk)

→ B1 situational review REQUIRED per RA-24 (cost-bearing trigger surface).

**Build assignment:** B3 (`~/bm-b3`). **Review assignment:** B1 (formal) + AI Head A (`/security-review` + structural).

---

## Behavior change

### Before (current LIVE state)

```
maybe_trigger_cortex(signal_id, matter_slug=anything)
  → if CORTEX_GATE_ENABLED: post_gate(signal_id, matter_slug)
  → post_gate posts Slack DM regardless of whether matter has a cortex-config
  → Director taps approve → Phase 2 has no per-matter brain to load → garbage cycle
```

### After

```
post_gate(signal_id, matter_slug)
  → matter_has_cortex_config(matter_slug)?
      no  → log info "matter not Cortex-enabled"; return False (caller skips cycle)
      yes → read cost_estimate_dollars from frontmatter (default $4)
            post Slack DM with "Approx cost: $X" reflecting per-matter config
            existing approve/skip flow unchanged
```

Single source of truth: presence of `<vault>/wiki/matters/<slug>/cortex-config.md`.

---

## Implementation

### File 1: MODIFY `triggers/cortex_pre_review_gate.py`

Add module-level helpers + change `post_gate` body. Keep all existing tested behaviour (HMAC, idempotency, Slack unfurl=False, schema-correct `summary`/`matter` columns).

```python
import os
from pathlib import Path
from typing import Optional, Tuple

# ... existing imports / constants ...

DEFAULT_COST_ESTIMATE_DOLLARS = float(
    os.environ.get("CORTEX_DEFAULT_COST_DOLLARS", "4.0")
)


def _vault_root() -> Optional[Path]:
    """Return Path(BAKER_VAULT_PATH) or None if unset/invalid.

    On Render the env var points at the baker-vault-mirror checkout
    (e.g. /opt/render/project/src/baker-vault-mirror). On B-code worktrees,
    /Users/dimitry/baker-vault. Tests set it to a tmp path.
    """
    raw = os.environ.get("BAKER_VAULT_PATH", "").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_dir() else None


def matter_has_cortex_config(matter_slug: str) -> bool:
    """True iff <vault>/wiki/matters/<matter_slug>/cortex-config.md exists.

    Single source of truth for 'is this matter Cortex-enabled'. Used by the
    pre-review gate AND by /api/cortex/run rate-limit upstream (future).
    """
    if not matter_slug:
        return False
    root = _vault_root()
    if not root:
        return False
    cfg = root / "wiki" / "matters" / matter_slug / "cortex-config.md"
    return cfg.is_file()


def _read_cost_estimate(matter_slug: str) -> float:
    """Read 'cost_estimate_dollars' from cortex-config.md frontmatter, else default.

    Lightweight YAML-free parse — line-based on '---'-delimited frontmatter.
    Avoids pulling in yaml just for one optional float.
    """
    root = _vault_root()
    if not root:
        return DEFAULT_COST_ESTIMATE_DOLLARS
    cfg = root / "wiki" / "matters" / matter_slug / "cortex-config.md"
    if not cfg.is_file():
        return DEFAULT_COST_ESTIMATE_DOLLARS
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            return DEFAULT_COST_ESTIMATE_DOLLARS
        end = text.find("\n---", 3)
        if end < 0:
            return DEFAULT_COST_ESTIMATE_DOLLARS
        fm = text[3:end]
        for line in fm.splitlines():
            line = line.strip()
            if line.startswith("cost_estimate_dollars:"):
                val = line.split(":", 1)[1].strip()
                try:
                    return float(val)
                except ValueError:
                    return DEFAULT_COST_ESTIMATE_DOLLARS
        return DEFAULT_COST_ESTIMATE_DOLLARS
    except Exception as e:
        logger.error("read_cost_estimate failed matter=%s: %s", matter_slug, e)
        return DEFAULT_COST_ESTIMATE_DOLLARS
```

**Modify `post_gate` body** — insert whitelist check + use dynamic cost in Slack text:

```python
def post_gate(*, signal_id: int, matter_slug: str) -> bool:
    """Post the pre-review gate Slack DM. Returns True if posted.

    CORTEX_MULTI_MATTER_GATE_1: only posts when the matter has a
    cortex-config.md. Without config, Phase 2 has nothing to load — gate
    skipped, caller falls through (legacy direct-fire still respects
    CORTEX_LIVE_PIPELINE so this stays safe).
    """
    if already_decided(signal_id):
        logger.info("gate skipped — signal_id=%s already decided", signal_id)
        return False

    # NEW: whitelist by config presence
    if not matter_has_cortex_config(matter_slug):
        logger.info(
            "gate skipped — matter=%s has no cortex-config.md (signal_id=%s)",
            matter_slug, signal_id,
        )
        return False

    if _secret() is None:
        logger.error(
            "CORTEX_GATE_SECRET unset/short — gate disabled, signal_id=%s",
            signal_id,
        )
        return False

    cost = _read_cost_estimate(matter_slug)
    expires_at = int(time.time()) + GATE_TTL_SECONDS
    approve_tok = sign_token(signal_id=signal_id, action="approve", expires_at=expires_at)
    skip_tok = sign_token(signal_id=signal_id, action="skip", expires_at=expires_at)
    approve_url = (
        f"{PUBLIC_BASE_URL}/api/cortex/gate/decide"
        f"?signal_id={signal_id}&action=approve&exp={expires_at}&token={approve_tok}"
    )
    skip_url = (
        f"{PUBLIC_BASE_URL}/api/cortex/gate/decide"
        f"?signal_id={signal_id}&action=skip&exp={expires_at}&token={skip_tok}"
    )

    preview = _signal_preview(signal_id)
    text = (
        f"📨 *New {matter_slug.upper()} signal — review with Cortex?*\n"
        f"Approx cost: ${cost:.2f} if approved.\n"
        f"\n*Preview:*\n>>> {preview}\n"
        f"\n<{approve_url}|✅ Yes, review (~${cost:.2f})>   |   "
        f"<{skip_url}|❌ Skip>"
    )

    try:
        from outputs.slack_notifier import post_to_channel
        return bool(post_to_channel(
            DIRECTOR_DM_CHANNEL, text,
            unfurl_links=False, unfurl_media=False,
        ))
    except Exception as e:
        logger.error("post_gate Slack post failed signal_id=%s: %s", signal_id, e)
        return False
```

### File 2: MODIFY `triggers/cortex_pipeline.py`

**Already correct** — when `post_gate` returns False AND `_secret()` is set AND `already_decided` is None, the existing logic logs warning + skips cycle. The new return-False-on-no-config case falls into that branch naturally (no spend, no error).

**Verify no change needed** by reading lines 64-92 again. If the existing branching does NOT cleanly handle "False from no-config" without runaway, add a single conditional:

```python
            # After existing post_gate call returns False:
            if not matter_has_cortex_config(matter_slug):
                # Matter not Cortex-enabled — explicit early return, no spend
                logger.info(
                    "cortex pipeline: matter=%s not Cortex-enabled (no config); skipping",
                    matter_slug,
                )
                return
```

**Decision for builder (B3):** read the existing `maybe_trigger_cortex` once and judge whether the explicit early-return is needed for clarity OR whether the existing "post_gate False + secret set" branch already covers the no-config case. Document the call in your ship report.

### File 3: MODIFY `tests/test_cortex_pre_review_gate.py`

Add tests (extend the existing 10-test suite):

```python
# Test 11 — matter_has_cortex_config positive
def test_matter_has_cortex_config_positive(monkeypatch, tmp_path):
    (tmp_path / "wiki" / "matters" / "oskolkov").mkdir(parents=True)
    (tmp_path / "wiki" / "matters" / "oskolkov" / "cortex-config.md").write_text(
        "---\nmatter_slug: oskolkov\n---\n", encoding="utf-8",
    )
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    import importlib, triggers.cortex_pre_review_gate as g
    importlib.reload(g)
    assert g.matter_has_cortex_config("oskolkov") is True


# Test 12 — matter_has_cortex_config negative (no config file)
def test_matter_has_cortex_config_negative(monkeypatch, tmp_path):
    (tmp_path / "wiki" / "matters" / "hagenauer-rg7").mkdir(parents=True)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    import importlib, triggers.cortex_pre_review_gate as g
    importlib.reload(g)
    assert g.matter_has_cortex_config("hagenauer-rg7") is False


# Test 13 — matter_has_cortex_config returns False when BAKER_VAULT_PATH unset
def test_matter_has_cortex_config_no_vault(monkeypatch):
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    import importlib, triggers.cortex_pre_review_gate as g
    importlib.reload(g)
    assert g.matter_has_cortex_config("oskolkov") is False


# Test 14 — _read_cost_estimate from frontmatter
def test_read_cost_estimate_from_frontmatter(monkeypatch, tmp_path):
    (tmp_path / "wiki" / "matters" / "movie").mkdir(parents=True)
    (tmp_path / "wiki" / "matters" / "movie" / "cortex-config.md").write_text(
        "---\nmatter_slug: movie\ncost_estimate_dollars: 7.50\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    import importlib, triggers.cortex_pre_review_gate as g
    importlib.reload(g)
    assert abs(g._read_cost_estimate("movie") - 7.50) < 1e-6


# Test 15 — _read_cost_estimate falls back to default when field absent
def test_read_cost_estimate_default(monkeypatch, tmp_path):
    (tmp_path / "wiki" / "matters" / "ao").mkdir(parents=True)
    (tmp_path / "wiki" / "matters" / "ao" / "cortex-config.md").write_text(
        "---\nmatter_slug: ao\n---\n", encoding="utf-8",
    )
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("CORTEX_DEFAULT_COST_DOLLARS", "4.0")
    import importlib, triggers.cortex_pre_review_gate as g
    importlib.reload(g)
    assert abs(g._read_cost_estimate("ao") - 4.0) < 1e-6


# Test 16 — post_gate skips when matter has no config
def test_post_gate_skips_no_config(monkeypatch, tmp_path):
    monkeypatch.setenv("CORTEX_GATE_SECRET", "test-secret-32-characters-long-XX")
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))  # vault exists but no matter dirs
    import importlib, triggers.cortex_pre_review_gate as g
    importlib.reload(g)
    with patch("triggers.cortex_pre_review_gate.already_decided", return_value=None), \
         patch("outputs.slack_notifier.post_to_channel") as mock_post:
        ok = g.post_gate(signal_id=999, matter_slug="hagenauer-rg7")
    assert ok is False
    mock_post.assert_not_called()


# Test 17 — post_gate fires when matter has config; cost reflects frontmatter
def test_post_gate_fires_with_config_and_cost(monkeypatch, tmp_path):
    (tmp_path / "wiki" / "matters" / "movie").mkdir(parents=True)
    (tmp_path / "wiki" / "matters" / "movie" / "cortex-config.md").write_text(
        "---\nmatter_slug: movie\ncost_estimate_dollars: 6.00\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CORTEX_GATE_SECRET", "test-secret-32-characters-long-XX")
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    import importlib, triggers.cortex_pre_review_gate as g
    importlib.reload(g)
    with patch("triggers.cortex_pre_review_gate.already_decided", return_value=None), \
         patch("triggers.cortex_pre_review_gate._signal_preview", return_value="preview"), \
         patch("outputs.slack_notifier.post_to_channel", return_value=True) as mock_post:
        ok = g.post_gate(signal_id=42, matter_slug="movie")
    assert ok is True
    assert mock_post.call_count == 1
    posted_text = mock_post.call_args[0][1]
    assert "$6.00" in posted_text
```

---

## Key Constraints

- DO NOT change `sign_token`/`verify_token`/`record_decision`/`already_decided` — all PR #66+#75 hardening stays.
- DO NOT YAML-import — use the line-based frontmatter parse to avoid a new dep.
- DO NOT log frontmatter content beyond cost (potential matter intel).
- DO NOT add a new env var beyond `CORTEX_DEFAULT_COST_DOLLARS` (optional, default `4.0`).
- DO NOT touch `outputs/dashboard.py` `/api/cortex/gate/decide` endpoint — Track 1's `/api/cortex/run` is the only dashboard work, and that's owned by Brief 1 (B1 builder). No race.
- DO NOT pre-create cortex-config files for hagenauer-rg7 / nvidia-corinthia — Tracks 3 + 4 own those.

## Quality Checkpoints

1. `python3 -c "import py_compile; py_compile.compile('triggers/cortex_pre_review_gate.py', doraise=True)"` clean
2. `pytest tests/test_cortex_pre_review_gate.py -v` — full suite (existing 10 + 7 new = 17/17 PASS literal)
3. Regression: `pytest tests/test_cortex_pipeline.py tests/test_alerts_to_signal_cortex_dispatch.py -v` PASS
4. `bash scripts/check_singletons.sh` clean
5. `pytest tests/test_cortex_pre_review_gate.py::test_post_gate_disables_slack_unfurl -v` — Test 10 STILL passes (no regression on unfurl=False contract)
6. Post-deploy: BAKER_VAULT_PATH set on Render to baker-vault-mirror; smoke shows AO signal → gate fires; `hagenauer-rg7` (config-less) signal → gate skips with info log

## Post-deploy verification (AI Head)

```bash
# After Render redeploys + post-deploy hagenauer-rg7 cortex-config lands (Track 3):
# Insert a fake hagenauer-rg7 signal_queue row + call maybe_dispatch
# → expect Slack DM with "$X.XX" cost reflecting hagenauer-rg7 frontmatter
# Insert a kitzbuhel-six-senses signal (config-less) row
# → expect NO Slack DM; logs show "matter=kitzbuhel-six-senses has no cortex-config.md"
```

```sql
SELECT action_type, target_task_id, payload, created_at
FROM baker_actions
WHERE action_type LIKE 'cortex:gate:%'
  AND created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC LIMIT 10;
```

## Files Modified / Added

- `triggers/cortex_pre_review_gate.py` — modified (+ ~80 LOC: 2 helpers + post_gate diff)
- `triggers/cortex_pipeline.py` — possibly modified (+ ~5 LOC; B3's call per builder note)
- `tests/test_cortex_pre_review_gate.py` — modified (+ ~150 LOC, 7 new tests)

## Do NOT Touch

- `outputs/dashboard.py` — out of scope (Brief 1 owns it; do not race).
- `orchestrator/cortex_runner.py` — out of scope.
- `kbl/bridge/alerts_to_signal.py` — out of scope; matter routing into `signal_queue.matter` stays.
- Existing PR #66 / PR #75 contracts (HMAC, idempotency, unfurl=False) — unchanged.

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
