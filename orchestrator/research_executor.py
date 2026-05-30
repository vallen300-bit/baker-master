"""
ART-1 Batch 2: Research Dossier Execution Engine (Session 30)

When Director approves a research proposal, this engine:
1. Dispatches 3-4 specialists in parallel
2. Combines results into a structured dossier
3. Formats as McKinsey-style .docx
4. Saves to Dropbox /Baker-Feed/research-dossiers/
5. Notifies Director via WhatsApp + dashboard alert

Cost: ~EUR 2-4 per dossier (3-4 specialist Opus calls).
Time: ~60-120 seconds (parallel execution).

BRIEF_DOSSIER_ROOM_READ_1 (2026-05-30): before specialists run, resolve the
subject to ONE matter slug and prepend that room's curated digest to the
specialist prompt as ground truth. Resolution is strict-precedence (explicit
matter_slug column → exact canonical / composite alias → metadata-only weak
candidate → fail closed). Generic single-token aliases are REJECTED for
authoritative resolution.
"""
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.settings import config

logger = logging.getLogger("baker.research_executor")

# Kill-flag preference key (runtime-checked at the call-site; NOT a module-level
# env var, so a bad injection can be disabled via DB write without redeploy).
_KILL_FLAG_CATEGORY = "feature_flags"
_KILL_FLAG_KEY = "dossier_room_read_enabled"

# Frontmatter cap when scanning candidate matter cortex-config.md files in the
# metadata-only fallback (step 3 of resolver). Frontmatter is the first YAML
# block; 4KB is more than enough for the largest cortex-config frontmatter
# observed, and caps the worst-case body-read damage on a malformed file.
_FRONTMATTER_SCAN_CAP = 4000
_PEOPLE_SCAN_CAP = 8000

# Dropbox destination folder (Dropbox API path, not local filesystem)
DROPBOX_DOSSIER_FOLDER = "/Baker-Feed/research-dossiers"

# Specialist display names
SPECIALIST_NAMES = {
    "research": "Research & OSINT",
    "legal": "Legal Analysis",
    "profiling": "People Intelligence",
    "pr_branding": "PR & Media",
    "asset_management": "Asset Management",
    "finance": "Financial Analysis",
    "sales": "Sales Perspective",
    "communications": "Communications",
}


def _get_proposal(proposal_id: int) -> dict:
    """Fetch proposal from database."""
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # matter_slug must be in the SELECT for the dossier-room resolver to
            # honour the explicit-column path (BRIEF_DOSSIER_ROOM_READ_1, Codex C1).
            # Prod schema already carries the column; bootstrap CREATE TABLE in
            # research_trigger.py is drift (FAST-FOLLOW item).
            cur.execute("""
                SELECT id, subject_name, subject_type, context, specialists,
                       trigger_source, trigger_ref, matter_slug
                FROM research_proposals WHERE id = %s
            """, (proposal_id,))
            row = cur.fetchone()
            cur.close()
            if row:
                result = dict(row)
                if isinstance(result.get("specialists"), str):
                    result["specialists"] = json.loads(result["specialists"])
                return result
            return None
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"_get_proposal failed: {e}")
        return None


