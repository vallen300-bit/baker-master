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
"""
import json
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from config.settings import config

logger = logging.getLogger("baker.research_executor")

# Dropbox sync path (local filesystem — Dropbox client syncs automatically)
DROPBOX_DOSSIER_PATH = Path("/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Feed/research-dossiers")

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
            cur.execute("""
                SELECT id, subject_name, subject_type, context, specialists,
                       trigger_source, trigger_ref
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
                            deliverable_summary: str = None):
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
                        completed_at = NOW()
                    WHERE id = %s
                """, (deliverable_path, deliverable_summary, proposal_id))
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

        for future in as_completed(futures, timeout=180):
            slug = futures[future]
            try:
                result = future.result(timeout=120)
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


def _generate_and_save_docx(subject_name: str, dossier_md: str) -> tuple:
    """Generate .docx and save to Dropbox. Returns (filename, local_path) or (None, None)."""
    try:
        from document_generator import generate_document, get_file

        file_id, filename, size_bytes = generate_document(
            content=dossier_md,
            fmt="docx",
            title=f"Dossier_{subject_name}",
            metadata={
                "generated_by": "Baker Research Engine (ART-1)",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        file_info = get_file(file_id)
        src_path = file_info["filepath"]

        # Save to Dropbox
        month_folder = DROPBOX_DOSSIER_PATH / datetime.now().strftime("%Y-%m")
        month_folder.mkdir(parents=True, exist_ok=True)
        dst_path = month_folder / filename

        shutil.copy2(src_path, dst_path)
        logger.info(f"Dossier saved to Dropbox: {dst_path} ({size_bytes} bytes)")

        return filename, str(dst_path)

    except Exception as e:
        logger.error(f"Document generation/save failed: {e}")
        # Fallback: save raw markdown
        try:
            import re
            safe_name = re.sub(r'[^\w\s-]', '', subject_name).strip().replace(' ', '_')
            date_str = datetime.now().strftime('%Y-%m-%d')
            md_filename = f"Dossier_{safe_name}_{date_str}.md"

            month_folder = DROPBOX_DOSSIER_PATH / datetime.now().strftime("%Y-%m")
            month_folder.mkdir(parents=True, exist_ok=True)
            md_path = month_folder / md_filename

            md_path.write_text(dossier_md, encoding="utf-8")
            logger.info(f"Dossier saved as markdown fallback: {md_path}")
            return md_filename, str(md_path)
        except Exception as e2:
            logger.error(f"Markdown fallback also failed: {e2}")
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
        )
    except Exception as e:
        logger.warning(f"Dossier alert creation failed: {e}")

    # WhatsApp
    try:
        from outputs.whatsapp_sender import send_whatsapp
        wa_text = (
            f"Research dossier completed: {subject_name}\n\n"
            f"Specialists: {spec_list}\n"
            f"File: {filename}\n\n"
            f"Saved to Baker-Feed/research-dossiers/."
        )
        send_whatsapp(wa_text)
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

    # 2. Mark as running
    _update_proposal_status(proposal_id, "running")

    try:
        # 3. Get source text
        source_text = _get_source_text(trigger_ref)

        # 4. Run specialists in parallel
        logger.info(f"Dispatching {len(specialists)} specialists for '{subject_name}'")
        specialist_results = _run_specialists(
            subject_name, subject_type, context, source_text, specialists
        )

        if not specialist_results:
            logger.error("No specialist results — aborting")
            _update_proposal_status(proposal_id, "approved")  # Reset to approved
            return

        # 5. Combine into dossier markdown
        dossier_md = _format_dossier_markdown(
            subject_name, subject_type, specialist_results, specialists
        )

        # 6. Generate .docx and save to Dropbox
        filename, local_path = _generate_and_save_docx(subject_name, dossier_md)

        # 7. Update proposal as completed
        summary = dossier_md[:500] if dossier_md else ""
        _update_proposal_status(
            proposal_id, "completed",
            deliverable_path=local_path,
            deliverable_summary=summary,
        )

        # 8. Notify Director
        if filename:
            _notify_completion(proposal_id, subject_name, filename, specialists)

        logger.info(
            f"Research dossier complete: proposal_id={proposal_id}, "
            f"subject='{subject_name}', file='{filename}'"
        )

    except Exception as e:
        logger.error(f"Research dossier execution failed: {e}")
        _update_proposal_status(proposal_id, "approved")  # Reset so Director can retry
