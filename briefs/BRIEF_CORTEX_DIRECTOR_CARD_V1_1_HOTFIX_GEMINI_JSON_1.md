# BRIEF: CORTEX_DIRECTOR_CARD_V1_1_HOTFIX_GEMINI_JSON_1 — fix Gemini 100% fallback rate on Phase 4.5 Director Card

## Context

PR #229 (merged 2026-05-20 12:26 as `d9065ae`) swapped Phase 4.5 from Haiku to Gemini 2.5 Pro primary + Sonnet 4.6 fallback. Live smoke immediately after deploy (cycle `dceaf71b-ca6f-4496-9d74-e30e4a3f9656`, oskolkov self-wake at 12:37Z) confirmed the fail-open contract works — but **100% of cards came back via the Sonnet fallback, not Gemini**.

Render log evidence at 12:37:15.820Z:
```
httpx | POST .../gemini-2.5-pro:generateContent → HTTP 200 OK
orchestrator.cortex_phase4_5_director_card | WARNING
  | [phase4_5] cycle dceaf71b...: gemini returned non-JSON; trying Sonnet fallback
```

Gemini was reached, auth fine, HTTP 200 — but the response body could not be parsed as JSON. The existing parser at `orchestrator/cortex_phase4_5_director_card.py:248-267` already strips leading code fences AND leading prose, so the body is corrupt past those two defenses.

Most likely root cause: `orchestrator/gemini_client.py:99-104` builds `GenerateContentConfig(max_output_tokens=max_tokens)` without `response_mime_type="application/json"`. Without that flag, Gemini 2.5 Pro is free to emit prose around the JSON (especially trailing prose, which the parser does NOT strip) OR truncate mid-JSON at `_MAX_TOKENS=600` because the 2.5 Pro "thinking" reserve consumes part of the output-token budget before any visible text streams.

Fail-open is doing exactly what it was designed to do — masking the issue with a graceful Sonnet fallback. But the cost-saving + quality lift from the Gemini swap is currently zero. Cost per card is $0.009 (Sonnet) vs target ~$0.002 (Gemini); 4-5x cost regression vs the v1.0 Haiku baseline ($0.0006).

Director ratified 2026-05-20: "Tier-A, I act" — AH1-authored hot-fix brief authorized.

### Surface contract: N/A — pure backend (Phase 4.5 module + Gemini client wrapper + tests). No UI, no API surface change, no DB schema change. End-user behavior already correct via fallback; this PR restores intended primary path.

## Estimated time: ~30-45 builder-minutes
## Complexity: Low
## Prerequisites
- PR #229 merged (`d9065ae`) — Phase 4.5 Gemini-primary scaffolding already in place.
- `GEMINI_API_KEY` set on Render `srv-d6dgsbctgctc73f55730` (verified 2026-05-20 — restored during the env-wipe sweep).
- `tools/render_env_guard.safe_env_put` + `.githooks/pre-commit` Part 4 both live (no env changes in this brief — safe to ignore).

## API version / deprecation / fallback
- **google-genai SDK:** verified at `orchestrator/gemini_client.py:28` (`from google import genai`). `types.GenerateContentConfig` supports `response_mime_type` as a field. Documented in google-genai SDK; takes string "application/json" to force strict-JSON output without fences or surrounding prose.
- **Gemini 2.5 Pro thinking-mode:** Pro models have an internal "thinking" reserve that consumes part of `max_output_tokens` before the visible response streams. `_MAX_TOKENS=600` is too tight for a 9-field card after the thinking reserve burns. Industry-standard headroom for 2.5 Pro + JSON-mode is 1500-2000 tokens.
- **Fallback path:** Sonnet 4.6 max_tokens at 600 is fine (no thinking overhead), but the Phase 4.5 code currently shares the constant across both paths. Sonnet hasn't shown truncation in smoke (it served the card cleanly), so the bump is for Gemini only — Sonnet can stay at 600 or be set to its own constant.

---

## Fix/Feature 1: Gemini JSON-mode + max_tokens headroom + trailing-prose parser

### Problem

`translate_to_director_card()` in `orchestrator/cortex_phase4_5_director_card.py` calls `gemini_generate(...)` (via `orchestrator.gemini_client.generate`). On live smoke `dceaf71b`:
- `generate()` succeeded — HTTP 200 from `gemini-2.5-pro:generateContent`.
- `getattr(resp, "text", "")` returned something non-empty (else fallback path would log "no client", not "non-JSON").
- `_parse_json_response(raw_text)` returned `None`.
- Phase 4.5 logged `gemini returned non-JSON; trying Sonnet fallback` and switched to Sonnet, which served a valid card.