def _update_proposal_status(proposal_id: int, status: str,
                            deliverable_path: str = None,
                            deliverable_summary: str = None,
                            error_message: str = None):
    """Update proposal status in database."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            if status == "completed":
                cur.execute("""
                    UPDATE research_proposals
                    SET status = 'completed',
                        deliverable_path = %s,
                        deliverable_summary = %s,
                        completed_at = NOW(),
                        error_message = NULL
                    WHERE id = %s
                """, (deliverable_path, deliverable_summary, proposal_id))
            elif status == "failed":
                cur.execute("""
                    UPDATE research_proposals
                    SET status = 'failed',
                        error_message = %s,
                        completed_at = NOW()
                    WHERE id = %s
                """, (error_message or "Unknown error", proposal_id))
            else:
                cur.execute("""
                    UPDATE research_proposals SET status = %s WHERE id = %s
                """, (status, proposal_id))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"_update_proposal_status failed: {e}")


def _get_source_text(trigger_ref: str) -> str:
    """Retrieve the original message text that triggered the proposal."""
    if not trigger_ref:
        return ""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return ""
        try:
            cur = conn.cursor()
            if trigger_ref.startswith("wa-"):
                msg_id = trigger_ref[3:]
                cur.execute("""
                    SELECT full_text FROM whatsapp_messages
                    WHERE id = %s OR msg_id = %s
                    LIMIT 1
                """, (msg_id, msg_id))
            elif trigger_ref.startswith("email-"):
                thread_id = trigger_ref[6:]
                cur.execute("""
                    SELECT full_body FROM email_messages
                    WHERE thread_id = %s OR message_id = %s
                    LIMIT 1
                """, (thread_id, thread_id))
            else:
                return ""
            row = cur.fetchone()
            cur.close()
            return row[0][:4000] if row and row[0] else ""
        finally:
            store._put_conn(conn)
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Curated-room resolver (BRIEF_DOSSIER_ROOM_READ_1)
# ─────────────────────────────────────────────────────────────────────────────


def _room_read_enabled() -> bool:
    """Runtime kill-flag check (DB-backed, not env-var — disable without redeploy).

    Default: ENABLED. Returns False ONLY when an explicit `false`-shaped
    preference exists. Any failure path keeps the feature on (fail-open on
    flag check), which matches the brief's "any error → log → proceed" frame.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        prefs = store.get_preferences(category=_KILL_FLAG_CATEGORY)
        for p in prefs:
            if p.get("pref_key") == _KILL_FLAG_KEY:
                val = str(p.get("pref_value", "")).strip().lower()
                if val in {"false", "0", "off", "disabled", "no"}:
                    return False
                break
        return True
    except Exception as e:
        logger.debug(f"_room_read_enabled flag check non-fatal: {e}")
        return True


def _alias_is_composite(alias_key: str) -> bool:
    """A safe-to-resolve-authoritatively alias contains a hyphen (matter-specific).

    Single-token aliases (`mohg`, `mandarin`) and bare multi-word aliases
    (`mandarin oriental`) are REJECTED for authoritative resolution because
    they collide across matters (e.g. `mohg` maps to `mo-vie-am` in slugs.yml
    even though a Bick/MOHG dossier needs `nvidia-mohg`).
    """
    return "-" in alias_key


_TOKEN_BOUNDARY = re.compile(r"[^a-z0-9-]+")


def _authoritative_match(subject_name: str, context: str) -> Optional[str]:
    """Step 2 of resolver: exact canonical slug or matter-specific composite alias.

    Scans `subject_name + context` (lowercased, hyphen-preserving boundary) for
    occurrences of (a) any canonical slug, or (b) any composite (hyphenated)
    alias. Single-token aliases are REJECTED — they collide across matters and
    must never resolve authoritatively (Codex C2 regression).

    Returns:
        - The single canonical slug if exactly one matches.
        - None if zero matches OR 2+ distinct canonical slugs match (ambiguous).
    """
    try:
        from kbl import slug_registry
    except ImportError:
        return None

    haystack_raw = " ".join(s for s in (subject_name, context) if s).lower()
    if not haystack_raw.strip():
        return None
    # Normalise non-slug separators (spaces, punctuation) to a single space so
    # hyphenated composites stay intact for word-boundary matching.
    haystack = _TOKEN_BOUNDARY.sub(" ", haystack_raw)
    tokens = set(haystack.split())
    if not tokens:
        return None

    hits: set[str] = set()
    for slug in slug_registry.canonical_slugs():
        if slug in tokens:
            hits.add(slug)
            continue
        try:
            aliases = slug_registry.aliases_for(slug)
        except KeyError:
            aliases = []
        for alias in aliases:
            if not _alias_is_composite(alias):
                continue
            # Composite alias may itself contain hyphens; match as a whole token
            if alias in tokens:
                hits.add(slug)
                break

    if len(hits) == 1:
        return next(iter(hits))
    return None


