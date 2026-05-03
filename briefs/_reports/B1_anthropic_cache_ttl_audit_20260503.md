# B1 — Anthropic prompt cache TTL audit (diagnostic, no code change)

**Date:** 2026-05-03 · **Dispatcher:** AH1 · **Effort:** ~30 min · **Verdict:** **Upgrade recommended for inter-cycle reuse on same matter (esp. oskolkov).** Median intra-phase gaps fit 5-min default; inter-cycle gaps on AO sit at ~21.6 min — squarely in the 5-min-to-1-hr window where extended cache pays off.

---

## 1. Current cache TTL on baker-master (main, commit `acbb9ad`)

**Result: default 5-minute ephemeral cache. No 1-hour extended-cache header in any call path.**

`cache_control={"type": "ephemeral"}` is shipped at four hot sites:

| File | Line | Block |
|---|---|---|
| `kbl/anthropic_client.py` | 238 | `system_blocks` for `call_opus()` — central wrapper |
| `outputs/dashboard.py` | 67 | Scan endpoint stable-prefix split (PROMPT_CACHE_AUDIT_1) |
| `orchestrator/capability_runner.py` | 41 | Capability system blocks |
| `baker_rag.py` | 214 | RAG path |

The `ttl` field is **not** set on any of these `cache_control` dicts → SDK uses Anthropic default `5m` ephemeral.

The only beta header in flight is `context-1m-2025-08-07` (1M context window, separate feature):
- `outputs/dashboard.py:43` — `extra_headers={"anthropic-beta": config.claude.beta_header}` gated on `model == config.claude.model`
- `baker_rag.py:217`, `orchestrator/pipeline.py:521` — same pattern
- `config/settings.py:48` — `beta_header: str = "context-1m-2025-08-07"`

No `extended-cache-ttl-2025-04-11` (or equivalent 1-hr cache beta header) anywhere in the tree.

---

## 2. Cycle gap analysis (last 20 completed cycles)

Source: `cortex_cycles` + `cortex_phase_outputs` joined on `cycle_id`. 15 cycles with ≥2 phase outputs in the analysis window (2026-04-28 → 2026-05-02).

### Intra-cycle phase-to-phase gaps (n=134 gaps)

| Stat | Seconds | Bucket |
|---|---|---|
| min | 0.0 (-176542 outliers from out-of-order writes) | — |
| median | **13.6** | 5-min ✅ |
| p90 | **181.6** | 5-min ✅ (~3 min) |
| p95 | 22 687 | 1-hr ❌ (~6.3h — Director-await tail) |
| max | 176 542 | — |
| n gaps > 5 min | 13/134 (9.7%) | — |
| n gaps > 1 hr | 11/134 (8.2%) | — |

**Read:** ~90% of intra-cycle phase transitions complete inside the 5-min cache window already. The ~10% tail is mostly `awaiting_reason` / `tier_b_pending` Director-decision waits that exceed even 1 hr — extended cache wouldn't recover those either.

### Inter-cycle gaps (per matter)

| matter | cycles | gaps | median inter-cycle | within 5min | 5min–1hr | over 1hr |
|---|---|---|---|---|---|---|
| **oskolkov** | 17 | 16 | **1295 s (~21.6 min)** | 4 | **9** | 3 |
| hagenauer-rg7 | 3 | 2 | 60 699 s (~16.9h) | 0 | 1 | 1 |
| Financing Vienna & Baden-Baden | 1 | 0 | — | — | — | — |
| German Property Tax | 1 | 0 | — | — | — | — |
| movie | 1 | 0 | — | — | — | — |
| nvidia-corinthia | 1 | 0 | — | — | — | — |

**Read:** Oskolkov is the only matter with non-trivial inter-cycle traffic in the window. **9 of 16 oskolkov inter-cycle gaps fall in the 5-min-to-1-hr band** — exactly the window extended (1-hr) cache would convert from miss → hit.

Caveat: most oskolkov cycles in the dataset are the 2026-04-28 evening AO bug-bash batch (~17 close-spaced cycles for ratification testing). In steady state the inter-cycle cadence per matter is much sparser. The 1295 s median is debug-batch-skewed.

---

## 3. Cost shape (last 20 cycles with cost_dollars > 0)

Largest cycles by `cost_dollars`:

| matter | status | $ | tokens |
|---|---|---|---|
| oskolkov (rejected) | 4.00 | 246 659 |
| hagenauer-rg7 (approved) | 3.46 | 198 967 |
| oskolkov (tier_b_pending) | 3.22 | 179 808 |
| nvidia-corinthia (approved) | 2.58 | 140 951 |
| hagenauer-rg7 (approved) | 1.46 | 80 460 |

Several cycles run 150K-250K input tokens. With Opus base input pricing, the system-block prefix (multi-K stable) gets re-sent on every cache miss. **A single cache miss on a 50K-token capability template costs ~$0.75 of input**, vs ~$0.075 on a hit.

---

## 4. Upgrade path if AH1 wants to flip 1-hr cache

**No code change in this dispatch.** Pointer for follow-up brief:

1. **Add beta header to extra_headers** at the 3+1 hot sites already carrying `cache_control` (or push it into `kbl/anthropic_client.py` _get_client() so it lands on every Anthropic call automatically):
   ```python
   extra_headers={"anthropic-beta": "extended-cache-ttl-2025-04-11"}
   ```
   (verify exact header string against current Anthropic SDK docs at brief-write time — the API surface for 1-hr cache changed shape ~2025-04 and could change again)

2. **Set ttl on cache_control block:**
   ```python
   {"type": "text", "text": stable, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
   ```

3. **Cost delta math (per Anthropic prompt-cache pricing):**
   - Cache write: **2.0× base input** (1-hr) vs **1.25× base** (5-min) → +0.75× of base on each first call per matter (after which TTL is rolling)
   - Cache read: **0.1× base** in both cases → flat
   - **Break-even: any matter with ≥1 cycle within 1 hr of a prior cycle**

4. **Expected savings on oskolkov-shaped traffic:**
   - 9 inter-cycle gaps in 5min–1hr window. Each currently misses (full re-encode of ~50-200K-token system prefix at full input price).
   - If oskolkov's average system block is ~50K tokens (capability + curated knowledge layer), the saved input on 9 hit conversions ≈ **9 × 50K × (1.0 - 0.1) base input price** = ~$4-5 saved per debug batch (Opus pricing).
   - Plus reduced first-cycle write tax of +0.75× on the first cycle: ~+$0.4-1 per matter per cache-write event.
   - Net positive when matters see ≥2 cycles within 1 hr — easily met during AO Step 30 LIVE runs and Director ratification batches.

5. **Concentrate the change in one place:** flip `_get_client()` / `call_opus()` in `kbl/anthropic_client.py` so all four hot sites inherit the new TTL without per-site touch. Matches existing Lesson #50 single-source pattern.

---

## 5. Non-blockers / data hygiene flags (for AH1 awareness)

- `cortex_phase_outputs` has occasional **negative inter-row deltas** when ordered by `(phase_order, created_at)` — suggests phase artifacts being written slightly out-of-order vs phase_order column. Not affecting cache analysis (negative deltas excluded by `gap_s > 0` selection on the ranking percentiles); flagging only.
- `cortex_cycles.completed_at` for several long-running cycles equals `2026-04-30 23:55:xx` cluster — looks like a sweep/finalize job stamping batch closure rather than per-cycle natural close. Inflates `cycle_seconds` for those rows. The phase-span gap analysis above is more representative of actual machine work.
- The only cycles that completed in clean 5-min-floor time (~250-300s) are the early oskolkov "failed" batch — these failed at the 5-min cycle umbrella from `orchestrator/cortex_phase3_invoker.py:111`. Cache TTL is unrelated.

---

## 6. Recommendation

**Queue follow-up brief: flip extended-cache-ttl on `kbl/anthropic_client.py` _get_client() once Step 30 LIVE AO cadence stabilizes.** Don't ship before Step 30 first LIVE cycle — too many unknowns about prod cache hit-rate post-stabilization.

After Step 30 + 1 week observation, re-run this audit; if the steady-state inter-cycle gap median moves into the 5-min-to-1-hr band on the active matters (likely once Cortex auto-trigger lands), the brief is greenlit. If steady-state inter-cycle gaps cluster either <5 min (cache already covered) or >>1 hr (cache irrelevant), no upgrade needed.

Diagnostic only — no code change in this dispatch per AH1 instructions.
