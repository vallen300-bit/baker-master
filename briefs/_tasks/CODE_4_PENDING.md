---
status: REQUEST_CHANGES_ROUND_1
pr: 213
pr_head_before_changes: 26dc3dc
brief: briefs/BRIEF_CLAIMSMAX_API_CAPABILITY_1.md
brief_id: CLAIMSMAX_API_CAPABILITY_1
trigger_class: MEDIUM (new external API surface + new MCP tools + new migration; mandatory 2nd-pass review)
target_branch: b4/claimsmax-api-capability-1
matter_slug: claimsmax
cross_matter_usage: [mo-vie-am, hagenauer-rg7, cupial, ao, baker-internal]
dispatched_at: 2026-05-16T20:55:00Z
dispatched_by: AH1
director_auth: 2026-05-16 chat — "Please go ahead and write it into Baker's as a permanent capability"
prior_brief_complete: |
  PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1 shipped as PR #209 (merge_commit
  a13b2c9, 2026-05-16T13:30:00Z, ah1_merge_msg bus #305). Ship report
  preserved in briefs/_reports/B4_PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1_20260516.md.
  This dispatch overwrites the mailbox slot with the new brief.
ship_round_1:
  pr_opened_at: 2026-05-17T10:21:34Z
  pr_open_bus: 324
  tests: 28/28 green (Py3.12 literal)
  ship_report: briefs/_reports/B4_CLAIMSMAX_API_CAPABILITY_1_20260517.md