_FRONTMATTER_BLOCK_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n", re.DOTALL)


def _extract_frontmatter_text(body: str) -> str:
    """Return raw frontmatter block (between leading ---/---) or "" if absent.

    Body-cap: never scan more than _FRONTMATTER_SCAN_CAP chars. Defense against
    a malformed file with no closing `---`.
    """
    if not body or not body.startswith("---"):
        return ""
    head = body[:_FRONTMATTER_SCAN_CAP]
    m = _FRONTMATTER_BLOCK_RE.match(head)
    return m.group(1) if m else ""


def _metadata_lookup(subject_name: str, context: str) -> Optional[str]:
    """Step 3 of resolver: ONE pass over wiki/matters/*/ — frontmatter + _people.md only.

    NEVER reads room bodies (00_originals/, curated/, 03_source_summaries/).
    Returns a single candidate canonical slug iff exactly one matter scores >0
    AND no other matter ties. 0 or tie → None.

    The result, if any, is NON-authoritative — the caller must use the WEAK
    header on injection (D2 fail-closed: never label a metadata guess as
    ground truth).
    """
    try:
        from kbl import slug_registry
    except ImportError:
        return None

    vault = os.environ.get("BAKER_VAULT_PATH")
    if not vault:
        return None
    try:
        matters_root = (Path(vault).expanduser() / "wiki" / "matters").resolve()
    except OSError:
        return None
    if not matters_root.is_dir():
        return None

    haystack = " ".join(s for s in (subject_name, context) if s).lower()
    if not haystack.strip():
        return None
    subject_lc = subject_name.lower().strip() if subject_name else ""

    scores: dict[str, int] = {}

    try:
        entries = sorted(matters_root.iterdir())
    except OSError:
        return None

    for slug_dir in entries:
        try:
            if not slug_dir.is_dir():
                continue
        except OSError:
            continue
        slug = slug_dir.name
        # Containment + slug-registry gate: ignore stray dirs, alias dirs map to canonical.
        try:
            resolved = slug_dir.resolve()
        except OSError:
            continue
        if not str(resolved).startswith(str(matters_root) + os.sep):
            continue
        canonical = slug_registry.normalize(slug)
        if canonical is None:
            continue

        score = 0

        # cortex-config.md frontmatter — read ONLY the frontmatter block.
        cfg = slug_dir / "cortex-config.md"
        try:
            cfg_resolved = cfg.resolve()
        except OSError:
            cfg_resolved = None
        if cfg_resolved and str(cfg_resolved).startswith(str(matters_root) + os.sep) and cfg_resolved.is_file():
            try:
                body = cfg_resolved.read_text(encoding="utf-8")[:_FRONTMATTER_SCAN_CAP]
            except OSError:
                body = ""
            fm = _extract_frontmatter_text(body)
            if fm:
                fm_lc = fm.lower()
                # Subject-name token match against frontmatter (entities + trigger_patterns).
                if subject_lc and len(subject_lc) >= 4 and subject_lc in fm_lc:
                    score += 1
                # Entity slugs (e.g. `mohg-raphael-bick`) presence in haystack.
                # Pull anything that looks like a slug from entities/adjacent lists.
                for raw_slug in re.findall(r"[a-z][a-z0-9-]{3,}", fm_lc):
                    if raw_slug in haystack and "-" in raw_slug:
                        score += 1
                        break  # one entity hit is enough per matter

        # _people.md (table content) — substring match on subject_name.
        ppl = slug_dir / "_people.md"
        try:
            ppl_resolved = ppl.resolve()
        except OSError:
            ppl_resolved = None
        if ppl_resolved and str(ppl_resolved).startswith(str(matters_root) + os.sep) and ppl_resolved.is_file():
            try:
                ppl_body = ppl_resolved.read_text(encoding="utf-8")[:_PEOPLE_SCAN_CAP].lower()
            except OSError:
                ppl_body = ""
            if subject_lc and len(subject_lc) >= 4 and subject_lc in ppl_body:
                score += 1

        if score > 0:
            scores[canonical] = scores.get(canonical, 0) + score

    if not scores:
        return None
    if len(scores) == 1:
        return next(iter(scores))
    max_score = max(scores.values())
    top = [s for s, v in scores.items() if v == max_score]
    if len(top) == 1:
        return top[0]
    return None  # tie → fail closed


