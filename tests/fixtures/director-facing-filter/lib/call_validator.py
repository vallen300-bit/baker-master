#!/usr/bin/env python3
"""call_validator.py — invoke Anthropic Haiku for filter-validation judgment.

Fail-safe: every error path returns {"decision":"pass","reason":"validator unavailable: <why>"}.
A broken validator must never block legitimate work (Director-facing filter v1.1).

Usage:
    from call_validator import validate
    verdict = validate(
        skill_path="~/.claude/skills/director-facing-filter-stakeholder-validator/SKILL.md",
        context={"vip_canonical_name": "...", "asserted_claim": "...", ...},
    )
    # verdict = {"decision": "block"|"pass", "reason": "..."}

Performance contract:
    - p50 latency: ~1.5s (Haiku 4.5 typical)
    - p99 latency: <=3s (hard timeout; PASS on timeout)
    - Cost: ~$0.0005-0.002 per call (~500-2000 input tokens, ~50-150 output)

Module-level cache:
    - API key cached in process via _get_api_key() (op CLI call ~200ms)
    - Skill prompt cached in process per skill_path

Error contract (ALL degrade to pass; never raise):
    - 1Password CLI fail -> pass + reason
    - anthropic SDK ImportError -> pass + reason ("not installed in hook env")
    - APIConnectionError / Timeout / RateLimit / APIStatusError 5xx -> pass + reason
    - APIStatusError 4xx -> pass + reason (treat as bad request; do not retry)
    - JSON parse failure on model response -> pass + reason ("malformed verdict JSON")
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

_API_KEY: str | None = None
_SKILL_CACHE: dict[str, dict] = {}
_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT_S = 3.0
_MAX_OUTPUT_TOKENS = 256
_OP_TIMEOUT_S = 5.0


def _get_api_key() -> str | None:
    """Fetch Anthropic API key from 1Password. Cached in process. Never logged."""
    global _API_KEY
    if _API_KEY is not None:
        return _API_KEY
    try:
        r = subprocess.run(
            ["op", "read", "op://Baker API Keys/API Anthropic/credential"],
            capture_output=True,
            text=True,
            timeout=_OP_TIMEOUT_S,
        )
    except Exception:
        return None
    # Explicitly drop stderr — never log key or 1P internals.
    if r.returncode != 0 or not r.stdout.strip():
        return None
    _API_KEY = r.stdout.strip()
    return _API_KEY


def _load_skill(skill_path: str) -> dict | None:
    """Parse a SKILL.md into {frontmatter, system_prompt, user_template}. Cached."""
    skill_path = os.path.expanduser(skill_path)
    if skill_path in _SKILL_CACHE:
        return _SKILL_CACHE[skill_path]
    if not os.path.isfile(skill_path):
        return None
    try:
        text = Path(skill_path).read_text(encoding="utf-8")
    except Exception:
        return None
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        return None
    try:
        import yaml
        fm = yaml.safe_load(m.group(1))
    except Exception:
        return None
    body = m.group(2)
    sys_match = re.search(r"## System Prompt\s*\n(.*?)(?=\n## |\Z)", body, re.DOTALL)
    user_match = re.search(r"## User Template\s*\n(.*?)(?=\n## |\Z)", body, re.DOTALL)
    if not sys_match or not user_match:
        return None
    skill = {
        "frontmatter": fm or {},
        "system_prompt": sys_match.group(1).strip(),
        "user_template": user_match.group(1).strip(),
    }
    _SKILL_CACHE[skill_path] = skill
    return skill


def _fill_template(template: str, context: dict[str, Any]) -> str:
    """Render user_template with context dict; non-string values json.dumps'd."""
    rendered_context = {}
    for k, v in context.items():
        rendered_context[k] = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return template.format(**rendered_context)


def _strip_fences(text: str) -> str:
    """Models sometimes wrap JSON in markdown fences despite instructions. Strip them."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def validate(skill_path: str, context: dict[str, Any]) -> dict[str, str]:
    """Run validator. Returns {"decision": "block"|"pass", "reason": "..."}.

    Never raises. Every error path -> pass + diagnostic reason.
    """
    skill = _load_skill(skill_path)
    if not skill:
        return {
            "decision": "pass",
            "reason": f"validator unavailable: skill not loadable at {skill_path}",
        }

    key = _get_api_key()
    if not key:
        return {
            "decision": "pass",
            "reason": "validator unavailable: 1Password fetch failed",
        }

    try:
        import anthropic
    except ImportError:
        return {
            "decision": "pass",
            "reason": "validator unavailable: anthropic SDK not installed in hook env",
        }

    try:
        user_msg = _fill_template(skill["user_template"], context)
    except KeyError as e:
        return {
            "decision": "pass",
            "reason": f"validator unavailable: missing context key {e}",
        }
    except Exception as e:
        return {
            "decision": "pass",
            "reason": f"validator unavailable: template render {type(e).__name__}",
        }

    try:
        client = anthropic.Anthropic(api_key=key, timeout=_TIMEOUT_S)
    except Exception as e:
        return {
            "decision": "pass",
            "reason": f"validator unavailable: client init {type(e).__name__}",
        }

    try:
        resp = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=_MAX_OUTPUT_TOKENS,
            system=skill["system_prompt"],
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        return {
            "decision": "pass",
            "reason": f"validator unavailable: {type(e).__name__}",
        }

    try:
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        text = _strip_fences(text)
        verdict = json.loads(text)
    except Exception:
        return {
            "decision": "pass",
            "reason": "validator unavailable: malformed verdict JSON",
        }

    decision = verdict.get("decision") if isinstance(verdict, dict) else None
    if decision not in ("block", "pass"):
        return {
            "decision": "pass",
            "reason": "validator unavailable: invalid decision value",
        }

    reason = str(verdict.get("reason", ""))[:300]
    return {"decision": decision, "reason": reason}


def _self_test() -> int:
    """Smoke test: module loads, 1Password fetch works (or degrades cleanly)."""
    print("call_validator self-test")
    print(f"  model: {_HAIKU_MODEL}")
    print(f"  timeout: {_TIMEOUT_S}s")

    key = _get_api_key()
    if key:
        print(f"  1Password fetch: OK (key starts with {key[:14]}...)")
    else:
        print("  1Password fetch: FAILED (validator will degrade to PASS at runtime)")

    try:
        import anthropic  # noqa: F401
        print("  anthropic SDK import: OK")
    except ImportError:
        print("  anthropic SDK import: MISSING (validator will degrade to PASS)")

    # Trial degradation path: nonexistent skill should PASS.
    verdict = validate(skill_path="/nonexistent/skill.md", context={})
    assert verdict["decision"] == "pass", f"expected degrade-to-pass; got {verdict}"
    assert "skill not loadable" in verdict["reason"], verdict
    print("  degrade-on-missing-skill: OK")
    return 0


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    print(__doc__)
    sys.exit(0)