request_changes_round_1:
  at: 2026-05-17T10:35:00Z
  by: ai-head-1 (AH1)
  pr_comment: https://github.com/vallen300-bit/baker-master/pull/213#issuecomment-4470314931
  gates_fired:
    - gate-3-architect (code-architecture-reviewer): PASS-WITH-NITS but 1 CRITICAL
    - gate-4-code-reviewer (feature-dev:code-reviewer): PASS-WITH-NITS but 2 HIGHs
    - gate-2-ah2: pending (bus #326 to deputy, no reply yet — independent track)
  findings:
    critical:
      - id: C1
        file: migrations/20260517_claimsmax_capability_set.sql:32-38
        title: capability_type=domain + generic triggers hijack Cortex Phase 3 to tool-less hallucination
        why: |
          capability_type='domain' loads via cortex_phase3_reasoner._load_active_domain_capabilities (line 82).
          Tools=baker_claimsmax_* live in MCP surface, NOT in TOOL_DEFINITIONS used by capability_runner._get_filtered_tools (line 2198-2205). Filter returns []. Opus runs tool-less → hallucinates ClaimsMax results.
          capability_registry.match_trigger (line 145-155) iterates domain rows. Triggers "evidence" + "investigate" hijack "what's the evidence on Hagenauer?" queries.
        fix: |
          1. Change capability_type from 'domain' to 'archive' (new bucket; non-Cortex-invocable; MCP-only invocation by matter Desks).
          2. Drop generic triggers "evidence" and "investigate" from trigger_patterns. Keep narrow: ["claimsmax", "Pagitsch", "Hagenauer.*defects"].
          3. Verify 'archive' bucket is NOT loaded by cortex_phase3_reasoner. If capability_type is free-form text, 'archive' is no-op for Cortex (filter is WHERE capability_type='domain'). If ENUM, add the new value first.
    high:
      - id: H1
        file: kbl/report_renderer.py:114-116 (convert_to_pdf)
        title: convert_to_pdf orphans .md files in Director Dropbox on every call
        why: |
          _prepare_markdown_sibling materialises .md in Director's live Dropbox folder (1_ACTIVE_PROJECTS/<matter>/research/).
          convert_to_html cleans up via finally: md_path.unlink() (lines 144-148).
          convert_to_pdf does no cleanup → .md litter accumulates permanently in Director's research folders.
        fix: |
          Mirror convert_to_html try/finally cleanup pattern:
            def convert_to_pdf(json_path, *, pandoc_bin=None) -> str:
                md_path, pdf_path = _prepare_markdown_sibling(json_path, suffix=".pdf")
                try:
                    _pandoc_render(md_path, pdf_path, mode="pdf", pandoc_bin=pandoc_bin)
                finally:
                    try: md_path.unlink()
                    except OSError: pass
                return str(pdf_path)
      - id: H2
        file: kbl/report_renderer.py:53 (_DOCS_SITE_ROOT)
        title: _DOCS_SITE_ROOT hard-coded to legacy ~/Desktop/baker-code/docs-site
        why: |
          AH1 picker moved to ~/bm-aihead1/ on 2026-05-08. B-codes at ~/bm-bN/. Render container has no Desktop dir.
          HTML conversion either splits-brain across worktrees OR creates ghost path under /root/Desktop on Render and returns silent "success".
        fix: |
          Resolve via env var BAKER_DOCS_SITE_ROOT with no-default; raise RendererUnavailableError if unset/unreachable:
            _DOCS_SITE_ROOT = (
                Path(os.environ["BAKER_DOCS_SITE_ROOT"]).expanduser()
                if "BAKER_DOCS_SITE_ROOT" in os.environ else None
            )
          # In convert_to_html: if _DOCS_SITE_ROOT is None or not (parent.exists() and writable): raise RendererUnavailableError
          AH1 will set BAKER_DOCS_SITE_ROOT on Mac Mini LaunchAgent + on AH1 picker shell post-merge (Tier-A; mac-local only since convert is Director-gated).
    medium:
      - M1 — kbl/claimsmax_client.py:129-136 — httpx.Client per-request defeats /investigate polling pool (47+ TLS handshakes). Promote to instance state.
      - M2 — kbl/report_renderer.py:87-103 — matter_slug/topic_slug path-traversal unsafe. Add: if ".." in Path(matter_slug).parts: raise ValueError.
      - M3 — kbl/report_renderer.py:227 — pandoc subprocess no timeout. Add timeout=120.
      - M4 — tools/claimsmax.py:208,218,227,232 — dispatch_claimsmax constructs ClaimsmaxClient per call. Cache at module level (lazy init).
      - M5 — tools/claimsmax.py:270-292 — _format_search_result drops l3 from slim projection but l3_tags_required is filterable input. Add l3.
      - M6 — tools/claimsmax.py:263-264 — dispatch_claimsmax swallows programming errors via generic Exception. Add logger.exception(...) before return string.
    low:
      - L1 — kbl/claimsmax_client.py:125,161 — dead variable last_429
      - L2 — kbl/report_renderer.py:47-52 — _DROPBOX_ROOT hard-coded; same fix pattern as H2
      - L3 — PDF conversion docstring should note pandoc + pdflatex/xelatex requirement, not pandoc alone
      - L4 — migration output_format='prose' inconsistent with JSON-returning tools (cosmetic)
      - L5 — page + sort exposed on ClaimsmaxClient.search but not in MCP tool schema (pagination invisible to agents)
      - L6 — 3 ClaimsmaxClient methods unreachable via MCP (investigate_events, get_document_text, get_document_download_url) — document intent
      - L7 — _extract_detail returns 500 chars of raw HTML on vendor HTML-error-page (cosmetic)
  mandatory_fixes_for_round_2: [C1, H1, H2]
  optional_same_round_if_cheap: [M1, M2, M3, M4, M5, M6]
  fast_follow_acceptable: [L1, L2, L3, L4, L5, L6, L7]
ah1_tier_b_done_this_session:
  - CLAIMSMAX_API_KEY set on Render via merge-mode PUT (21 env vars verified via ?limit=100; default pagination gave 20-cutoff false-alarm)
  - Deploy POST dep-d84pfsugvqtc73d3srig at commit 9cb22f6c
  - Pandoc-on-Render decision: ship without (Director ratified yesterday; RendererUnavailableError degrades gracefully)
---

# Dispatch: CLAIMSMAX_API_CAPABILITY_1

B4 — full brief at `briefs/BRIEF_CLAIMSMAX_API_CAPABILITY_1.md`.

**TL;DR:** Wire the ClaimsMax v1 REST API (`https://brisen.claimsmax.co.uk/api/v1/`) into Baker as a permanent capability. New client in `kbl/claimsmax_client.py`, 4 MCP tools in `tools/claimsmax.py`, capability-set migration, tests, doc update. Auth via `CLAIMSMAX_API_KEY` env var (AH1 sets in Render before merge). Skip `/ask` — vendor bug pending Ellie Technologies fix.

**Working dir:** `~/bm-b4`
**Branch:** `b4/claimsmax-api-capability-1` off `main`
**Estimated touch:** ~8 files, ~400 LOC including tests + migration.
**Trigger class:** MEDIUM (mandatory 2nd-pass review per gate protocol — `/security-review` mandatory).

## Pre-flight

1. `git pull --ff-only origin main` in `~/bm-b4`.
2. Read `briefs/BRIEF_CLAIMSMAX_API_CAPABILITY_1.md` end-to-end.
3. Read `~/Desktop/ClaimsMaxAPI.md` for the full API spec.

## Reporting

- Bus-post `lead` (AH1) on PR open with topic `pr-open/claimsmax-api-capability-1`.
- AH1 runs `/security-review` (mandatory per Lesson #52 and trigger-class MEDIUM) + `/code-review`.
- AH1 sets Render env var `CLAIMSMAX_API_KEY` before merge (separate Tier B action).
- AH1 merges on green; runs one live smoke test against prod deploy.

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
