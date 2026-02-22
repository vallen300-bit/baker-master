#!/usr/bin/env python3
"""
Sentinel AI — Command Line Interface
Quick way to interact with Baker through the Sentinel pipeline.

Usage:
    python cli.py ask "What do I know about Andrey and the Mandarin hotel?"
    python cli.py ask "Summarize my relationship with Christian Planegger" --contact "Christian Planegger"
    python cli.py briefing
    python cli.py status
"""
import asyncio
import argparse
import json
import logging
import sys

from orchestrator.pipeline import SentinelPipeline, TriggerEvent, ask_baker
from memory.retriever import SentinelRetriever
from config.settings import config


def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_ask(args):
    """Ask Baker a question with full context retrieval."""
    response = asyncio.run(ask_baker(
        question=args.question,
        contact=args.contact,
    ))

    print("\n" + "=" * 60)
    print("BAKER RESPONSE")
    print("=" * 60)

    # Print alerts first
    if response.alerts:
        for alert in response.alerts:
            tier = alert.get("tier", "?")
            title = alert.get("title", "")
            print(f"\n🔴 [TIER {tier} ALERT] {title}")
            print(f"   {alert.get('body', '')}")

    # Print analysis
    print(f"\n{response.analysis}")

    # Print draft messages
    if response.draft_messages:
        print("\n--- DRAFT MESSAGES ---")
        for draft in response.draft_messages:
            print(f"\nTo: {draft.get('to', '?')} via {draft.get('channel', '?')}")
            print(f"{draft.get('content', '')}")

    # Print metadata
    print(f"\n--- Pipeline: {response.metadata.get('pipeline_duration_ms', '?')}ms | "
          f"Contexts: {response.metadata.get('contexts_included', '?')}/"
          f"{response.metadata.get('contexts_total', '?')} | "
          f"Tokens: ≈{response.metadata.get('tokens_estimated', '?')} ---")


def cmd_briefing(args):
    """Generate a daily briefing."""
    pipeline = SentinelPipeline()
    trigger = TriggerEvent(
        type="scheduled",
        content="Generate the daily morning briefing. Review all pending items, upcoming meetings, active deals, and any alerts that need attention.",
        source_id="daily-briefing",
    )
    response = asyncio.run(pipeline.run(trigger))
    print("\n" + "=" * 60)
    print("☀️  DAILY BRIEFING")
    print("=" * 60)
    print(response.analysis)


def cmd_status(args):
    """Check Sentinel system status."""
    print("Sentinel AI — System Status")
    print("=" * 40)

    # Check Qdrant
    try:
        retriever = SentinelRetriever()
        collections = [
            config.qdrant.collection_whatsapp,
            config.qdrant.collection_email,
            config.qdrant.collection_meetings,
            config.qdrant.collection_documents,
        ]
        for coll in collections:
            try:
                info = retriever.qdrant.get_collection(coll)
                print(f"✅ Qdrant/{coll}: {info.points_count} points")
            except Exception:
                print(f"⬜ Qdrant/{coll}: not created yet")
    except Exception as e:
        print(f"❌ Qdrant: {e}")

    # Check Claude API
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        print(f"✅ Claude API: configured (model={config.claude.model})")
    except Exception as e:
        print(f"❌ Claude API: {e}")

    # Check PostgreSQL
    try:
        import asyncpg
        async def check_pg():
            conn = await asyncpg.connect(config.postgres.connection_string)
            count = await conn.fetchval("SELECT count(*) FROM contacts")
            await conn.close()
            return count
        count = asyncio.run(check_pg())
        print(f"✅ PostgreSQL: {count} contacts")
    except Exception as e:
        print(f"⬜ PostgreSQL: not configured ({e})")

    print(f"\nBaker persona: {config.baker_persona}")
    print(f"Debug mode: {config.debug}")


def main():
    parser = argparse.ArgumentParser(description="Sentinel AI — Baker Chief of Staff")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(dest="command")

    # ask command
    ask_parser = subparsers.add_parser("ask", help="Ask Baker a question")
    ask_parser.add_argument("question", type=str, help="Your question")
    ask_parser.add_argument("--contact", type=str, help="Contact name for context")

    # briefing command
    subparsers.add_parser("briefing", help="Generate daily briefing")

    # status command
    subparsers.add_parser("status", help="Check system status")

    args = parser.parse_args()
    setup_logging(args.debug)

    if args.command == "ask":
        cmd_ask(args)
    elif args.command == "briefing":
        cmd_briefing(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
