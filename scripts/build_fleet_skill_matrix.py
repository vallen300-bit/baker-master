#!/usr/bin/env python3
"""Render the fleet role-to-skill KEEP/DROP planning matrix.

The matrix is intentionally declarative. It does not edit picker manifests or
shared skill bodies; it produces the review artifact that precedes rollout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VAULT = Path("/Users/dimitry/baker-vault")
SKILLS_INDEX = VAULT / "_ops" / "skills" / "SKILLS_INDEX.md"
POINTER_SKILL = VAULT / "_ops" / "skills" / "skill-index" / "SKILL.md"

sys.path.insert(0, str(ROOT))
from scripts.measure_session_start_load import (  # noqa: E402
    PICKER_PATHS,
    build_rows,
)


def _set(*names: str) -> set[str]:
    return set(names)


COMMON = _set(
    "agent-bus-posting-contract",
    "pin-protocol",
    "writer-contract",
)

ENGINEERING = _set(
    "code-graph-search-cheapest-form",
    "deep-module-interface-first",
    "done-rubrics-stop-gate",
    "engineering-router-context-contract",
    "harness-setup",
    "long-running-task-ownership",
    "post-deploy-ac-bus-gate",
    "reliability-engineering",
)

AI_HEAD = COMMON | ENGINEERING | _set(
    "ai-head",
    "ai-head-brief-and-gate",
    "ai-head-memory-reference",
    "ai-head-ops-reference",
    "architecture-review",
    "b-code-dispatch-coordination",
    "baker-whiteboard-pass",
    "devils-advocate",
    "eval-design",
    "grok-via-xai-api",
    "laconic",
    "model-selection",
    "pin-protocol",
    "prompt-pattern-library",
    "skill-installation",
    "ui-surface-prebrief",
    "verify-dashboard-render",
    "v2-bridge-cutover-runbook",
    "write-brief",
)

DEPUTY = AI_HEAD | _set(
    "install-agent-to-brisen-lab",
    "install-agent-to-cowork-app",
    "research-fan-out",
    "researcher-verify-citations",
)

WORKER = COMMON | ENGINEERING | _set(
    "b-code-dispatch-coordination",
    "flight-discipline",
)

FILING_WORKER = COMMON | ENGINEERING | _set(
    "document-intake-to-room",
    "flight-discipline",
    "important-document",
    "worker-execution-of-matter-filing",
)

RESEARCH = COMMON | _set(
    "analog-library",
    "claimsmax-api",
    "client-facing-research-findings",
    "document-intake-to-room",
    "grok-via-xai-api",
    "local-research-via-gemma",
    "research-fan-out",
    "research-repository",
    "researcher-verify-citations",
    "transcripts-by-matter",
    "ui-surface-prebrief",
    "x-twitter",
    "youtube-analyze",
)

MATTER_COMMON = COMMON | _set(
    "brisen-balazs-powerpoint-style",
    "brisen-balazs-word-style",
    "cascade-back-prop",
    "claimsmax-api",
    "client-facing-research-findings",
    "correspondence-routing",
    "cortex-config-template",
    "desk-gmail-reach",
    "document-intake-to-room",
    "email-send-via-mail-app",
    "executive-audit-html",
    "executive-memo-authoring",
    "executive-memo-ellie-style",
    "field-capture-to-card",
    "grok-via-xai-api",
    "humanality",
    "important-document",
    "local-research-via-gemma",
    "mckinsey-report-html",
    "memo-block-plan",
    "memo-body-loops",
    "memo-engagement-check",
    "memo-explore",
    "memo-grill",
    "memo-lessons",
    "memo-review",
    "nvidia-style-html",
    "outbound-status-claim-gate",
    "pichler-report",
    "project-room-build",
    "transcripts-by-matter",
    "ui-surface-prebrief",
    "whatsapp-pull-via-api",
    "whatsapp-send-via-waha",
    "x-twitter",
)

ORIGINATION = MATTER_COMMON | _set(
    "back-of-envelope-math",
    "ceo-decision-framing",
    "counterparty-model",
    "first-principles-reset",
    "helmer-7-powers",
    "jtbd",
    "kill-criteria-definer",
    "negotiation-prep",
    "opportunity-framework",
    "partner-pitch-craft",
    "pre-mortem",
    "scenario-planning",
    "swot-analysis",
    "three-horizons",
    "time-horizon-filter",
    "wardley-mapping",
)

AID = COMMON | ENGINEERING | _set(
    "agent-onboarding-runbook",
    "agent-spec-template",
    "aidennis-edge-scout",
    "chrome-debug-recovery",
    "install-agent-to-brisen-lab",
    "install-agent-to-cowork-app",
    "it-manager",
    "skill-installation",
    "v2-bridge-cutover-runbook",
)

ARM = COMMON | ENGINEERING | _set(
    "airport-process-orchestration",
    "b-code-dispatch-coordination",
    "clickup-research-loop",
    "dashboard-spa-build",
    "flight-dashboard-build",
    "flight-discipline",
    "flight-install-runbook",
    "pilot-training",
    "project-dashboard-spec",
    "verify-dashboard-render",
)

PUBLISHER = COMMON | _set(
    "brisen-balazs-powerpoint-style",
    "brisen-balazs-word-style",
    "client-facing-research-findings",
    "correspondence-routing",
    "dashboard-spa-build",
    "director-pdf-signing",
    "document-intake-to-room",
    "dropbox-file-delivery",
    "email-send-via-mail-app",
    "executive-audit-html",
    "executive-memo-authoring",
    "executive-memo-ellie-style",
    "humanality",
    "mckinsey-report-html",
    "nvidia-style-html",
    "outbound-status-claim-gate",
    "pichler-report",
    "presentation-deck",
    "ui-surface-prebrief",
    "verify-dashboard-render",
    "whatsapp-send-via-waha",
)

DESIGNER = COMMON | _set(
    "color-system",
    "component-spec",
    "dashboard-spa-build",
    "data-visualization",
    "design-ingest",
    "design-v2",
    "documentation-template",
    "html-loops",
    "html-triage",
    "layout-grid",
    "presentation-deck",
    "project-dashboard-spec",
    "responsive-design",
    "typography-scale",
    "ui-surface-prebrief",
    "ux-writing",
    "verify-dashboard-render",
    "wireframe-spec",
)

LIBRARIAN = RESEARCH | _set(
    "document-intake-to-room",
    "important-document",
    "project-room-build",
)

CLERK = FILING_WORKER | _set(
    "claimsmax-api",
    "desk-gmail-reach",
    "transcripts-by-matter",
    "whatsapp-pull-via-api",
)

RUSSO = RESEARCH

BEN = COMMON | _set(
    "back-of-envelope-math",
    "ceo-decision-framing",
    "client-facing-research-findings",
    "correspondence-routing",
    "counterparty-model",
    "executive-audit-html",
    "executive-memo-authoring",
    "executive-memo-ellie-style",
    "field-capture-to-card",
    "humanality",
    "mckinsey-report-html",
    "memo-block-plan",
    "memo-body-loops",
    "memo-engagement-check",
    "memo-explore",
    "memo-grill",
    "memo-lessons",
    "memo-review",
    "negotiation-prep",
    "nvidia-style-html",
    "outbound-status-claim-gate",
    "pichler-report",
    "presentation-deck",
    "pre-mortem",
    "scenario-planning",
    "swot-analysis",
    "three-horizons",
    "time-horizon-filter",
    "ui-surface-prebrief",
)


PROFILES: dict[str, tuple[str, set[str]]] = {
    "ai-head": ("AI Head terminal/app seat", AI_HEAD),
    "deputy": ("Deputy terminal seat", DEPUTY),
    "worker": ("Build worker seat", WORKER),
    "filing-worker": ("Matter filing worker seat", FILING_WORKER),
    "researcher": ("Research and evidence seat", RESEARCH),
    "matter-common": ("Matter desk seat", MATTER_COMMON),
    "origination": ("Origination desk seat", ORIGINATION),
    "aid": ("AI Dennis / IT seat", AID),
    "arm": ("ARM / flight operations seat", ARM),
    "publisher": ("Publisher seat", PUBLISHER),
    "designer": ("UI design seat", DESIGNER),
    "librarian": ("Library and evidence seat", LIBRARIAN),
    "clerk": ("Clerk evidence-processing seat", CLERK),
    "russo": ("Russo research seat", RUSSO),
    "ben": ("BEN finance/app seat", BEN),
}

PROFILE_ASSIGNMENTS: dict[str, str] = {
    "lead": "ai-head",
    "cowork-ah1": "ai-head",
    "deputy": "deputy",
    "deputy-codex": "N/A-codex",
    "aid": "aid",
    "b1": "worker",
    "b2": "worker",
    "b3": "worker",
    "b4": "worker",
    "researcher": "researcher",
    "codex": "N/A-codex",
    "codex-arch": "N/A-codex",
    "clerk": "clerk",
    "clerk-haiku": "clerk",
    "russo-ai": "russo",
    "deep55": "N/A-no-session",
    "ben": "ben",
    "librarian": "librarian",
    "arm": "arm",
    "publisher": "publisher",
    "designer": "designer",
    "hag-desk": "matter-common",
    "origination-desk": "origination",
    "ao-desk": "matter-common",
    "movie-desk": "matter-common",
    "baden-baden-desk": "matter-common",
    "brisen-desk": "matter-common",
    "cowork-bb-desk": "matter-common",
    "cowork-ao-desk": "matter-common",
    "cowork-movie-desk": "matter-common",
    "cowork-hag-desk": "matter-common",
    "cowork-origination-desk": "origination",
    "cowork-researcher": "researcher",
    "cowork-arm": "arm",
    "cowork-russo-ai": "russo",
    "cowork-librarian": "librarian",
    "cowork-aid": "aid",
    "CM-1": "filing-worker",
    "CM-2": "filing-worker",
    "CM-3": "filing-worker",
    "CM-4": "filing-worker",
    "hag-filer": "filing-worker",
}


def indexed_skills() -> list[str]:
    skills: list[str] = []
    for line in SKILLS_INDEX.read_text().splitlines():
        if line.startswith("| `"):
            skills.append(line.split("`", 2)[1])
    if len(skills) != len(set(skills)):
        raise ValueError("skill index contains duplicate slugs")
    return skills


def local_registered_skills(role: str) -> set[str]:
    picker = PICKER_PATHS.get(role)
    root = picker / ".claude" / "skills" if picker else None
    if not root or not root.is_dir():
        return set()
    return {child.name for child in root.iterdir() if child.is_dir() or child.is_symlink()}


def augment_profiles(indexed: set[str]) -> dict[str, tuple[str, set[str]]]:
    """Preserve current picker-local catalog registrations in the profile."""
    representatives: dict[str, list[str]] = {
        "ai-head": ["lead", "cowork-ah1"],
        "deputy": ["deputy"],
        "worker": ["b1", "b2", "b3", "b4"],
        "filing-worker": ["CM-1", "CM-2", "CM-3", "CM-4", "hag-filer"],
        "researcher": ["researcher", "cowork-researcher"],
        "matter-common": [
            "hag-desk",
            "ao-desk",
            "movie-desk",
            "baden-baden-desk",
            "brisen-desk",
            "cowork-bb-desk",
            "cowork-ao-desk",
            "cowork-movie-desk",
            "cowork-hag-desk",
        ],
        "origination": ["origination-desk", "cowork-origination-desk"],
        "aid": ["aid", "cowork-aid"],
        "arm": ["arm", "cowork-arm"],
        "publisher": ["publisher"],
        "designer": ["designer"],
        "librarian": ["librarian", "cowork-librarian"],
        "clerk": ["clerk", "clerk-haiku"],
        "russo": ["russo-ai", "cowork-russo-ai"],
        "ben": ["ben"],
    }
    out: dict[str, tuple[str, set[str]]] = {}
    for profile, (description, keep) in PROFILES.items():
        for role in representatives[profile]:
            keep |= local_registered_skills(role) & indexed
        out[profile] = (description, keep)
    return out


def table_zero(rows: list[dict]) -> list[str]:
    lines = [
        "## Table 0 - Seat manifest",
        "",
        f"Identity generator entries observed: **{len(rows)}** (brief/ruling expected 38; drift: {len(rows) - 38:+d}).",
        "Every generated row is assigned exactly once below. Claude skill decisions",
        "apply only to MEASURE rows; Codex and no-session rows are N/A.",
        "",
        "| Role | Class | Profile | Picker path | State |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        role = row["role"]
        profile = PROFILE_ASSIGNMENTS.get(role)
        if profile is None:
            raise ValueError(f"unassigned generated role: {role}")
        if profile in PROFILES:
            profile_label = f"`{profile}`"
        else:
            profile_label = f"`{profile}`"
        state = "N/A" if row["class"].startswith("N/A") else (
            "OK" if row.get("exists") else "MISSING"
        )
        lines.append(
            f"| `{role}` | `{row['class']}` | {profile_label} | "
            f"`{row['picker']}` | {state} |"
        )
    return lines


def render(output: Path) -> str:
    rows = build_rows()
    indexed = indexed_skills()
    indexed_set = set(indexed)
    profiles = augment_profiles(indexed_set)

    generated_roles = {row["role"] for row in rows}
    assigned_roles = set(PROFILE_ASSIGNMENTS)
    if generated_roles != assigned_roles:
        raise ValueError(
            f"role assignment drift: missing={sorted(generated_roles - assigned_roles)}, "
            f"extra={sorted(assigned_roles - generated_roles)}"
        )

    for profile, (_, keep) in profiles.items():
        unknown = keep - indexed_set
        if unknown:
            raise ValueError(f"{profile} has skills outside index: {sorted(unknown)}")

    lines = [
        "# Fleet role-to-skill KEEP/DROP matrix - 2026-07-16",
        "",
        "> **Binding ruling:** lead bus #11951. Table 0 is derived from the current",
        "> generated identity snapshot and supersedes the brief's imprecise 12-row map.",
        "",
        "## Scope and decision rule",
        "",
        f"- Catalog source: `SKILLS_INDEX.md` ({len(indexed)} indexed skills).",
        "- `KEEP` means register the skill in that role's picker.",
        "- `DROP` means remove it from that picker's registration and retain it behind",
        "  the shared `skill-index` pointer on demand.",
        "- Existing picker-local registrations found in the representative seats are",
        "  carried into the relevant profile when the slug is in the indexed catalog.",
        "- Local-only skills outside the 132-skill catalog are listed as preserved",
        "  exceptions; this matrix does not authorize deleting them.",
        "- This artifact does not edit manifests or shared skill bodies.",
        "",
        "## Gate and dependency state",
        "",
        "- Stage: matrix authored; independent Codex gate and lead line-read are still required.",
        "- Rollout order: workers first, then support, then matter desks.",
        f"- `skill-index` pointer present in the shared vault: **{'YES' if POINTER_SKILL.is_file() else 'NO'}**.",
    ]
    if not POINTER_SKILL.is_file():
        lines.append(
            "- **BLOCKING DEPENDENCY:** no shared `skill-index/SKILL.md` was visible at generation time; "
            "do not roll out DROP decisions until the pointer exists and its discoverability spot-check passes."
        )
    lines += ["", *table_zero(rows), "", "## Profile definitions", ""]
    lines += [
        "| Profile | Seats | Keep count | Drop count | Decision basis |",
        "|---|---|---:|---:|---|",
    ]
    for profile, (description, keep) in profiles.items():
        seats = [role for role, value in PROFILE_ASSIGNMENTS.items() if value == profile]
        lines.append(
            f"| `{profile}` | {', '.join(f'`{role}`' for role in seats)} | "
            f"{len(keep)} | {len(indexed) - len(keep)} | {description} |"
        )
    lines += ["", "## Skill decision matrix", ""]
    header = ["Skill"] + list(profiles)
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for skill in indexed:
        decisions = [
            "KEEP" if skill in profiles[profile][1] else "DROP-to-pointer"
            for profile in profiles
        ]
        lines.append("| " + " | ".join([f"`{skill}`", *decisions]) + " |")
    lines += ["", "## Local-only registrations to preserve", ""]
    local_rows: list[tuple[str, list[str]]] = []
    for role, profile in PROFILE_ASSIGNMENTS.items():
        if profile not in profiles:
            continue
        local = sorted(local_registered_skills(role) - indexed_set)
        if local:
            local_rows.append((role, local))
    if local_rows:
        lines += [
            "| Role | Profile | Local-only skill slugs |",
            "|---|---|---|",
        ]
        for role, local in local_rows:
            lines.append(
                f"| `{role}` | `{PROFILE_ASSIGNMENTS[role]}` | "
                + ", ".join(f"`{skill}`" for skill in local)
                + " |"
            )
    else:
        lines.append("No local-only registrations were observed.")
    lines += [
        "",
        "## Review notes",
        "",
        "- The current generated snapshot contains 42 seats, not the ruling's expected 38.",
        "  The four-row drift is preserved and named; no generated row was silently dropped.",
        "- `N/A-codex` rows use a different loader and are footnotes, not Claude skill denominators.",
        "- `N/A-no-session` rows have no local picker and do not receive a Claude manifest.",
        "- AC2 and AC3 remain open until the pointer skill exists, each staged manifest is",
        "  applied, and three dropped-skill discoverability probes pass per picker group.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(args.output))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
