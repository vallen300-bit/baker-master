"""Weekly lint for baker-vault/wiki/matters/movie/.

Mirrors scripts/lint_ao_pm_vault.py patterns. Additional MOVIE-specific
check: HMA clause citations in wiki/matters/movie/*.md must resolve to
document IDs 83200-83206 (the HMA suite: MA, CSA, TSA, MLA, LA, DOG, FE).

Output: wiki/matters/movie/_lint-report.md (overwritten each run).
"""
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lint_movie_am_vault")

MATTER_SLUG = "movie"
CAPABILITY_SLUG = "movie_am"
REQUIRED_FRONTMATTER = {"title", "matter", "type", "layer"}
HMA_DOC_ID_MIN = 83200
HMA_DOC_ID_MAX = 83206
HMA_CLAUSE_FILES = ("agreements-framework.md", "mohg-dynamics.md")


def main():
    vault_path = os.environ.get("BAKER_VAULT_PATH")
    if not vault_path:
        raise RuntimeError("BAKER_VAULT_PATH not set")
    matter_dir = Path(vault_path) / "wiki" / "matters" / MATTER_SLUG
    if not matter_dir.is_dir():
        raise RuntimeError(f"Matter dir not found: {matter_dir}")

    violations = []
    violations.extend(_check_frontmatter(matter_dir))
    violations.extend(_check_wikilinks(matter_dir))
    violations.extend(_check_stale_lessons(matter_dir))
    violations.extend(_check_interactions(matter_dir))
    violations.extend(_check_hma_clause_citations(matter_dir))

    report = _render_report(violations)
    report_path = matter_dir / "_lint-report.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info("Wrote %s (%d violations)", report_path, len(violations))

    if violations:
        logger.warning("Lint violations: %d — see %s", len(violations), report_path)


def _check_frontmatter(matter_dir: Path) -> list:
    violations = []
    for md in matter_dir.rglob("*.md"):
        if md.name in ("_lint-report.md", "README.md"):
            continue
        txt = md.read_text(encoding="utf-8")
        if not txt.startswith("---"):
            violations.append(f"Missing frontmatter: {md.relative_to(matter_dir)}")
            continue
        try:
            _, fm, _ = txt.split("---", 2)
        except ValueError:
            violations.append(f"Malformed frontmatter: {md.relative_to(matter_dir)}")
            continue
        fields = set()
        for line in fm.splitlines():
            if ":" in line and not line.startswith(" "):
                fields.add(line.split(":", 1)[0].strip())
        missing = REQUIRED_FRONTMATTER - fields
        if missing:
            violations.append(
                f"Missing frontmatter fields in {md.relative_to(matter_dir)}: {sorted(missing)}"
            )
    return violations


def _check_wikilinks(matter_dir: Path) -> list:
    violations = []
    existing = {p.stem for p in matter_dir.rglob("*.md")}
    sub_dir = matter_dir / "sub-matters"
    if sub_dir.is_dir():
        for p in sub_dir.glob("*.md"):
            existing.add(f"sub-matters/{p.stem}")
    for md in matter_dir.rglob("*.md"):
        if md.name == "_lint-report.md":
            continue
        txt = md.read_text(encoding="utf-8")
        for match in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", txt):
            target = match.group(1).strip()
            if target.startswith("#") or ("/" in target and not target.startswith("sub-matters/")):
                continue
            if target not in existing:
                violations.append(
                    f"Broken wikilink in {md.relative_to(matter_dir)}: [[{target}]]"
                )
    return violations


def _check_stale_lessons(matter_dir: Path) -> list:
    violations = []
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return violations
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, learned_rule FROM baker_corrections
                WHERE capability_slug = %s AND active = TRUE
                  AND (last_retrieved_at IS NULL OR last_retrieved_at < NOW() - INTERVAL '60 days')
                ORDER BY created_at ASC
                LIMIT 20
                """,
                (CAPABILITY_SLUG,),
            )
            for row_id, rule in cur.fetchall():
                violations.append(
                    f"Stale correction #{row_id} ({CAPABILITY_SLUG}): "
                    f"{(rule or '')[:80]}… — retired-candidate"
                )
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("Stale-lessons check failed: %s", e)
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning("Stale-lessons outer error: %s", e)
    return violations


def _check_interactions(matter_dir: Path) -> list:
    violations = []
    interactions = matter_dir / "interactions"
    if not interactions.is_dir():
        return violations
    required_ts = {"source_at", "ingest_at", "recall_at", "decision_at"}
    for md in interactions.glob("*.md"):
        if md.name == "README.md":
            continue
        txt = md.read_text(encoding="utf-8")
        missing = [ts for ts in required_ts if ts not in txt]
        if missing:
            violations.append(
                f"Interaction missing timestamps {missing}: {md.relative_to(matter_dir)}"
            )
    return violations


def _check_hma_clause_citations(matter_dir: Path) -> list:
    """MOVIE-specific: clause citations must be backed by HMA document rows.

    Greps \\bclause\\s+\\d+\\.\\d+\\b in agreements-framework + mohg-dynamics,
    then confirms at least one row exists in documents WHERE id BETWEEN
    83200 AND 83206. A missing HMA suite in documents is the only flag —
    per-clause attribution is out of scope (no clause column in documents).
    """
    violations = []
    clause_pattern = re.compile(r"\bclause\s+\d+\.\d+\b", re.IGNORECASE)
    cited_files = []
    for fname in HMA_CLAUSE_FILES:
        fpath = matter_dir / fname
        if not fpath.is_file():
            continue
        txt = fpath.read_text(encoding="utf-8")
        if clause_pattern.search(txt):
            cited_files.append(fname)
    if not cited_files:
        return violations

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return violations
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*) FROM documents
                WHERE id BETWEEN %s AND %s
                LIMIT 1
                """,
                (HMA_DOC_ID_MIN, HMA_DOC_ID_MAX),
            )
            row = cur.fetchone()
            count = row[0] if row else 0
            if count < 1:
                violations.append(
                    f"HMA clause citations found in {cited_files} but no documents "
                    f"rows in {HMA_DOC_ID_MIN}-{HMA_DOC_ID_MAX} (HMA suite missing)"
                )
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("HMA-clause check failed: %s", e)
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning("HMA-clause outer error: %s", e)
    return violations


def _render_report(violations: list) -> str:
    header = f"""---
title: MOVIE AM Lint Report
matter: movie
type: lint-report
layer: 2
live_state_refs: []
generated_at: {datetime.now(timezone.utc).isoformat()}
violation_count: {len(violations)}
---

# MOVIE AM Lint Report

Last run: `{datetime.now(timezone.utc).isoformat()}`
Violations: **{len(violations)}**

"""
    if not violations:
        return header + "All checks passed.\n"
    body = "\n".join(f"- {v}" for v in violations)
    return header + "## Violations\n\n" + body + "\n"


if __name__ == "__main__":
    main()