def _resolve_matter_slug(
    proposal_matter_slug: Optional[str],
    subject_name: str,
    context: str,
) -> tuple[Optional[str], str]:
    """Strict-precedence resolver. Returns (canonical_slug, path).

    path ∈ {'explicit', 'alias', 'grep', 'none'}.
      - 'explicit' : proposal.matter_slug, normalised to canonical (steps 1 — authoritative).
      - 'alias'    : exact canonical or composite-alias hit in subject+context (step 2 — authoritative).
      - 'grep'     : metadata-only fallback (step 3 — WEAK / non-authoritative).
      - 'none'     : unresolved (steps fail closed — no room injection).
    """
    try:
        from kbl import slug_registry
    except ImportError:
        return None, "none"

    # Step 1 — explicit column (authoritative). Brief: "Explicit DOMINATES — if
    # present and canonical, stop here; never override with a context guess."
    if proposal_matter_slug:
        normed = slug_registry.normalize(proposal_matter_slug)
        if normed and slug_registry.is_canonical(normed):
            return normed, "explicit"

    # Step 2 — exact canonical OR composite alias (authoritative).
    auth = _authoritative_match(subject_name, context)
    if auth:
        return auth, "alias"

    # Step 3 — metadata-only (non-authoritative).
    meta = _metadata_lookup(subject_name, context)
    if meta:
        return meta, "grep"

    return None, "none"


def _read_curated_room_block(slug: str, authoritative: bool) -> str:
    """Wrapper around kbl.curated_wiki_reader.read_room. Fault-tolerant."""
    try:
        from kbl.curated_wiki_reader import read_room
    except ImportError as e:
        logger.warning(f"read_room import failed: {e}")
        return ""
    try:
        return read_room(slug, authoritative=authoritative)
    except Exception as e:
        logger.warning(f"read_room({slug!r}) failed: {e}")
        return ""


def _resolve_and_prepend_room(
    proposal_matter_slug: Optional[str],
    subject_name: str,
    context: str,
) -> str:
    """Single call-site seam: resolve slug + read room + prepend to context.

    Returns the (possibly empty) string to prepend. Honours runtime kill-flag.
    All paths emit a structured log line (D3: observability) so a silent miss
    is detectable post-hoc.
    """
    if not _room_read_enabled():
        logger.info(
            "dossier_room_read: kill-flag DISABLED path=killflag room_found=false "
            "slug=- files=0 digest_chars=0"
        )
        return ""

    slug, path = _resolve_matter_slug(proposal_matter_slug, subject_name, context)
    if slug is None:
        logger.info(
            "dossier_room_read: unresolved path=%s room_found=false slug=- "
            "files=0 digest_chars=0", path
        )
        return ""

    authoritative = path in ("explicit", "alias")
    block = _read_curated_room_block(slug, authoritative=authoritative)
    if not block:
        logger.info(
            "dossier_room_read: empty room path=%s room_found=false slug=%s "
            "files=0 digest_chars=0", path, slug
        )
        return ""

    # D4: cost metering. ~4 chars/token estimate aligns with the digest cap.
    digest_chars = len(block)
    est_tokens = digest_chars // 4
    logger.info(
        "dossier_room_read: injected path=%s room_found=true slug=%s "
        "authoritative=%s digest_chars=%d est_tokens=%d",
        path, slug, authoritative, digest_chars, est_tokens
    )
    return block