Three weaknesses combine to cause this:
1. `gemini_client.generate()` doesn't pass `response_mime_type` — Gemini is free to wrap JSON in prose / fences / both.
2. `_MAX_TOKENS=600` is too tight for Gemini 2.5 Pro with thinking-mode active.
3. Parser strips LEADING fences + LEADING prose but not TRAILING prose (e.g., Gemini emitting `{...} Here is the JSON above.` would fail `json.loads`).

### Current state — file:line references (all verified by AH1 reading the file)

- `orchestrator/gemini_client.py:50-132` — `generate(model, messages, max_tokens=2000, system=None) -> GeminiResponse`. Builds `types.GenerateContentConfig(max_output_tokens=max_tokens)` at line 100; conditionally sets `gen_config.system_instruction = system` at line 104. **No `response_mime_type` is set on either the `generate()` path or the duplicate config block at line 243.**
- `orchestrator/cortex_phase4_5_director_card.py:30` — `_MAX_TOKENS = 600` (shared across Gemini + Sonnet paths).
- `orchestrator/cortex_phase4_5_director_card.py:248-267` — `_parse_json_response(raw)`:
  - Strips `^```(?:json)?` fence (line 256).
  - Strips `\n```$` fence (line 257).
  - Finds first `{` and slices from there (lines 259-263) — handles leading prose.
  - Strict `json.loads(s)` (line 265) — fails if `s` has trailing prose past the JSON's closing `}`.
- `orchestrator/cortex_phase4_5_director_card.py:300-345` — Gemini primary call site. Imports `generate as gemini_generate` inside the function, calls it with `max_tokens=_MAX_TOKENS`. No JSON-mode flag passed (would need a new param on `generate()`).

### Implementation

**A. `orchestrator/gemini_client.py` — add optional `response_format` param to `generate()`.**

Update signature + config build (lines 50-104). Add a fourth parameter, default `None`, that — when set to `"json"` — adds `response_mime_type="application/json"` to the `GenerateContentConfig`. Backward compatible: existing callers pass nothing → unchanged behavior.

```python
def generate(
    model: str,
    messages: list,
    max_tokens: int = 2000,
    system: str = None,
    response_format: str = None,    # NEW — "json" forces application/json mime
) -> GeminiResponse:
    """
    Call Gemini API with Claude-style message format.

    Args:
        model: "gemini-2.5-flash" or "gemini-2.5-pro"
        messages: [{"role": "user", "content": "..."}] — Claude format
        max_tokens: max output tokens
        system: system prompt (optional)
        response_format: "json" → set response_mime_type=application/json so
            Gemini emits strict JSON (no markdown fences, no prose preamble or
            trailing commentary). Other values: ignored.
    """
    from google.genai import types
    # ... (build contents — unchanged) ...

    # Build config
    gen_config = types.GenerateContentConfig(
        max_output_tokens=max_tokens,
    )
    if system:
        gen_config.system_instruction = system
    if response_format == "json":
        gen_config.response_mime_type = "application/json"
    # ... (retry loop — unchanged) ...
```

If `gen_config.response_mime_type = ...` doesn't take post-construction assignment in the SDK version on Render (some pydantic-v2 model configs are frozen), construct the config in one shot via kwargs:

```python
config_kwargs = {"max_output_tokens": max_tokens}
if system:
    config_kwargs["system_instruction"] = system
if response_format == "json":
    config_kwargs["response_mime_type"] = "application/json"
gen_config = types.GenerateContentConfig(**config_kwargs)
```

B-code picks the cleaner pattern based on what the SDK actually accepts; this is one of the things to verify before the test pass.

**B. `orchestrator/cortex_phase4_5_director_card.py` — bump max_tokens for Gemini + pass `response_format="json"`.**

Two constants instead of one. Keep `_MAX_TOKENS = 600` for Sonnet fallback (no thinking overhead, current behavior preserved); add `_MAX_TOKENS_GEMINI = 2000`.

```python
_MAX_TOKENS = 600                # Sonnet 4.6 fallback (unchanged from v1.0)
_MAX_TOKENS_GEMINI = 2000        # Gemini 2.5 Pro: covers thinking-mode reserve + 9-field card
```

Update the Gemini call site (around `orchestrator/cortex_phase4_5_director_card.py:310-320`, inside the `# --- Primary: Gemini 2.5 Pro ---` block):

```python
resp = gemini_generate(
    model=primary_model,
    messages=[{"role": "user", "content": user_text}],
    max_tokens=_MAX_TOKENS_GEMINI,
    system=SYSTEM_PROMPT,
    response_format="json",        # NEW — strict JSON mime
)
```

