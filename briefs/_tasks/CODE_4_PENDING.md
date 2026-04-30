COMPLETE — Brief 4 (CORTEX_CONFIG_DIRECTIVES_SCHEMA_1) shipped via PR #125 + follow-up patch PR #127, both merged 2026-04-30 (`5b55bf1` schema + provisioner + bootstrap hook + run-once batch + tests; `0b57961` four post-review fixes — slug-derived name source + validate_frontmatter self-invariant + regression test + `_global` bypass note).

Prior: Q1-flip dispatch 2026-04-30 by AI Head A (App). Schema migration, partial unique idx for Brief 3 reflector idempotency, bootstrap hook, run-once migrator all live on main. Trigger-class TIER A reviewed via architect-review pass twice (REQUEST_CHANGES on #125 → APPROVE on #127). PR #125 was merged by Director before #127 patches landed; #127 closes the gap (no production damage — migrator hadn't been run; bootstrap hook hadn't fired for any new matter in the gap window).

B4 idle. Next dispatcher: run §2 busy-check (`_ops/processes/b-code-dispatch-coordination.md`) before overwriting.

Brief 3 (CORTEX_PHASE6_REFLECTOR_1) is the next-up build — consumes the schema + partial unique idx that just shipped. Per Q1-flip ratification, Brief 3 dispatch follows Brief 4 ship.
