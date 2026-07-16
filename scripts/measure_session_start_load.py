#!/usr/bin/env python3
"""Measure Claude session-start source bytes for the fleet seat manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


HOME = Path("/Users/dimitry")
VAULT = HOME / "baker-vault"
GLOBAL_CLAUDE = HOME / ".claude" / "CLAUDE.md"
GLOBAL_SKILLS = HOME / ".claude" / "skills"
ROUTE_CUES = VAULT / "_ops" / "role-contexts" / "route-cues-to-superior.md"
LACONIC = VAULT / "_ops" / "role-contexts" / "laconic-default.md"
AI_HEAD = VAULT / "_ops" / "skills" / "ai-head" / "SKILL.md"

PICKER_PATHS = {
    "lead": HOME / "bm-aihead1",
    "cowork-ah1": HOME / "bm-aihead1",
    "deputy": HOME / "bm-aihead2",
    "deputy-codex": HOME / "bm-aihead2",
    "aid": HOME / "Vallen Dropbox/Dimitry vallen/bm-aidennis-t",
    "b1": HOME / "bm-b1",
    "b2": HOME / "bm-b2",
    "b3": HOME / "bm-b3",
    "b4": HOME / "bm-b4",
    "researcher": HOME / "bm-researcher",
    "codex": VAULT,
    "codex-arch": VAULT,
    "clerk": HOME / "bm-clerk",
    "clerk-haiku": HOME / "bm-clerk",
    "russo-ai": HOME / "bm-russo-ai",
    "deep55": None,
    "ben": HOME / "bm-ben",
    "librarian": HOME / "bm-librarian",
    "arm": HOME / "bm-arm",
    "publisher": HOME / "bm-publisher",
    "designer": HOME / "bm-designer",
    "hag-desk": HOME / "bm-hag-desk",
    "origination-desk": HOME / "Vallen Dropbox/Dimitry vallen/bm-origination-desk",
    "ao-desk": HOME / "Vallen Dropbox/Dimitry vallen/bm-ao-desk",
    "movie-desk": HOME / "Vallen Dropbox/Dimitry vallen/bm-movie-desk",
    "baden-baden-desk": HOME / "Vallen Dropbox/Dimitry vallen/bm-baden-baden-desk",
    "brisen-desk": HOME / "Vallen Dropbox/Dimitry vallen/bm-brisen-desk",
    "cowork-bb-desk": HOME / "BB",
    "cowork-ao-desk": HOME / "AO",
    "cowork-movie-desk": HOME / "MOVIE",
    "cowork-hag-desk": HOME / "Hagenauer",
    "cowork-origination-desk": HOME / "Origination",
    "cowork-researcher": HOME / "Researcher",
    "cowork-arm": HOME / "ARM",
    "cowork-russo-ai": HOME / "Russo",
    "cowork-librarian": HOME / "Librarian",
    "cowork-aid": HOME / "AID",
    "CM-1": HOME / "bm-CM-1",
    "CM-2": HOME / "bm-CM-2",
    "CM-3": HOME / "bm-CM-3",
    "CM-4": HOME / "bm-CM-4",
    "hag-filer": HOME / "bm-hag-filer",
}

CODEX_SEATS = {"deputy-codex", "codex", "codex-arch"}
NO_SESSION = {"deep55"}
APP_SEATS = {
    "cowork-ah1",
    "ben",
    "cowork-bb-desk",
    "cowork-ao-desk",
    "cowork-movie-desk",
    "cowork-hag-desk",
    "cowork-origination-desk",
    "cowork-researcher",
    "cowork-arm",
    "cowork-russo-ai",
    "cowork-librarian",
    "cowork-aid",
}
AI_HEAD_SEATS = {"lead", "cowork-ah1", "deputy"}
ORIENTATION_ALIASES = {
    "lead": "aihead1",
    "cowork-ah1": "aihead1",
    "deputy": "aihead2",
    "aid": "ai-dennis",
    "ben": "bb-finance",
    "cowork-aid": "ai-dennis",
    "cowork-bb-desk": "baden-baden-desk",
    "cowork-hag-desk": "hagenauer-desk",
}

# Captured before the lead-local trim began. Other seats are measured from disk.
LEAD_BEFORE = {
    "picker_claude": 20703,
    "role_context": 6436,
    "orientation": 13061,
    "ai_head": 13334,
}


def read_bytes(path: Path | None) -> int:
    try:
        return path.stat().st_size if path and path.is_file() else 0
    except OSError:
        return 0


def frontmatter_bytes(path: Path) -> int:
    try:
        raw = path.read_bytes()
    except OSError:
        return 0
    if not raw.startswith(b"---"):
        return 0
    end = raw.find(b"\n---", 3)
    return end + 4 if end >= 0 else 0


def skill_frontmatter_bytes(root: Path) -> tuple[int, int]:
    total = 0
    count = 0
    if not root.is_dir():
        return 0, 0
    for child in sorted(root.iterdir()):
        skill = child / "SKILL.md"
        size = frontmatter_bytes(skill)
        if size:
            total += size
            count += 1
    return total, count


def claude_chain_bytes(picker: Path | None) -> tuple[int, list[str]]:
    paths: list[Path] = []
    if picker:
        current = picker
        while current != current.parent:
            candidate = current / "CLAUDE.md"
            if candidate.is_file():
                paths.append(candidate)
            current = current.parent
    if GLOBAL_CLAUDE.is_file():
        paths.append(GLOBAL_CLAUDE)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return sum(read_bytes(path) for path in unique), [str(path) for path in unique]


def role_context_bytes(role: str, picker: Path | None) -> tuple[int, list[str]]:
    paths: list[Path] = []
    if picker:
        local = picker / ".claude" / "role-context" / f"{role.lower()}.md"
        if local.is_file():
            paths.append(local)
    if ROUTE_CUES.is_file():
        paths.append(ROUTE_CUES)
    if role in {"deputy", "deputy-codex"} and LACONIC.is_file():
        paths.append(LACONIC)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return sum(read_bytes(path) for path in unique), [str(path) for path in unique]


def orientation_paths(role: str) -> list[Path]:
    key = ORIENTATION_ALIASES.get(role, role)
    candidates = [VAULT / "_ops" / "agents" / key / "orientation.md"]
    if role.startswith("cowork-"):
        candidates.append(VAULT / "_ops" / "agents" / role.removeprefix("cowork-") / "orientation.md")
    return [path for path in candidates if path.is_file()]


def tier0_bytes(role: str) -> tuple[int, list[str]]:
    paths = orientation_paths(role)
    if role in AI_HEAD_SEATS:
        paths.append(AI_HEAD)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return sum(read_bytes(path) for path in unique), [str(path) for path in unique]


def window_tokens(picker: Path | None) -> tuple[int, str]:
    if not picker:
        return 0, "N/A"
    settings = picker / ".claude" / "settings.json"
    try:
        data = json.loads(settings.read_text())
        value = data.get("rollover_window_tokens")
        if isinstance(value, int) and value > 0:
            return value, str(settings)
    except (OSError, ValueError):
        pass
    return 200_000, "default:200000"


def seat_class(role: str) -> str:
    if role in CODEX_SEATS:
        return "N/A-codex"
    if role in NO_SESSION:
        return "N/A-no-session"
    if role in APP_SEATS:
        return "MEASURE-app"
    return "MEASURE-terminal"


def snapshot_slugs() -> list[str]:
    sys.path.insert(0, str(HOME / "bm-aihead1"))
    from orchestrator.agent_identity_data import SNAPSHOT_TERMINALS

    return [entry.split(":", 1)[0] for entry in SNAPSHOT_TERMINALS]


def build_rows() -> list[dict]:
    global_skill, global_count = skill_frontmatter_bytes(GLOBAL_SKILLS)
    rows: list[dict] = []
    for role in snapshot_slugs():
        kind = seat_class(role)
        picker = PICKER_PATHS.get(role)
        if kind == "N/A-codex":
            rows.append({
                "role": role,
                "class": kind,
                "picker": str(picker) if picker else "N/A",
                "agents_bytes": read_bytes((picker or VAULT) / "AGENTS.md"),
                "note": "Codex loader; no Claude skill-frontmatter denominator.",
            })
            continue
        if kind == "N/A-no-session":
            rows.append({
                "role": role,
                "class": kind,
                "picker": "N/A",
                "note": "Identity row is planned and has no local session launcher.",
            })
            continue
        picker_skill, picker_count = skill_frontmatter_bytes(
            picker / ".claude" / "skills" if picker else Path("/")
        )
        chain, chain_paths = claude_chain_bytes(picker)
        role_context, role_context_paths = role_context_bytes(role, picker)
        tier0, tier0_paths = tier0_bytes(role)
        window, window_source = window_tokens(picker)
        if role == "lead":
            before = {
                "picker_claude": LEAD_BEFORE["picker_claude"],
                "role_context": LEAD_BEFORE["role_context"],
                "tier0": LEAD_BEFORE["orientation"] + LEAD_BEFORE["ai_head"],
            }
        else:
            before = {
                "picker_claude": read_bytes((picker or Path("/")) / "CLAUDE.md"),
                "role_context": role_context,
                "tier0": tier0,
            }
        skills_bytes = global_skill + picker_skill
        before_claude = before["picker_claude"] + read_bytes(GLOBAL_CLAUDE)
        before_role_context = before["role_context"] + read_bytes(ROUTE_CUES)
        total = skills_bytes + chain + role_context + tier0
        before_total = skills_bytes + before_claude + before_role_context + before["tier0"]
        rows.append({
            "role": role,
            "class": kind,
            "picker": str(picker) if picker else "MISSING",
            "exists": bool(picker and picker.is_dir()),
            "global_skill_count": global_count,
            "global_skill_frontmatter_bytes": global_skill,
            "picker_skill_count": picker_count,
            "picker_skill_frontmatter_bytes": picker_skill,
            "skills_bytes": skills_bytes,
            "claude_chain_bytes": chain,
            "role_context_bytes": role_context,
            "tier0_bytes": tier0,
            "before_claude_chain_bytes": before_claude,
            "before_role_context_bytes": before_role_context,
            "before_tier0_bytes": before["tier0"],
            "before_bytes": before_total,
            "current_bytes": total,
            "window_tokens": window,
            "window_source": window_source,
            "before_percent": (before_total / 4 / window * 100) if window else 0,
            "current_percent": (total / 4 / window * 100) if window else 0,
            "claude_chain_paths": chain_paths,
            "role_context_paths": role_context_paths,
            "tier0_paths": tier0_paths,
        })
    return rows


def render(rows: list[dict]) -> str:
    expected = 38
    actual = len(rows)
    lines = [
        "# Fleet session-start load audit — 2026-07-16",
        "",
        "> **Binding ruling:** lead bus #11951. The seat manifest is Table 0 and",
        "> supersedes the brief's imprecise '12-row map' wording.",
        "",
        "## Table 0 — Seat manifest",
        "",
        f"Identity generator entries observed: **{actual}** (brief/ruling expected 38; drift: {actual - expected:+d}).",
        "Every generated row is classified exactly once. AC1/AC3 denominators are",
        "`MEASURE-terminal` + `MEASURE-app`; Codex and no-session rows are excluded.",
        "",
        "| Role | Class | Picker path | State |",
        "|---|---|---|---|",
    ]
    for row in rows:
        state = "N/A" if row["class"].startswith("N/A") else ("OK" if row.get("exists") else "MISSING")
        lines.append(f"| `{row['role']}` | `{row['class']}` | `{row['picker']}` | {state} |")
    lines += [
        "",
        "## Measurement method",
        "",
        "- **Skills:** user-global `~/.claude/skills/*/SKILL.md` frontmatter plus",
          "picker `.claude/skills/*/SKILL.md` frontmatter, counted additively.",
        "- **CLAUDE.md chain:** existing `CLAUDE.md` files from picker to home,",
          "deduplicated by resolved path, plus user-global `~/.claude/CLAUDE.md`.",
        "- **Role hook:** local `.claude/role-context/<role>.md` plus route-cues;",
          "the deputy hook also appends the laconic register.",
        "- **Tier 0:** role orientation plus `ai-head/SKILL.md` for AH seats.",
        "- **Window:** picker `settings.json` `rollover_window_tokens`, otherwise",
          "the declared 200,000-token default. This is a byte proxy, not a live meter.",
        "- **Conversion:** `bytes / 4` estimated tokens; percentage is",
          "`bytes / 4 / window_tokens * 100`.",
        "",
        "## Table 1 — Baseline source bytes",
        "",
        "| Role | Class | Skills FM | CLAUDE chain | Hook | Tier 0 | Before bytes | Before % | Window |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        if row["class"].startswith("N/A"):
            continue
        lines.append(
            f"| `{row['role']}` | `{row['class']}` | {row['skills_bytes']:,} | "
            f"{row['before_claude_chain_bytes']:,} | {row['before_role_context_bytes']:,} | "
            f"{row['before_tier0_bytes']:,} | {row['before_bytes']:,} | "
            f"{row['before_percent']:.2f}% | {row['window_tokens']:,} |"
        )
    lines += [
        "",
        "## Table 2 — Codex and excluded rows",
        "",
        "| Role | Class | Footnote |",
        "|---|---|---|",
    ]
    for row in rows:
        if row["class"].startswith("N/A"):
            detail = row.get("agents_bytes", 0)
            if row["class"] == "N/A-codex":
                detail = f"AGENTS.md bytes: {detail:,}; Claude skill frontmatter excluded."
            lines.append(f"| `{row['role']}` | `{row['class']}` | {detail or row['note']} |")
    lines += [
        "",
        "## Fail-loud notes",
        "",
        "- The generated source currently returns 42 entries, not 38; all 42 are",
          "included above rather than silently dropped.",
        "- The identity generator has no service row in `SNAPSHOT_TERMINALS`; the",
          "planned `deep55` row is the only current `N/A-no-session` classification.",
        "- Percentages are deterministic byte proxies. A fresh session meter is",
        "required to close the live AC after each rollout group.",
        "",
        "## Table 3 — Lead-local pilot byte delta",
        "",
        "| Surface | Before bytes | Current bytes | Delta |",
        "|---|---:|---:|---:|",
        "| `_ops/agents/aihead1/orientation.md` | 13,061 | 3,332 | -9,729 |",
        "| `_ops/skills/ai-head/SKILL.md` | 13,334 | 3,704 | -9,630 |",
        "| `bm-aihead1/CLAUDE.md` | 20,703 | 16,913 | -3,790 |",
        "| `bm-aihead1/.claude/role-context/lead.md` | 6,436 | 933 | -5,503 |",
        "| `AH1 MEMORY.md` | 26,831 | 4,376 | -22,455 |",
        "| `dropbox-tier0.md` | 11,093 | 11,093 | 0 (fleet stage) |",
        "",
        "The lead-local trim is intentionally not the final 6.5% target: the binding",
        "ruling moves global skill redistribution to the coordinated fleet migration.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(build_rows()))
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
