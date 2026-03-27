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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from config.settings import config

logger = logging.getLogger("baker.research_executor")

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

        # 11. DOSSIER-PIPELINE-1: Store .docx binary for download
        try:
            import os as _os
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            if local_path and _os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    file_bytes = f.read()
                store.store_dossier_file(
                    name=filename or f"Dossier_{subject_name}.docx",
                    file_bytes=file_bytes,
                    source="research_proposal",
                    source_id=str(proposal_id),
                )
        except Exception as _df_err:
            logger.warning(f"Dossier file storage failed (non-fatal): {_df_err}")

        # 12. Baker 3.0 — extract structured data from dossier output
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