The Sonnet fallback block (around line 365) stays on `max_tokens=_MAX_TOKENS`.

**C. `orchestrator/cortex_phase4_5_director_card.py:_parse_json_response` — strip trailing prose too.**

Replace the function body (lines 248-267) to also handle JSON followed by trailing commentary. Walk the string finding the first `{` and its matching closing `}` (brace-balanced, string-aware), then `json.loads` only that slice:

```python
def _parse_json_response(raw: str) -> Optional[dict]:
    """Tolerate a model that wraps JSON in code-fences, adds a leading
    sentence, OR appends trailing commentary. Strict JSON only after the
    object boundary is identified."""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*\n", "", s)
        s = re.sub(r"\n```\s*$", "", s)
    # Find first '{' (handles leading prose).
    start = s.find("{")
    if start == -1:
        return None
    # Find the matching closing brace (handles trailing prose).
    depth = 0
    in_str = False
    escape = False
    end = -1
    for i, ch in enumerate(s[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return None
    try:
        return json.loads(s[start:end + 1])
    except (ValueError, json.JSONDecodeError):
        return None
```

**D. Tests — `tests/test_cortex_phase4_5_director_card.py`.**

Add three new test cases, each independently runnable:

1. `test_gemini_response_with_trailing_prose_parses` — feed `_install_gemini_stub` a response like `'{"matter":"X",...}\n\nHere is the JSON above for your review.'` (a valid 9-field card followed by trailing prose). Assert `card is not None`, `_meta.fallback_used is False`, Anthropic stub NOT called.
2. `test_gemini_response_with_fences_and_trailing_prose_parses` — feed `'```json\n{"matter":"X",...}\n```\n\nLet me know if you need anything.'`. Same assertions.
3. `test_parse_json_response_strips_trailing_prose_unit` — direct unit test on `_parse_json_response` with three fixtures: clean JSON, JSON + trailing prose, JSON + leading + trailing prose, JSON with `}` inside a string value (e.g., `'{"key":"value with } brace"}`) — assert the brace-balanced walk handles it.

Existing tests must still pass; the new parser is a superset of the old behavior.

### Key constraints

- **Do NOT change the Sonnet fallback path's max_tokens.** It works; leave 600 as `_MAX_TOKENS`.
- **Do NOT change `gemini_client.call_flash` / `call_pro` defaults.** They stay backward-compatible — `response_format` defaults to `None` so other callers (e.g., capability_runner) are unaffected.
- **Do NOT touch `SYSTEM_PROMPT`.** The prompt already says "Output ONLY a JSON object... No prose, no markdown" — the issue is API-level enforcement, not prompt drift. Tightening the prompt without the mime-type flag is theater.
- **Do NOT touch the schema validator or sanitizer.** Both work; the failure mode is parsing, not validation.
- **Do NOT add Gemini retry logic on parse failure.** The Sonnet fallback already handles it. Adding a retry doubles cost on legit Gemini failures.
- **Singleton pattern unchanged** — `_get_anthropic_fallback_client` + `_get_client` (in gemini_client.py) stay as-is.

### Verification

1. **Literal pytest run:**
   ```
   pytest tests/test_cortex_phase4_5_director_card.py -v
   ```
   Paste full output in ship report. All existing tests must still pass, plus the 3 new ones added in step D.

2. **py_compile both modified files:**
   ```
   python3.12 -c "import py_compile; py_compile.compile('orchestrator/gemini_client.py', doraise=True); py_compile.compile('orchestrator/cortex_phase4_5_director_card.py', doraise=True); print('compile OK')"
   ```

3. **Singletons CI guard:**
   ```
   bash scripts/check_singletons.sh
   ```
   Must report `OK: No singleton violations found.`

4. **Post-merge live smoke (AH1 runs after merge):**
   - Fire a self_wake_smoke cycle via `POST /api/cortex/trigger` with matter `oskolkov`.
   - Query `cortex_phase_outputs` filtered to `artifact_type='director_card'` + `created_at > NOW() - INTERVAL '5 minutes'`.
   - Assert `payload->'_meta'->>'model' = 'gemini-2.5-pro'` AND `payload->'_meta'->>'fallback_used' = 'false'`.
   - Render logs in the cycle window must contain ZERO `[phase4_5]` warnings (no fallback fires on healthy path).

---

## Files Modified

- `orchestrator/gemini_client.py` — `generate()` gains optional `response_format: str = None` param; when `"json"`, adds `response_mime_type="application/json"` to `GenerateContentConfig`. Backward compatible.
- `orchestrator/cortex_phase4_5_director_card.py`:
  - New constant `_MAX_TOKENS_GEMINI = 2000` (next to existing `_MAX_TOKENS = 600`).
  - Gemini primary call passes `max_tokens=_MAX_TOKENS_GEMINI` + `response_format="json"`.
  - `_parse_json_response` rewritten to brace-balance the JSON object (strips trailing prose in addition to existing leading-prose + fence stripping).
- `tests/test_cortex_phase4_5_director_card.py` — 3 new tests for the parser + Gemini-primary path with messy responses.

## Do NOT Touch

- `SYSTEM_PROMPT` — prompt is fine; enforcement is the issue.
- `_sanitize_card` / `_validate_card_schema` — unrelated to the parsing failure.
- `_compute_gemini_pro_cost_eur` / `_compute_sonnet_cost_eur` — token math unaffected.
- Sonnet fallback block (`_MAX_TOKENS=600` constant + `client.messages.create` call) — keep verbatim.
- `outputs/dashboard.py` smoke filter — pure UI, unrelated.
- Any other consumer of `gemini_client.generate` / `call_flash` / `call_pro` (e.g., `orchestrator/capability_runner.py`, the auto-insight extraction path) — backward-compatible param addition only.

## Quality Checkpoints

1. Literal `pytest tests/test_cortex_phase4_5_director_card.py -v` output in ship report — no "pass by inspection".
2. New tests (#1, #2, #3 in step D) added + green; old tests still green.
3. `bash scripts/check_singletons.sh` OK.
4. Pre-commit hook Part 4 passes (no raw `/env-vars` PUT in diff — there shouldn't be any).
5. `py_compile` clean on both modified files.
6. Manual diff inspection: `response_format` param has default `None`, so capability_runner + auto-insight callers are unaffected.

## Anti-pattern checks (lessons.md applied proactively)

| Anti-pattern | Applied mitigation |
|---|---|
| Brief code snippet wrong signature | Verified `generate()` signature at gemini_client.py:50-65 + `_parse_json_response` at cortex_phase4_5_director_card.py:248-267 by Read tool before drafting snippets |
| Gemini call pattern three-way match | Preserved: `messages=[{"role":"user","content":...}]` + returns `GeminiResponse` with `.text` + `.usage` — unchanged |
| Function name guessing | Brief references `gemini_generate` (import alias used in cortex_phase4_5_director_card.py) — verified |
| Missing import | `re` already imported in cortex_phase4_5_director_card.py (line 5 — verified); `types` already imported inside `generate()` (line 65) |
| Render restart survival | Stateless config-only change; no state to lose |
| Cost impact | Negligible: `response_mime_type` is free; `_MAX_TOKENS_GEMINI=2000` only matters for output tokens actually emitted (a 9-field card is ~300-500 tokens regardless of cap). No new API calls |
| Blast radius | Low: `response_format` defaults to None → other callers unchanged. If `response_mime_type` assignment somehow raises in the SDK, outer try/except catches → Sonnet fallback (current degraded but functional behavior preserved) |
| Untracked briefs | This brief will be `git add`'ed before commit |
| Secrets in brief | None — only env-var names referenced |

## Branch / PR

- Branch: `b1/cortex-director-card-v1-1-hotfix-gemini-json-1`
- PR title: `fix(phase4_5): Gemini JSON-mode + max_tokens headroom + trailing-prose parser (V1.1 hot-fix)`
- Reply target on PR open: bus-post `lead` topic `ship/cortex-director-card-v1-1-hotfix-gemini-json-1`.

## Reporting

`dispatched_by: lead` — bus-post `lead` on PR open per brief-reply-to-sender rule (2026-05-17 ratification).

## Anchors

- PR #229 merge — `d9065ae`, merged 2026-05-20 12:26:38Z.
- Live smoke cycle that exposed the bug — `dceaf71b-ca6f-4496-9d74-e30e4a3f9656`, oskolkov self_wake_smoke at 12:37:23Z.
- Render log evidence — `[phase4_5] cycle dceaf71b...: gemini returned non-JSON; trying Sonnet fallback` at 12:37:15.820Z.
- google-genai SDK `GenerateContentConfig.response_mime_type` — standard JSON-mode toggle; takes `"application/json"`.
- Gemini 2.5 Pro thinking-mode — consumes part of `max_output_tokens` reserve before visible response streams; documented in google-genai docs.
- Director ratification path — 2026-05-20 chat: "Tier-A, I act" (AH1 dispatched without per-action ask per autonomy charter §3).
