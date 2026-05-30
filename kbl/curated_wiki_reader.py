"""Curated wiki reader — additive read-path for per-matter PM capabilities.

Adds the curated knowledge layer (`<baker-vault>/wiki/matters/<slug>/curated/*.md`)
to the AO-PM (and future per-matter-PM) capability context. The DB state_json
update path is slower than Director's curated-wiki edits, so capabilities that
read only state_json give stale answers on cycle facts (Q2-2026 capital-call
tranche receipts surfaced this on 2026-05-16).

This module is read-only and stateless. Slug input is sanitized against:
  1. Regex `^[a-z0-9-]+$` — blocks path traversal characters.
  2. Allow-list — `slug_registry.normalize(slug) is not None`, i.e. the slug
     must be a known canonical or alias in `slugs.yml`. (Curated wiki dirs may
     use alias names, e.g. `wiki/matters/oskolkov/` for canonical `ao`, so we
     allow aliases through but reject anything outside the registry.)
  3. Path resolution — final resolved path must be under
     `<BAKER_VAULT_PATH>/wiki/matters/` (string-prefix on resolved paths;
     defends against symlink escape).

Briefs:
  - BRIEF_AO_PM_READ_CURATED_WIKI_1 (2026-05-16, AH2) — `read_curated`.
  - BRIEF_DOSSIER_ROOM_READ_1 (2026-05-30, cowork-ah1) — `read_room`: the
    dossier-engine pre-read. Reuses containment + char-cap helpers.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default per-file char cap (~2K tokens at 4 chars/token); enough to capture
# the Bottom Line + first 1-2 sections of a curated file, which is where dated
# cycle facts live.
DEFAULT_CHAR_CAP = 8000

# Default curated files to surface in PM context. Brief acceptance:
#   - 00_overview.md (Bottom Line / cycle posture)
#   - 02_money.md (drawdown status / dated receipts)
DEFAULT_FILES = ("00_overview.md", "02_money.md")

# read_room caps. The total cap is the load-bearing budget — `context` is not
# truncated downstream, so the dossier prompt swells with the digest * N
# specialists. ROOM_TOTAL_CHAR_CAP keeps digest≤~8K tokens at 4 chars/token.
ROOM_MAX_FILES = 8
ROOM_TOTAL_CHAR_CAP = 32000  # ~8K tokens
ROOM_PER_FILE_CAP = 8000

# Resolution-path headers. Authoritative header is reserved for steps 1-2 of
# the dossier-engine resolver (explicit matter_slug or exact/specific-composite
# slug match). Step 3 (metadata-only lookup) uses the weak header. The dossier
# resolver chooses which one to use; `read_room` honours that choice.
ROOM_HEADER_AUTHORITATIVE = (
    "=== CURATED PROJECT ROOM (authoritative — desk-maintained; "
    "surface conflicts, do not average; do NOT report a listed document as missing) ==="
)
ROOM_HEADER_WEAK = "=== POSSIBLY-RELATED ROOM (unconfirmed — verify) ==="
ROOM_INSTRUCTION = (
    "The block below is desk-curated ground truth for the matter named in the "
    "header. Treat as primary source: if a fact in this block contradicts your "
    "memory or a web result, surface the conflict — do not average. If a "
    "document is listed below, do NOT report it as missing."
)

_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")
_TOUCHES_SIBLINGS_RE = re.compile(
    r"^\s*touches_siblings\s*:\s*\[?\s*([^\]\n]+?)\s*\]?\s*$",
    re.MULTILINE,
)


class CuratedWikiError(ValueError):
    """Raised when a slug fails validation or path resolution escapes vault."""


@dataclass(frozen=True)
class CuratedFile:
    path: str            # relative path under baker-vault (for citation labels)
    body: str            # raw markdown content, char-capped
    last_curated_at: Optional[str]  # frontmatter `last_curated_at` if present
    truncated: bool      # True if body was capped below original length


def _validate_slug(slug: str) -> None:
    """Two-gate slug validation: regex + registry allow-list."""
    if not isinstance(slug, str) or not slug:
        raise CuratedWikiError(f"slug must be a non-empty string (got {slug!r})")
    if not _SLUG_PATTERN.match(slug):
        raise CuratedWikiError(
            f"slug {slug!r} contains disallowed characters; "
            f"must match {_SLUG_PATTERN.pattern}"
        )
    try:
        from kbl import slug_registry
    except ImportError as e:
        raise CuratedWikiError(f"slug_registry unavailable: {e}") from e
    if slug_registry.normalize(slug) is None:
        raise CuratedWikiError(
            f"slug {slug!r} is not a known canonical slug or alias in slugs.yml"
        )


def _resolve_vault_root() -> Path:
    vault = os.environ.get("BAKER_VAULT_PATH")
    if not vault:
        raise CuratedWikiError(
            "BAKER_VAULT_PATH env var not set — required to resolve curated wiki paths"
        )
    return Path(vault).expanduser().resolve()


def _parse_last_curated_at(body: str) -> Optional[str]:
    """Lift `last_curated_at:` from YAML frontmatter if present.

    Curated files use a 4-line+ frontmatter block delimited by `---` on its
    own line. Minimal parse — no PyYAML dep needed here; we only need one
    string field, and matching is line-based to keep the parser cheap and
    failure-tolerant on malformed frontmatter.
    """
    if not body.startswith("---"):
        return None
    lines = body.splitlines()
    if len(lines) < 2:
        return None
    # 30-line cap: real curated files have ≤10-line frontmatter; cap defends
    # against a pathological body that has no closing `---` (e.g. partially
    # written file) without scanning the whole body.
    for i in range(1, min(len(lines), 30)):
        if lines[i].strip() == "---":
            break
        if ":" in lines[i]:
            key, _, value = lines[i].partition(":")
            if key.strip() == "last_curated_at":
                return value.strip().strip('"').strip("'") or None
    return None


def _read_capped_text(
    fpath: Path,
    matters_root_resolved: Path,
    char_cap: int,
) -> Optional[tuple[str, bool]]:
    """Resolve, containment-check, read, char-cap a single file under matters_root.

    Returns `(body, truncated)` on success or None when the file does not exist,
    escapes containment, or is unreadable. Defense-in-depth: matter_dir's
    containment is enforced separately by the caller; this helper re-checks at
    file level because is_file()/read_text() follow symlinks.
    """
    try:
        resolved = fpath.resolve()
    except OSError as e:
        logger.warning("curated_wiki: resolve failed %s: %s", fpath, e)
        return None
    if not str(resolved).startswith(str(matters_root_resolved) + os.sep):
        logger.warning("curated_wiki: file %s escapes vault, skipping", resolved)
        return None
    if not resolved.is_file():
        return None
    try:
        body = resolved.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("curated_wiki: read failed %s: %s", resolved, e)
        return None
    truncated = False
    if char_cap and len(body) > char_cap:
        body = body[:char_cap] + "\n\n[...truncated; full file in vault...]"
        truncated = True
    return body, truncated


def read_curated(
    slug: str,
    files: Optional[tuple] = None,
    char_cap: int = DEFAULT_CHAR_CAP,
) -> list[CuratedFile]:
    """Return curated files for `slug`, char-capped, in the requested order.

    Args:
        slug: matter slug (e.g. "capital-call", "oskolkov"). Must pass the
              two-gate validation in `_validate_slug`.
        files: tuple of filenames under `curated/` to read. Each filename
               must match `^[A-Za-z0-9_.-]+\\.md$` (no path separators).
               Defaults to DEFAULT_FILES.
        char_cap: max chars per file; longer bodies are truncated with a
                  trailing marker. Pass 0 to disable capping.

    Returns:
        List of `CuratedFile` for files that exist + read cleanly. Missing
        files are skipped (graceful no-op per brief). Empty list if nothing
        readable — caller must treat as "no curated context" not as error.

    Raises:
        CuratedWikiError on slug validation failure or vault env unset.
    """
    _validate_slug(slug)

    requested = files or DEFAULT_FILES
    # Require leading alphanumeric to block dot-only names like '.md' / '..md'.
    safe_filename = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.md$")
    for fname in requested:
        if not safe_filename.match(fname):
            raise CuratedWikiError(f"unsafe curated filename {fname!r}")

    vault_root = _resolve_vault_root()
    matters_root = vault_root / "wiki" / "matters"
    matter_dir = (matters_root / slug / "curated").resolve()

    # String-prefix containment check on resolved paths defeats symlink escape
    # without relying on Path.is_relative_to (added 3.9 but cleaner to be
    # explicit + portable).
    matters_root_resolved = matters_root.resolve()
    if not str(matter_dir).startswith(str(matters_root_resolved) + os.sep) \
            and matter_dir != matters_root_resolved:
        raise CuratedWikiError(
            f"resolved curated dir {matter_dir} escapes {matters_root_resolved}"
        )

    if not matter_dir.is_dir():
        logger.info("curated_wiki: dir not present for slug=%s (%s)", slug, matter_dir)
        return []

    out: list[CuratedFile] = []
    for fname in requested:
        # File-level symlink containment: matter_dir containment is verified
        # above, but a symlink INSIDE curated/ can still point outside the
        # vault. is_file()/read_text() follow symlinks, so resolve + re-check
        # before any filesystem access on the path.
        fpath = (matter_dir / fname).resolve()
        if not str(fpath).startswith(str(matters_root_resolved) + os.sep):
            logger.warning(
                "curated_wiki: file %s escapes vault, skipping", fpath
            )
            continue
        if not fpath.is_file():
            continue
        try:
            body = fpath.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("curated_wiki: read failed %s: %s", fpath, e)
            continue
        truncated = False
        if char_cap and len(body) > char_cap:
            body = body[:char_cap] + "\n\n[...truncated; full file in vault...]"
            truncated = True
        rel = f"wiki/matters/{slug}/curated/{fname}"
        out.append(
            CuratedFile(
                path=rel,
                body=body,
                last_curated_at=_parse_last_curated_at(body),
                truncated=truncated,
            )
        )
    return out


def format_for_prompt(
    slug: str,
    files: Optional[tuple] = None,
    char_cap: int = DEFAULT_CHAR_CAP,
) -> str:
    """Convenience wrapper: read curated files and format as prompt block.

    Returns an empty string if nothing is readable, so callers can
    `if block: prompt += block` without a conditional read.
    """
    try:
        files_data = read_curated(slug, files=files, char_cap=char_cap)
    except CuratedWikiError as e:
        logger.warning("curated_wiki: skip slug=%s reason=%s", slug, e)
        return ""
    if not files_data:
        return ""
    parts = []
    for f in files_data:
        header = f"[CURATED WIKI: {f.path}"
        if f.last_curated_at:
            header += f" | last_curated_at: {f.last_curated_at}"
        header += "]"
        parts.append(f"{header}\n{f.body}")
    return "\n\n---\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# read_room — dossier-engine pre-read
# ─────────────────────────────────────────────────────────────────────────────


def _parse_touches_siblings(body: str) -> list[str]:
    """Lift `touches_siblings: [a, b, c]` (inline list) from frontmatter or body.

    Tolerates both the YAML frontmatter form and a bare line elsewhere in the
    document. Returns a possibly-empty list of stripped slug strings.
    """
    if not body:
        return []
    m = _TOUCHES_SIBLINGS_RE.search(body)
    if not m:
        return []
    raw = m.group(1)
    parts = [p.strip().strip("'\"") for p in raw.split(",")]
    return [p for p in parts if p and _SLUG_PATTERN.match(p)]


def _family_root(slug: str) -> str:
    """Family boundary = first hyphen-separated segment.

    Examples: 'nvidia-mohg' -> 'nvidia', 'mo-vie-am' -> 'mo', 'hagenauer-rg7'
    -> 'hagenauer'. Used to gate sibling reads so resolution + sibling-read
    cannot cross matters (`nvidia-*` siblings stay inside the nvidia family).
    """
    return slug.split("-", 1)[0]


def _in_family(primary: str, candidate: str) -> bool:
    """True iff `candidate` belongs to the same slug family as `primary`."""
    if not primary or not candidate:
        return False
    root = _family_root(primary)
    # candidate must equal root or start with `root-`. Equal-root case covers
    # parent slug (e.g. 'nvidia') when primary is 'nvidia-mohg'.
    return candidate == root or candidate.startswith(root + "-")


def read_room(
    slug: str,
    authoritative: bool = True,
    file_cap: int = ROOM_MAX_FILES,
    total_char_cap: int = ROOM_TOTAL_CHAR_CAP,
    per_file_cap: int = ROOM_PER_FILE_CAP,
) -> str:
    """Return a formatted curated-room digest for `slug`, headered for ground-truth use.

    Build order:
      1. `02_inventory/*room-structure-overview.md` if present (preferred — desk-authored).
      2. Else: `00_originals/` filenames listing + `03_source_summaries/*.md` bodies + `curated/*.md`.
      3. Expand `touches_siblings:` frontmatter on read files → include those siblings'
         `curated/*.md` + `03_source_summaries/*.md`, slug-family-gated.

    Reuses containment + char-cap helpers (`_read_capped_text`, `_validate_slug`,
    `read_curated`). No new vault-layout knowledge in callers.

    Args:
        slug: matter slug (must pass `_validate_slug`).
        authoritative: True → prepend AUTHORITATIVE header (resolver steps 1-2).
                       False → prepend WEAK header (resolver step 3 metadata-only).
        file_cap: max files in digest (default 8).
        total_char_cap: max raw chars across all files (default 32K ≈ 8K tokens).
        per_file_cap: per-file char cap before the file body is truncated.

    Returns:
        Formatted string ready to prepend to the specialist prompt. Empty string
        if nothing readable, slug invalid, or vault env unset (graceful no-op —
        callers can `if block: context = block + context`).
    """
    try:
        _validate_slug(slug)
    except CuratedWikiError as e:
        logger.warning("read_room: skip slug=%s reason=%s", slug, e)
        return ""

    try:
        vault_root = _resolve_vault_root()
    except CuratedWikiError as e:
        logger.warning("read_room: vault unresolvable: %s", e)
        return ""

    matters_root = vault_root / "wiki" / "matters"
    matters_root_resolved = matters_root.resolve()
    if not matters_root_resolved.is_dir():
        logger.info("read_room: matters root missing %s", matters_root_resolved)
        return ""

    # Slug-family gate up front: resolution chose `slug`; siblings allowed only
    # within slug-family.
    primary_dir = (matters_root / slug).resolve()
    if not str(primary_dir).startswith(str(matters_root_resolved) + os.sep):
        logger.warning("read_room: primary dir %s escapes vault", primary_dir)
        return ""

    digest: list[tuple[str, str]] = []  # (rel_path, body)
    truncated_files = 0
    total_chars = 0

    def _add(rel: str, body: str) -> bool:
        """Append (rel, body), respecting file_cap + total_char_cap. Returns True if added."""
        nonlocal total_chars, truncated_files
        if len(digest) >= file_cap:
            truncated_files += 1
            return False
        # Per-room budget — trim individual body to remaining headroom rather than
        # rejecting outright, so a single oversized file doesn't starve later ones
        # AND cannot blow the total cap.
        room_left = total_char_cap - total_chars
        if room_left <= 0:
            truncated_files += 1
            return False
        if len(body) > room_left:
            body = body[:room_left] + "\n\n[...truncated; total-room cap hit...]"
        digest.append((rel, body))
        total_chars += len(body)
        return True

    # ── Primary room: prefer overview ──
    overview_dir = primary_dir / "02_inventory"
    overview_used = False
    if overview_dir.is_dir():
        try:
            overview_candidates = sorted(
                f for f in overview_dir.iterdir()
                if f.is_file() and f.name.endswith("room-structure-overview.md")
            )
        except OSError:
            overview_candidates = []
        for f in overview_candidates:
            res = _read_capped_text(f, matters_root_resolved, per_file_cap)
            if res is None:
                continue
            body, was_trunc = res
            rel = f"wiki/matters/{slug}/02_inventory/{f.name}"
            if _add(rel, body):
                overview_used = True
                if was_trunc:
                    truncated_files += 0  # body-internal truncation, not file-skip
            break  # only first overview file

    if not overview_used:
        # Filename listing of 00_originals/ (names only — never bodies)
        originals_dir = primary_dir / "00_originals"
        if originals_dir.is_dir():
            try:
                originals_resolved = originals_dir.resolve()
                if str(originals_resolved).startswith(str(matters_root_resolved) + os.sep):
                    names = sorted(
                        p.name for p in originals_dir.iterdir() if p.is_file()
                    )
                    if names:
                        listing = "Filenames in 00_originals/ (names only — bodies live in vault):\n" + \
                                  "\n".join(f"- {n}" for n in names)
                        _add(f"wiki/matters/{slug}/00_originals/ (listing)", listing)
            except OSError as e:
                logger.warning("read_room: originals listing failed %s: %s", originals_dir, e)

        # 03_source_summaries bodies
        ss_dir = primary_dir / "03_source_summaries"
        if ss_dir.is_dir():
            try:
                ss_files = sorted(
                    f for f in ss_dir.iterdir() if f.is_file() and f.name.endswith(".md")
                )
            except OSError:
                ss_files = []
            for f in ss_files:
                res = _read_capped_text(f, matters_root_resolved, per_file_cap)
                if res is None:
                    continue
                body, _ = res
                # _add bumps truncated_files when caps reject the add — do NOT
                # short-circuit the loop here, or the truncation count is
                # silently lost.
                _add(f"wiki/matters/{slug}/03_source_summaries/{f.name}", body)

        # curated/ via read_curated (full directory listing, not DEFAULT_FILES)
        curated_dir = primary_dir / "curated"
        if curated_dir.is_dir() and len(digest) < file_cap and total_chars < total_char_cap:
            try:
                curated_files = tuple(
                    sorted(p.name for p in curated_dir.iterdir()
                           if p.is_file() and p.name.endswith(".md"))
                )
            except OSError:
                curated_files = ()
            if curated_files:
                try:
                    files_data = read_curated(slug, files=curated_files, char_cap=per_file_cap)
                except CuratedWikiError as e:
                    logger.warning("read_room: read_curated failed slug=%s: %s", slug, e)
                    files_data = []
                for cf in files_data:
                    _add(cf.path, cf.body)

    # ── touches_siblings expansion (slug-family-gated) ──
    sibling_slugs: set[str] = set()
    for _path, body in list(digest):
        for sib in _parse_touches_siblings(body):
            if sib == slug:
                continue
            if not _in_family(slug, sib):
                continue
            try:
                from kbl import slug_registry
            except ImportError:
                continue
            if not slug_registry.is_canonical(sib):
                continue
            sibling_slugs.add(sib)

    for sib in sorted(sibling_slugs):
        sib_dir = (matters_root / sib).resolve()
        if not str(sib_dir).startswith(str(matters_root_resolved) + os.sep):
            continue
        if not sib_dir.is_dir():
            continue

        # Sibling curated/
        sib_curated = sib_dir / "curated"
        if sib_curated.is_dir():
            try:
                sib_curated_files = tuple(
                    sorted(p.name for p in sib_curated.iterdir()
                           if p.is_file() and p.name.endswith(".md"))
                )
            except OSError:
                sib_curated_files = ()
            if sib_curated_files:
                try:
                    sib_files_data = read_curated(sib, files=sib_curated_files,
                                                  char_cap=per_file_cap)
                except CuratedWikiError:
                    sib_files_data = []
                for cf in sib_files_data:
                    _add(cf.path, cf.body)

        # Sibling 03_source_summaries
        sib_ss = sib_dir / "03_source_summaries"
        if sib_ss.is_dir():
            try:
                ss_files = sorted(
                    f for f in sib_ss.iterdir() if f.is_file() and f.name.endswith(".md")
                )
            except OSError:
                ss_files = []
            for f in ss_files:
                res = _read_capped_text(f, matters_root_resolved, per_file_cap)
                if res is None:
                    continue
                body, _ = res
                _add(f"wiki/matters/{sib}/03_source_summaries/{f.name}", body)

    if not digest:
        return ""

    header = ROOM_HEADER_AUTHORITATIVE if authoritative else ROOM_HEADER_WEAK
    parts = [f"{header}\nResolved slug: {slug}\n{ROOM_INSTRUCTION}"]
    for rel, body in digest:
        parts.append(f"[{rel}]\n{body}")
    if truncated_files > 0:
        parts.append(f"[room digest truncated: {truncated_files} files omitted]")
    return "\n\n".join(parts)