def _run_specialists(subject_name: str, subject_type: str, context: str,
                     source_text: str, specialist_slugs: list) -> dict:
    """Run multiple specialists in parallel. Returns {slug: answer_text}."""
    from orchestrator.capability_runner import CapabilityRunner
    from orchestrator.capability_registry import CapabilityRegistry

    registry = CapabilityRegistry.get_instance()
    runner = CapabilityRunner()

    prompt = f"""Prepare a comprehensive research dossier section on: {subject_name}

Subject type: {subject_type}
Context: {context}

{f"Source material:{chr(10)}{source_text[:3000]}" if source_text else ""}

Instructions:
- Provide thorough analysis from YOUR specialist perspective
- Focus on facts, amounts, dates, and verifiable information
- Search Baker's memory for any prior interactions, emails, meetings, or documents related to this subject
- Cite sources whenever possible
- Flag risks and opportunities clearly
- Be specific — names, dates, amounts, companies
- Structure with clear headings
- Write for a C-suite executive who needs to make decisions"""

    results = {}

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for slug in specialist_slugs:
            cap = registry.get_by_slug(slug)
            if not cap:
                logger.warning(f"Capability '{slug}' not found — skipping")
                continue
            future = executor.submit(runner.run_single, cap, prompt)
            futures[future] = slug

        for future in as_completed(futures, timeout=420):
            slug = futures[future]
            try:
                result = future.result(timeout=420)
                results[slug] = result.answer
                logger.info(
                    f"Specialist '{slug}' completed: {result.iterations} iterations, "
                    f"{result.elapsed_ms}ms"
                )
            except Exception as e:
                logger.error(f"Specialist '{slug}' failed: {e}")
                results[slug] = f"[Specialist {slug} encountered an error: {e}]"

    return results


