# BRIEF: REPORT_RENDERER_SLUG_HARDEN_1 — validate matter slug recovered from JSON path

## Context

PR #213 (ClaimsMax v1 REST API capability) merged 2026-05-17 (`3cbc287`). AH2 cross-lane review #331 surfaced a LOW finding: `kbl/report_renderer.py::_matter_slug_from_json_path` returns `parts[idx-1]` directly without passing it through the existing `_validate_safe_slug` validator. Other call sites in the same module (e.g. `save_investigation_json` line 122-123) already validate caller-supplied slugs. This brief closes the gap on the path-recovery code path.

Same shape as PR #210's recent harden — apply existing validator at the boundary where a string becomes a path component.

## Estimated time: ~15 minutes
## Complexity: Low
## Prerequisites
- None. Local-only change to `kbl/report_renderer.py` + one test.

## API version / deprecation / fallback
- No external API calls. Internal Python only.
- Python 3.11+ (matches baker-master `runtime.txt`).

---

## Problem statement

```python
# kbl/report_renderer.py:314-326
def _matter_slug_from_json_path(json_p: Path) -> str:
    parts = json_p.parts
    try:
        idx = parts.index("research")
        if idx >= 1:
            return parts[idx - 1]
    except ValueError:
        pass
    return "misc"
```

`parts[idx - 1]` is returned as-is. If a path were crafted such that the segment before `research/` contained `..` or `/` (unlikely in normal flow but achievable if anyone feeds an attacker-controlled path), the slug would propagate to `out_dir = out_root / matter_slug` and escape the docs-site root. Existing `_validate_safe_slug` (line 74) already rejects exactly this class.

## Acceptance criteria

1. `_matter_slug_from_json_path` passes the recovered slug through `_validate_safe_slug` before returning.
2. On validation failure, fall back to `"misc"` (the same fallback the function already uses for non-conforming paths) — silent recovery, no exception propagated.
3. New test in `tests/test_report_renderer.py` (or wherever existing tests for this module live — grep first) covers:
   - normal path returns correct slug
   - path with `..` segment falls back to `"misc"`
   - path with `/` in the candidate segment falls back to `"misc"`
   - path with no `research/` segment falls back to `"misc"` (existing behavior; regression guard)
4. Literal `pytest tests/test_report_renderer.py -v` green (no "by inspection").

## Implementation sketch (non-binding — pick the cleanest shape)

```python
def _matter_slug_from_json_path(json_p: Path) -> str:
    parts = json_p.parts
    try:
        idx = parts.index("research")
        if idx >= 1:
            candidate = parts[idx - 1]
            try:
                _validate_safe_slug(candidate, field="matter_slug")
            except ValueError:
                return "misc"
            return candidate
    except ValueError:
        pass
    return "misc"
```

## Out of scope

- The L2 `_DROPBOX_ROOT` env-var pattern (a separate fast-follow, BRIEF later).
- The `/ask` endpoint NotImplementedError (blocked on vendor fix).
- Any refactor of the surrounding render flow.

## Ship gate

- Literal `pytest tests/test_report_renderer.py -v` output in ship report
- Branch: `b4/report-renderer-slug-harden-1`
- PR title: `fix(report_renderer): validate matter slug recovered from JSON path (#331 LOW)`

## Anchors

- AH2 cross-lane review #331 LOW finding.
- Lesson #65 pattern: apply existing validators at every boundary.
- Composes with PR #210 harden (same shape).