def _format_dossier_markdown(subject_name: str, subject_type: str,
                              specialist_results: dict, specialists: list) -> str:
    """Combine specialist results into structured markdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    spec_list = ", ".join(SPECIALIST_NAMES.get(s, s) for s in specialists)

    sections = []
    sections.append(f"# Research Dossier: {subject_name}\n")
    sections.append(f"**Subject Type:** {subject_type}")
    sections.append(f"**Generated:** {now}")
    sections.append(f"**Specialists:** {spec_list}")
    sections.append("\n---\n")

    for slug in specialists:
        if slug in specialist_results:
            title = SPECIALIST_NAMES.get(slug, slug.title())
            answer = specialist_results[slug]
            sections.append(f"\n## {title}\n\n{answer}\n")
            sections.append("\n---\n")

    sections.append("\n*Generated by Baker Research Engine (ART-1)*")
    return "\n".join(sections)


def _generate_and_save_docx(subject_name: str, subject_type: str,
                            specialists: list, dossier_md: str) -> tuple:
    """Generate professional .docx and upload to Dropbox. Returns (filename, dropbox_path)."""
    import os
    import re
    import tempfile

    try:
        from document_generator import generate_dossier_docx

        safe_name = re.sub(r'[^\w\s-]', '', subject_name).strip().replace(' ', '_')
        date_str = datetime.now().strftime('%Y-%m-%d')
        filename = f"Dossier_{safe_name}_{date_str}.docx"

        tmp_dir = tempfile.gettempdir()
        filepath = os.path.join(tmp_dir, f"baker_dossier_{safe_name}.docx")

        specialists_text = ", ".join(SPECIALIST_NAMES.get(s, s) for s in specialists)

        generate_dossier_docx(
            dossier_md=dossier_md,
            subject_name=subject_name,
            subject_type=subject_type,
            specialists_text=specialists_text,
            filepath=filepath,
        )

        size_bytes = os.path.getsize(filepath)
        logger.info(f"Professional DOCX generated: {filename} ({size_bytes} bytes)")

        # Upload to Dropbox via API
        month = datetime.now().strftime("%Y-%m")
        dropbox_path = f"{DROPBOX_DOSSIER_FOLDER}/{month}/{filename}"

        try:
            from triggers.dropbox_client import DropboxClient

            # Check if client is available
            client = DropboxClient._get_global_instance()
            if client is None:
                logger.error("Dropbox upload skipped: DropboxClient._get_global_instance() returned None "
                             "(DROPBOX_ACCESS_TOKEN / DROPBOX_REFRESH_TOKEN may not be set)")
                return filename, filepath

            # Check token
            if not getattr(client, '_access_token', None) and not getattr(client, '_refresh_token', None):
                logger.error("Dropbox upload skipped: no access_token or refresh_token on DropboxClient")
                return filename, filepath

            logger.info(f"Uploading dossier to Dropbox: {dropbox_path} ({size_bytes} bytes)")
            result = client.upload_file(filepath, dropbox_path)
            actual_path = result.get("path_display", dropbox_path)
            logger.info(f"Dossier uploaded to Dropbox successfully: {actual_path}")
            return filename, actual_path

        except Exception as upload_err:
            logger.error(f"Dropbox upload failed for '{filename}': {type(upload_err).__name__}: {upload_err}",
                         exc_info=True)
            return filename, filepath

    except Exception as e:
        logger.error(f"DOCX generation failed: {type(e).__name__}: {e}", exc_info=True)
        return None, None


def _notify_completion(proposal_id: int, subject_name: str, filename: str,
                       specialists: list):
    """Notify Director via WhatsApp + dashboard alert."""
    spec_list = ", ".join(SPECIALIST_NAMES.get(s, s) for s in specialists)

    # Dashboard alert
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        store.create_alert(
            tier=2,
            title=f"Dossier ready: {subject_name}",
            body=(
                f"Research dossier completed.\n\n"
                f"**File:** {filename}\n"
                f"**Specialists:** {spec_list}\n\n"
                f"Saved to Baker-Feed/research-dossiers/. "
                f"Open the file or ask Baker to email it to your team."
            ),
            action_required=True,
            tags=["dossier", "research_complete"],
            source="research_executor",
            source_id=f"dossier-complete-{proposal_id}",
            structured_actions={
                "research_proposal_id": proposal_id,
                "subject_name": subject_name,
                "status": "completed",
                "specialists": specialists,
            },
        )
    except Exception as e:
        logger.warning(f"Dossier alert creation failed: {e}")

    # WhatsApp — research dossier is Baker's delivery of work product about
    # an external entity (subject_name) to Director. vip_signal kind fits.
    try:
        from outputs.whatsapp_sender import send_whatsapp
        wa_text = (
            f"Research dossier completed: {subject_name}\n\n"
            f"Specialists: {spec_list}\n"
            f"File: {filename}\n\n"
            f"Saved to Baker-Feed/research-dossiers/."
        )
        send_whatsapp(wa_text, kind="vip_signal")
    except Exception as e:
        logger.warning(f"Dossier WA notification failed: {e}")


# ─────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────

def execute_research_dossier(proposal_id: int):
    """
    Execute a research dossier for an approved proposal.
    Called as a background task from the API endpoint.

    Flow: fetch proposal → run specialists in parallel → combine →
          format .docx → save to Dropbox → notify Director.
    """
    logger.info(f"Starting research dossier execution: proposal_id={proposal_id}")

    # 1. Fetch proposal
    proposal = _get_proposal(proposal_id)
    if not proposal:
        logger.error(f"Proposal {proposal_id} not found — aborting")
        return

    subject_name = proposal["subject_name"]
    subject_type = proposal.get("subject_type", "person")
    context = proposal.get("context", "")
    specialists = proposal.get("specialists", ["research"])
    trigger_ref = proposal.get("trigger_ref", "")
    proposal_matter_slug = proposal.get("matter_slug")

    # 2. Mark as running
    _update_proposal_status(proposal_id, "running")

    try:
        # 3. Get source text
        source_text = _get_source_text(trigger_ref)

        # 3a. BRIEF_DOSSIER_ROOM_READ_1: resolve matter slug → read curated room →
        # prepend as ground truth so specialists do NOT re-derive filed facts.
        # Single call-site seam (D1/D2): all resolution + caps + observability
        # live in _resolve_and_prepend_room. Fail-closed on unresolved; weak
        # header on metadata-only matches; runtime kill-flag honoured.
        room_block = _resolve_and_prepend_room(
            proposal_matter_slug, subject_name, context
        )
        if room_block:
            context = room_block + "\n\n" + (context or "")

        # 4. Run specialists in parallel
        logger.info(f"Dispatching {len(specialists)} specialists for '{subject_name}'")
        specialist_results = _run_specialists(
            subject_name, subject_type, context, source_text, specialists
        )

        if not specialist_results:
            error_msg = "No specialist results returned — all specialists failed or timed out"
            logger.error(error_msg)
            _update_proposal_status(proposal_id, "failed", error_message=error_msg)
            return

        # 5. Quality gate — check total content length
        total_content = sum(len(v) for v in specialist_results.values())
        logger.info(f"Quality gate: {total_content} chars from {len(specialist_results)} specialists")

        if total_content < 2000:
            error_msg = (
                f"Specialists returned insufficient content ({total_content} chars, "
                f"minimum 2,000). This usually means Baker has no data on '{subject_name}'. "
                f"Try adding context or checking Baker's memory first."
            )
            logger.warning(f"Quality gate FAILED for proposal {proposal_id}: {error_msg}")
            _update_proposal_status(proposal_id, "failed", error_message=error_msg)
            return

        # 6. Combine into dossier markdown
        dossier_md = _format_dossier_markdown(
            subject_name, subject_type, specialist_results, specialists
        )

        # 7. Generate professional .docx and save to Dropbox
        filename, local_path = _generate_and_save_docx(
            subject_name, subject_type, specialists, dossier_md
        )

        # 8. Update proposal as completed (store full dossier for on-demand download)
        _update_proposal_status(
            proposal_id, "completed",
            deliverable_path=local_path,
            deliverable_summary=dossier_md,
        )

        # 9. Notify Director
        if filename:
            _notify_completion(proposal_id, subject_name, filename, specialists)

        # 10. DOSSIER-PIPELINE-1: Cross-store to deep_analyses for unified search
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            store.log_deep_analysis(
                analysis_id=f"research_{proposal_id}",
                topic=f"{subject_name} — Profile Dossier",
                source_documents=["research_proposal"],
                analysis_text=dossier_md,
            )
            logger.info(f"Cross-stored dossier to deep_analyses: research_{proposal_id}")
        except Exception as _da_err:
            logger.warning(f"deep_analyses cross-store failed (non-fatal): {_da_err}")

        # 11. Baker 3.0 — extract structured data from dossier output
        try:
            from orchestrator.extraction_engine import extract_specialist_output
            extract_specialist_output(
                task_id=proposal_id,
                specialist_slug="research_dossier",
                output_text=dossier_md,
            )
        except Exception as _ext_err:
            logger.warning(f"Dossier extraction hook failed (non-fatal): {_ext_err}")

        logger.info(
            f"Research dossier complete: proposal_id={proposal_id}, "
            f"subject='{subject_name}', file='{filename}', content={total_content} chars"
        )

    except Exception as e:
        error_msg = f"Execution error: {type(e).__name__}: {e}"
        logger.error(f"Research dossier execution failed: {error_msg}", exc_info=True)
        _update_proposal_status(proposal_id, "failed", error_message=error_msg)
