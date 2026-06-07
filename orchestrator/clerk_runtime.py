"""Headless Clerk runtime on Qwen3-Coder.

Phase 1 of CLERK_WORKBENCH_1: model client, bounded tool loop, tool registry,
and hard guardrails. Browser workbench surfaces are intentionally out of scope.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import posixpath
import re
import socket
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from config.settings import GraphConfig, Qwen3Config, config

logger = logging.getLogger("baker.clerk_runtime")

_DEFAULT_SAVE_PREFIX = "/Baker-Feed/Clerk-Workbench"
_ALLOWED_FETCH_PREFIXES = (
    "/Baker-Feed/",
    "/Apps/Baker/Clerk/",
)
_ALLOWED_SAVE_PREFIXES = (
    _DEFAULT_SAVE_PREFIX,
    "/Baker-Feed/Clerk",
    "/Apps/Baker/Clerk",
)
# CLERK_FULL_CAPABILITY_POLICY_1 — argument-value belt-and-suspenders (kept). The
# old _FORBIDDEN_TOOL_NAME_FRAGMENTS substring denylist is RETIRED in favour of the
# capability-CLASS policy below (_CLERK_TOOL_POLICY + _classify_tool, default-DENY).
_FORBIDDEN_TOOL_ARG_VALUES = re.compile(
    r"\b(send|delete|remove|move|archive|mark\s+read|mark\s+unread|pay|payment|wire|transfer)\b",
    re.I,
)

# ── Capability-class policy (CLERK_FULL_CAPABILITY_POLICY_1, Director-ratified) ──
# Every Baker tool slots into exactly one class. UNKNOWN tools are DENIED
# (fail-closed) so a newly-registered-but-unclassified tool is refused until it is
# explicitly added here — adding a capability becomes one line, not a guardrail PR.
#   ALLOW    — reads / search / analysis (+ live web, + Clerk drafting into its own
#              /Baker-Feed/Clerk-Workbench sandbox via file_save; out-of-sandbox
#              file_save is still gated by the registry path-gate / HMAC).
#   APPROVAL — real data mutations; never executes without a server-issued approval
#              action-key (the model can NEVER self-approve).
#   DENY     — money/payment/transfer + any external-to-human send; never executes
#              even WITH a valid approval token.
CLERK_ALLOW = "allow"
CLERK_APPROVAL = "approval"
CLERK_DENY = "deny"

_CLERK_TOOL_POLICY: dict[str, str] = {
    # ALLOW — currently wired read/search/analysis + sandbox file_save
    "baker_search": CLERK_ALLOW,
    "email_search": CLERK_ALLOW,
    "email_download": CLERK_ALLOW,
    "channel_search": CLERK_ALLOW,
    "transcripts_by_matter": CLERK_ALLOW,
    "document_fetch": CLERK_ALLOW,
    "format_convert": CLERK_ALLOW,
    "file_save": CLERK_ALLOW,  # sandbox save is core Clerk work; path-gate handles out-of-folder
    # ALLOW — Baker MCP reads to be wired in PR 2 (pre-classified so they slot in)
    "baker_deadlines": CLERK_ALLOW,
    "baker_vip_contacts": CLERK_ALLOW,
    "baker_sent_emails": CLERK_ALLOW,
    "baker_actions": CLERK_ALLOW,
    "baker_clickup_tasks": CLERK_ALLOW,
    "baker_todoist_tasks": CLERK_ALLOW,
    "baker_rss_feeds": CLERK_ALLOW,
    "baker_rss_articles": CLERK_ALLOW,
    "baker_deep_analyses": CLERK_ALLOW,
    "baker_briefing_queue": CLERK_ALLOW,
    "baker_watermarks": CLERK_ALLOW,
    "baker_conversation_memory": CLERK_ALLOW,
    "baker_get_preferences": CLERK_ALLOW,
    "baker_browser_tasks": CLERK_ALLOW,
    "baker_browser_results": CLERK_ALLOW,
    "baker_gmail_search": CLERK_ALLOW,
    "baker_gmail_read_message": CLERK_ALLOW,
    "baker_gmail_attachment_read": CLERK_ALLOW,
    "baker_health": CLERK_ALLOW,
    # ALLOW — ClaimsMax reads
    "baker_claimsmax_search": CLERK_ALLOW,
    "baker_claimsmax_check_investigation": CLERK_ALLOW,
    "baker_claimsmax_get_document": CLERK_ALLOW,
    # ALLOW — live web search
    "baker_grok_ask": CLERK_ALLOW,
    "baker_grok_web_search": CLERK_ALLOW,
    "baker_grok_x_search": CLERK_ALLOW,
    "perplexity_ask": CLERK_ALLOW,
    # ALLOW — internal agent bus (NOT an external send; coordination only)
    "baker_inbox_read": CLERK_ALLOW,
    "baker_inbox_post": CLERK_ALLOW,
    "baker_inbox_ack": CLERK_ALLOW,
    # APPROVAL — real internal mutations (server-issued action-key required)
    "baker_vault_write": CLERK_APPROVAL,
    "baker_raw_write": CLERK_APPROVAL,
    "baker_ingest_text": CLERK_APPROVAL,
    "baker_store_decision": CLERK_APPROVAL,
    "baker_store_analysis": CLERK_APPROVAL,
    "baker_add_deadline": CLERK_APPROVAL,
    "baker_upsert_vip": CLERK_APPROVAL,
    "baker_update_vip_profile": CLERK_APPROVAL,
    "baker_upsert_preference": CLERK_APPROVAL,
    "baker_upsert_matter": CLERK_APPROVAL,
    "baker_claimsmax_save_investigation": CLERK_APPROVAL,
    "baker_claimsmax_convert_to_html": CLERK_APPROVAL,
    "baker_claimsmax_convert_to_pdf": CLERK_APPROVAL,
    # APPROVAL — fire-and-forget multi-step run = real cost + side effect (G2 M2)
    "baker_claimsmax_investigate": CLERK_APPROVAL,
    # APPROVAL — _dispatch routes baker_scan to /api/scan = a full Opus Cortex run
    # (expensive LLM + side effects). Same principle as grok cost-gate / raw_query /
    # claimsmax_investigate: an autonomous cheap model must not trigger Opus scans
    # freely. APPROVAL-class + intentionally NOT registered yet (PR 2b defers it).
    "baker_scan": CLERK_APPROVAL,
    # DENY — raw SQL is NOT safely read-only: the MCP read guard is a startswith
    # keyword check that a writable CTE (WITH x AS (DELETE ... RETURNING ...) SELECT
    # ...) slips past, and _query autocommits — so a cheap model is one prompt from a
    # mutate/DELETE. Hard-DENY (not APPROVAL: even an approved call could write) until
    # the MCP layer is structurally SELECT-only / readonly-role (separate follow-up). (G2 H1)
    "baker_raw_query": CLERK_DENY,
    # DENY — money/payment + external-to-human sends (never executable, even approved)
    "baker_gmail_send": CLERK_DENY,
    "gmail_send": CLERK_DENY,
    "email_send": CLERK_DENY,
    "whatsapp_send": CLERK_DENY,
    "slack_send": CLERK_DENY,
    "baker_payment": CLERK_DENY,
    "baker_wire": CLERK_DENY,
}

# CLERK_FULL_CAPABILITY_POLICY_1 PR 2b — pure-SELECT Baker MCP reads wired into
# Clerk via the governed baker_mcp._dispatch entrypoint (the same sync path the MCP
# server's call_tool uses). All are read-only in _dispatch (verified); schemas are
# reused from the MCP TOOLS source of truth to avoid drift. baker_scan is NOT here
# (it is APPROVAL-class — an Opus scan, not a cheap read).
_CLERK_BAKER_READ_TOOLS = (
    "baker_deadlines",
    "baker_vip_contacts",
    "baker_sent_emails",
    "baker_actions",
    "baker_rss_feeds",
    "baker_rss_articles",
    "baker_deep_analyses",
    "baker_briefing_queue",
    "baker_watermarks",
    "baker_conversation_memory",
    "baker_get_preferences",
    "baker_browser_tasks",
    "baker_browser_results",
    "baker_health",
)

# CLERK_FULL_CAPABILITY_POLICY_1 PR 2c — gmail + claimsmax READS, routed through the
# governed tools.gmail.dispatch_gmail / tools.claimsmax.dispatch_claimsmax. Reads only.
# NOTE: baker_claimsmax_ask (LLM Q&A = cost) + investigate/save/convert (cost/side
# effects) are deliberately NOT here — ask is left UNMAPPED (default-DENY, fail-safe),
# the rest are APPROVAL-class.
_CLERK_GMAIL_READ_TOOLS = (
    "baker_gmail_search",
    "baker_gmail_read_message",
    "baker_gmail_attachment_read",
)
_CLERK_CLAIMSMAX_READ_TOOLS = (
    "baker_claimsmax_search",
    "baker_claimsmax_check_investigation",
    "baker_claimsmax_get_document",
)

# CLERK_FULL_CAPABILITY_POLICY_1 PR 2d-1 — internal agent bus, routed through the same
# governed baker_mcp._dispatch (inbox_* hit the brisen-lab HTTP daemon). ALLOW =
# internal coordination per the system prompt (NOT an external-to-human send; those
# are DENY). post/ack are bus coordination, not Baker-data lookups, so they are NOT
# grounding tools.
_CLERK_BUS_TOOLS = (
    "baker_inbox_read",
    "baker_inbox_post",
    "baker_inbox_ack",
)


def _pick_tool_schemas(tools: list[Any], wanted: frozenset[str]) -> list[dict[str, Any]]:
    """Convert source MCP Tool objects (.name/.description/.inputSchema) into Clerk's
    tool-schema dicts for the wanted names — reuse from source of truth, no drift."""
    out: list[dict[str, Any]] = []
    for tool in tools:
        name = getattr(tool, "name", None)
        if name in wanted:
            out.append({
                "name": name,
                "description": getattr(tool, "description", "") or "",
                "input_schema": getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}},
            })
    return out


# Name-fragment fail-closed catch for money/external-send shapes not explicitly
# mapped (defence in depth; default-DENY already covers unknowns).
_CLERK_DENY_FRAGMENTS = ("_send", "send_", "payment", "wire", "transfer", "remit", "payout")


def _classify_tool(name: str) -> str:
    """Return the capability class for a tool name. UNKNOWN -> DENY (fail-closed)."""
    if not name:
        return CLERK_DENY
    mapped = _CLERK_TOOL_POLICY.get(name)
    if mapped is not None:
        return mapped
    lowered = name.lower()
    if any(frag in lowered for frag in _CLERK_DENY_FRAGMENTS):
        return CLERK_DENY
    return CLERK_DENY  # default-deny: unclassified tools are refused until mapped


def _clerk_action_key(name: str, args: dict[str, Any] | None) -> str:
    """Stable per-(tool, args) key an APPROVAL-class call must match in the run's
    server-issued approved-actions set. The session boundary is the per-run
    provisioning of that set; the secret/token never touches the model."""
    try:
        canonical = json.dumps(args or {}, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        canonical = repr(args)
    return hashlib.sha256(f"{name}\x00{canonical}".encode("utf-8")).hexdigest()
_EMAIL_SEARCH_PROVIDERS = ("all", "gmail", "graph", "store")
_EMAIL_DOWNLOAD_PROVIDERS = ("all", "gmail", "graph", "store")
_CHANNEL_SEARCH_CHANNELS = (
    "email_store",
    "whatsapp",
    "slack",
    "transcripts",
    "calendar",
    "documents",
    "sent_emails",
    "rss",
    "substack",
)
_SUBSTACK_COLLECTIONS = ("baker-substack-natesnewsletter",)
_TOOL_TEXT_LIMIT = 8_000
_PLACEHOLDER_EMAIL_RE = re.compile(
    r"(?P<prefix>\bfrom:\s*)?(?P<local>[a-z0-9._%+\-]+)@(?P<domain>[a-z0-9.\-]+)",
    re.I,
)
_PLACEHOLDER_DOMAINS = frozenset({
    "example.com",
    "example.org",
    "example.net",
    "test.com",
    "test.org",
    "test.net",
})
_PLACEHOLDER_LOCAL_PARTS = frozenset({"foo", "bar", "test", "example", "user", "email"})


class ClerkRuntimeError(RuntimeError):
    """Raised for deterministic runtime configuration failures."""


class _TextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _ToolUseBlock:
    def __init__(self, id: str, name: str, input: dict[str, Any]):
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input


class _Usage:
    def __init__(
        self,
        input_tokens: int | None = 0,
        output_tokens: int | None = 0,
        total_tokens: int | None = None,
        cost: float | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        usage_known: bool = True,
    ):
        if usage_known:
            self.prompt_tokens = prompt_tokens if prompt_tokens is not None else input_tokens
            self.completion_tokens = completion_tokens if completion_tokens is not None else output_tokens
        else:
            self.prompt_tokens = prompt_tokens
            self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.cost = cost
        self.input_tokens = int(self.prompt_tokens or 0)
        self.output_tokens = int(self.completion_tokens or 0)


class _ToolResponse:
    def __init__(
        self,
        content: list[Any],
        stop_reason: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int | None = None,
        cost: float | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        usage_known: bool = True,
    ):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Usage(
            input_tokens,
            output_tokens,
            total_tokens=total_tokens,
            cost=cost,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usage_known=usage_known,
        )


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _text_from_blocks(content: list[Any]) -> str:
    return "".join(getattr(block, "text", "") for block in content if getattr(block, "type", "") == "text")


def _tool_uses(content: list[Any]) -> list[Any]:
    return [block for block in content if getattr(block, "type", "") == "tool_use"]


def _validate_qwen_base_url(cfg: Qwen3Config) -> str:
    base_url = (cfg.base_url or "").strip().rstrip("/")
    if not base_url:
        raise ClerkRuntimeError("CLERK_QWEN_BASE_URL is required")

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ClerkRuntimeError("CLERK_QWEN_BASE_URL must be an absolute http(s) URL")

    host = (parsed.hostname or "").rstrip(".").lower()
    resolved_ips = _resolve_host_ips(host)
    if cfg.backend == "qwen3_ollama_local":
        if not resolved_ips or not all(ip.is_loopback for ip in resolved_ips):
            raise ClerkRuntimeError("qwen3_ollama_local backend only permits localhost/127.0.0.1")
    else:
        if parsed.scheme != "https":
            raise ClerkRuntimeError("qwen3_hosted backend requires https")
        if any(_is_forbidden_remote_ip(ip) for ip in resolved_ips):
            raise ClerkRuntimeError("qwen3_hosted backend rejects local/private/reserved endpoints")

    return base_url


def _resolve_host_ips(host: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    if not host:
        raise ClerkRuntimeError("CLERK_QWEN_BASE_URL host is required")
    try:
        return {ipaddress.ip_address(host)}
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ClerkRuntimeError(f"CLERK_QWEN_BASE_URL host could not be resolved: {host}") from e
    ips = {ipaddress.ip_address(info[4][0]) for info in infos}
    if not ips:
        raise ClerkRuntimeError(f"CLERK_QWEN_BASE_URL host resolved to no addresses: {host}")
    return ips


def _is_forbidden_remote_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any((
        ip.is_private,
        ip.is_loopback,
        ip.is_link_local,
        ip.is_reserved,
        ip.is_unspecified,
        ip.is_multicast,
    ))


def _normalize_dropbox_path(path: str) -> str:
    if not path.startswith("/"):
        return ""
    normalized = posixpath.normpath(path)
    if normalized == "." or not normalized.startswith("/"):
        return ""
    return normalized


def _is_allowed_dropbox_path(path: str, prefixes: tuple[str, ...]) -> bool:
    normalized = _normalize_dropbox_path(path)
    if not normalized:
        return False
    for prefix in prefixes:
        allowed = posixpath.normpath(prefix)
        if normalized == allowed or normalized.startswith(allowed.rstrip("/") + "/"):
            return True
    return False


def _is_allowed_local_convert_path(path: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return False
    try:
        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
        resolved.relative_to(temp_root)
    except (OSError, ValueError):
        return False
    return any(part.startswith("clerk_doc_") for part in resolved.parts)


def _openai_messages_from_anthropic(system: str | None, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    if system:
        converted.append({"role": "system", "content": system})

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if not isinstance(content, list):
            converted.append({"role": role, "content": str(content)})
            continue

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in content:
                btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", "")
                if btype == "text":
                    text_parts.append(str(block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")))
                elif btype == "tool_use":
                    tool_id = str(block.get("id", "") if isinstance(block, dict) else getattr(block, "id", ""))
                    name = str(block.get("name", "") if isinstance(block, dict) else getattr(block, "name", ""))
                    inp = block.get("input", {}) if isinstance(block, dict) else getattr(block, "input", {})
                    tool_calls.append({
                        "id": tool_id,
                        "type": "function",
                        "function": {"name": name, "arguments": _safe_json(inp or {})},
                    })
            out: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                out["tool_calls"] = tool_calls
            converted.append(out)
            continue

        tool_results = [
            b for b in content
            if (b.get("type") if isinstance(b, dict) else getattr(b, "type", "")) == "tool_result"
        ]
        if tool_results:
            for block in tool_results:
                if isinstance(block, dict):
                    tool_id = str(block.get("tool_use_id", ""))
                    result = block.get("content", "")
                else:
                    tool_id = str(getattr(block, "tool_use_id", ""))
                    result = getattr(block, "content", "")
                converted.append({"role": "tool", "tool_call_id": tool_id, "content": str(result)})
            continue

        text = "\n".join(
            str(b.get("text", "") if isinstance(b, dict) else getattr(b, "text", ""))
            for b in content
            if (b.get("type") if isinstance(b, dict) else getattr(b, "type", "")) == "text"
        )
        converted.append({"role": role, "content": text})

    return converted


def _openai_tools_from_anthropic(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    out = []
    for tool in tools:
        out.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object"}),
            },
        })
    return out


class _QwenMessages:
    def __init__(self, owner: "Qwen3ToolClient"):
        self._owner = owner

    def create(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> _ToolResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": _openai_messages_from_anthropic(system, messages),
            "max_tokens": max_tokens,
        }
        openai_tools = _openai_tools_from_anthropic(tools)
        if openai_tools:
            payload["tools"] = openai_tools
            # CLERK_QWEN3_TOOL_USE_ENFORCEMENT_1: default "auto"; the agent loop
            # passes tool_choice="required" on the forced-search retry to compel a
            # tool call when the model tried to answer a lookup without searching.
            payload["tool_choice"] = kwargs.get("tool_choice") or "auto"

        headers = {"Content-Type": "application/json"}
        if self._owner.api_key:
            headers["Authorization"] = f"Bearer {self._owner.api_key}"

        resp = self._owner.http.post(
            f"{self._owner.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=min(float(kwargs.get("timeout") or self._owner.timeout), self._owner.timeout),
        )
        resp.raise_for_status()
        data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content: list[Any] = []
        if message.get("content"):
            content.append(_TextBlock(str(message["content"])))

        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            raw_args = function.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except Exception:
                args = {"__malformed_json": str(raw_args)}
            content.append(_ToolUseBlock(
                id=str(call.get("id") or f"call_{len(content)}"),
                name=str(function.get("name") or ""),
                input=args if isinstance(args, dict) else {"value": args},
            ))

        raw_usage = data.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        usage_known = bool(usage)
        prompt_tokens = _int_or_none(usage.get("prompt_tokens")) if isinstance(usage, dict) else None
        completion_tokens = _int_or_none(usage.get("completion_tokens")) if isinstance(usage, dict) else None
        total_tokens = _int_or_none(usage.get("total_tokens")) if isinstance(usage, dict) else None
        if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens
        cost = _float_or_none(usage.get("cost")) if isinstance(usage, dict) else None
        stop_reason = "tool_use" if _tool_uses(content) else "end_turn"
        return _ToolResponse(
            content=content,
            stop_reason=stop_reason,
            input_tokens=prompt_tokens or 0,
            output_tokens=completion_tokens or 0,
            total_tokens=total_tokens,
            cost=cost,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usage_known=usage_known,
        )


class Qwen3ToolClient:
    """Anthropic-style tool client over an OpenAI-compatible Qwen3 endpoint."""

    def __init__(
        self,
        cfg: Qwen3Config | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 60.0,
    ):
        self.cfg = cfg or config.qwen3
        self.base_url = _validate_qwen_base_url(self.cfg)
        self.api_key = (self.cfg.api_key or "").strip()
        if self.cfg.backend != "qwen3_ollama_local" and not self.api_key:
            raise ClerkRuntimeError("CLERK_QWEN_API_KEY is required for qwen3_hosted")
        self.http = http_client or httpx.Client()
        self.timeout = timeout
        self.messages = _QwenMessages(self)


@dataclass
class GuardrailDecision:
    status: str
    reason: str
    item: int | None = None

    @property
    def allowed(self) -> bool:
        return self.status == "allowed"


class ClerkGuardrails:
    """Defense-in-depth prose checks.

    The real security boundary is the tool registry: Phase 1 exposes no send,
    delete, move/archive, payment, slug-creation, or production-change tools.
    These regexes catch obvious user/model instructions early, but tool
    capability checks remain authoritative.
    """

    _hard_blocks: tuple[tuple[int, re.Pattern[str], str], ...] = (
        (1, re.compile(r"\b(pay|wire|transfer|release|send)\s+(money|funds|payment|cash)\b|\bmake\s+a\s+payment\b|\bpay\s+the\s+\w+|\bwire\s+[\d,.]+\s*(eur|usd|gbp|chf|k)\b|\bwire\s+.*\b(to|vendor|supplier)\b", re.I), "money/payment action"),
        (2, re.compile(r"\b(as|pretend to be)\s+(dimitry|the director)\b|\bact\s+as\s+(dimitry|director)\b", re.I), "acting as Director"),
        (3, re.compile(r"\b(write|change|edit|deploy|restart|push|merge)\s+(code|production|prod|render|service|system)\b|\bgit\s+push\b", re.I), "code/production-system change"),
        (4, re.compile(r"\b(create|mint)\s+(a\s+)?matter\s+slug\b|\brestructure\s+(the\s+)?vault\b|\b(rename|move)\s+(vault|folder|directory)\b", re.I), "matter slug or vault restructuring"),
    )
    _approval_required: tuple[tuple[int, re.Pattern[str], str], ...] = (
        (5, re.compile(r"\b(delete|move|archive|purge|remove)\s+(this\s+|the\s+)?(message|email|mail|file|document)\b|\bmark\s+(this\s+|the\s+)?(message|email|mail)\s+(read|unread)\b|\bmark-email\b", re.I), "email/file state change"),
        (6, re.compile(r"\b(send|deliver|email|forward)\s+(an\s+)?(external\s+)?e?-?mail\b|\b(email|forward|send)\b.*\bto\s+[^@\s]+@[^@\s]+\b|\breply\s+to\s+.+\bwith\s+(the\s+)?(file|attachment|document)\b", re.I), "external email send"),
        (7, re.compile(r"\b(irreversible|permanent|permanently|submit\s+filing|sign\s+(contract|agreement)|finalize\s+transaction)\b", re.I), "irreversible action"),
    )

    def check(self, text: str) -> GuardrailDecision:
        haystack = text or ""
        for item, pattern, reason in self._hard_blocks:
            if pattern.search(haystack):
                return GuardrailDecision("blocked", reason, item)
        for item, pattern, reason in self._approval_required:
            if pattern.search(haystack):
                return GuardrailDecision("pending_approval", reason, item)
        return GuardrailDecision("allowed", "ok")


class ClerkToolRegistry:
    """Tool wrappers exposed to the Clerk model."""

    def __init__(
        self,
        dropbox_client: Any | None = None,
        approved_save_paths: set[str] | tuple[str, ...] | None = None,
    ):
        self._dropbox_client = dropbox_client
        self._approved_save_paths = frozenset(
            normalized
            for normalized in (_normalize_dropbox_path(str(path)) for path in (approved_save_paths or ()))
            if normalized
        )

    @property
    def tools(self) -> list[dict[str, Any]]:
        default_mail_provider = self._default_mail_provider()
        return [
            {
                "name": "baker_search",
                "description": (
                    "Unified read-only semantic search across Baker memory/retrieval "
                    "collections, including emails, WhatsApp, Slack, meetings, documents, "
                    "RSS/Substack where indexed, contacts, and project memory."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "email_search",
                "description": (
                    "Search Gmail, Outlook/Graph, and Baker's stored email index. "
                    "Query may be a person's name, subject keywords, or a real known email address. "
                    "Default provider is all (Gmail + Outlook/Graph + store merged). "
                    "Name/person searches that return zero store matches retry with bounded fuzzy matching. "
                    "Do not synthesize or guess an address; when only a name is known, search the name itself "
                    "across provider all instead of a made-up from: filter."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "provider": {
                            "type": "string",
                            "enum": list(_EMAIL_SEARCH_PROVIDERS),
                            "default": default_mail_provider,
                        },
                        "max_results": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "email_download",
                "description": "Download/read an email body and optional attachments by message id.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string"},
                        "provider": {
                            "type": "string",
                            "enum": list(_EMAIL_DOWNLOAD_PROVIDERS),
                            "default": default_mail_provider,
                        },
                        "include_attachments": {"type": "boolean", "default": False},
                    },
                    "required": ["message_id"],
                },
            },
            {
                "name": "channel_search",
                "description": (
                    "Read-only exact search in a specific Baker channel using existing "
                    "retrievers/tables: email_store, whatsapp, slack, transcripts, "
                    "calendar, documents, sent_emails, rss, or substack."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "enum": list(_CHANNEL_SEARCH_CHANNELS)},
                        "query": {"type": "string", "default": ""},
                        "matter_slug": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                    },
                    "required": ["channel"],
                },
            },
            {
                "name": "transcripts_by_matter",
                "description": "Read-only search of Plaud/Fireflies/YouTube meeting transcripts by matter slug.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "matter_slug": {"type": "string"},
                        "query": {"type": "string", "default": ""},
                        "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                    },
                    "required": ["matter_slug"],
                },
            },
            {
                "name": "document_fetch",
                "description": "Fetch a document from Dropbox and return local path plus extracted text when possible.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "source": {"type": "string", "default": "dropbox"}},
                    "required": ["path"],
                },
            },
            {
                "name": "format_convert",
                "description": "Convert a local file or base64 bytes to plain text/markdown.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "local_path": {"type": "string"},
                        "filename": {"type": "string"},
                        "bytes_base64": {"type": "string"},
                        "target_format": {"type": "string", "default": "markdown"},
                    },
                },
            },
            {
                "name": "file_save",
                "description": "Save generated content to Clerk's Dropbox working folder.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "filename": {"type": "string"},
                        "dropbox_path": {"type": "string"},
                    },
                    "required": ["content", "filename"],
                },
            },
            # CLERK_FULL_CAPABILITY_POLICY_1 PR 2a — live web/X search via Grok (xAI).
            # Read-only: returns a cited summary; performs no writes or sends.
            {
                "name": "baker_grok_web_search",
                "description": (
                    "Live web search via Grok (xAI) with citations. Use for current/"
                    "external facts not in Baker's own memory (news, public companies, "
                    "market data, recent events). Returns a summary plus source URLs."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "allowed_domains": {"type": "array", "items": {"type": "string"}},
                        "excluded_domains": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "baker_grok_x_search",
                "description": (
                    "Live X/Twitter search via Grok (xAI). Use for what people are saying "
                    "on X about a topic/person/event. Returns a summary plus cited posts."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "from_date": {"type": "string", "description": "ISO date YYYY-MM-DD lower bound"},
                        "to_date": {"type": "string", "description": "ISO date YYYY-MM-DD upper bound"},
                        "allowed_x_handles": {"type": "array", "items": {"type": "string"}},
                        "excluded_x_handles": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "baker_grok_ask",
                "description": (
                    "Ask Grok (xAI) a plain question under its own training + reasoning "
                    "(no live retrieval). Use for general knowledge / synthesis when Baker "
                    "memory and web/X search are not the right fit."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "instructions": {"type": "string"},
                    },
                    "required": ["prompt"],
                },
            },
        ] + self._extra_read_tool_schemas()

    @staticmethod
    def _extra_read_tool_schemas() -> list[dict[str, Any]]:
        """Read tools wired from governed dispatchers, schemas reused from each
        source's TOOLS (no drift). Each import is lazy + failure-tolerant so a Clerk
        run never breaks if one source module can't load:
          PR 2b — Baker MCP PG reads via baker_mcp._dispatch;
          PR 2c — gmail reads via tools.gmail.dispatch_gmail + claimsmax reads via
                  tools.claimsmax.dispatch_claimsmax."""
        out: list[dict[str, Any]] = []
        try:
            from baker_mcp.baker_mcp_server import TOOLS as _MCP_TOOLS
            out += _pick_tool_schemas(_MCP_TOOLS, frozenset(_CLERK_BAKER_READ_TOOLS + _CLERK_BUS_TOOLS))
        except Exception:
            logger.warning("Clerk: baker_mcp TOOLS import failed — baker reads/bus unavailable")
        try:
            from tools.gmail import GMAIL_TOOLS
            out += _pick_tool_schemas(GMAIL_TOOLS, frozenset(_CLERK_GMAIL_READ_TOOLS))
        except Exception:
            logger.warning("Clerk: gmail TOOLS import failed — gmail reads unavailable")
        try:
            from tools.claimsmax import CLAIMSMAX_TOOLS
            out += _pick_tool_schemas(CLAIMSMAX_TOOLS, frozenset(_CLERK_CLAIMSMAX_READ_TOOLS))
        except Exception:
            logger.warning("Clerk: claimsmax TOOLS import failed — claimsmax reads unavailable")
        return out

    def execute(self, name: str, args: dict[str, Any]) -> str:
        try:
            if name == "baker_search":
                return self._baker_search(args)
            if name == "email_search":
                return self._email_search(args)
            if name == "email_download":
                return self._email_download(args)
            if name == "channel_search":
                return self._channel_search(args)
            if name == "transcripts_by_matter":
                return self._transcripts_by_matter(args)
            if name == "document_fetch":
                return self._document_fetch(args)
            if name == "format_convert":
                return self._format_convert(args)
            if name == "file_save":
                return self._file_save(args)
            if name in ("baker_grok_web_search", "baker_grok_x_search", "baker_grok_ask"):
                return self._grok_dispatch(name, args)
            if name in _CLERK_BAKER_READ_TOOLS or name in _CLERK_BUS_TOOLS:
                return self._baker_mcp_read(name, args)
            if name in _CLERK_GMAIL_READ_TOOLS:
                return self._gmail_dispatch(name, args)
            if name in _CLERK_CLAIMSMAX_READ_TOOLS:
                return self._claimsmax_dispatch(name, args)
            return _safe_json({"error": f"unknown tool: {name}"})
        except BaseException as e:
            # CLERK_SEARCH_BACKEND_FAILSILENT_FIX_1 (B): a backend OUTAGE must
            # render as a retryable error, never silently as "no results found".
            try:
                from memory.retriever import SearchBackendUnavailable
                if isinstance(e, SearchBackendUnavailable):
                    logger.error("Clerk tool %s: search backend unavailable: %s", name, e)
                    return _safe_json({
                        "error": "search backend unavailable — retry",
                        "backend_unavailable": True,
                        "tool": name,
                    })
            except Exception:
                pass
            logger.warning("Clerk tool failed (%s): %s", name, type(e).__name__)
            return _safe_json({"error": f"{name} failed: {type(e).__name__}"})

    @staticmethod
    def _default_mail_provider() -> str:
        provider = str(getattr(config.qwen3, "default_mail_provider", "all") or "all").strip().lower()
        return provider if provider in set(_EMAIL_SEARCH_PROVIDERS) else "all"

    @staticmethod
    def _clamped_limit(value: Any, default: int = 5, upper: int = 20) -> int:
        try:
            limit = int(value or default)
        except (TypeError, ValueError):
            limit = default
        return min(max(limit, 1), upper)

    @staticmethod
    def _parse_tool_json(raw: str) -> Any:
        try:
            return json.loads(raw)
        except Exception:
            return raw

    @staticmethod
    def _payload_error(payload: Any) -> str | None:
        if isinstance(payload, dict):
            error = payload.get("error")
            return str(error) if error else None
        return None

    @staticmethod
    def _payload_count(payload: Any) -> int:
        if isinstance(payload, list):
            return len(payload)
        if not isinstance(payload, dict):
            return 1 if payload else 0
        for key in ("match_count", "count", "total"):
            val = payload.get(key)
            if isinstance(val, int):
                return val
        for key in ("matches", "messages", "results", "articles", "items"):
            val = payload.get(key)
            if isinstance(val, list):
                return len(val)
        return 0

    @staticmethod
    def _normalized_word(value: str) -> str:
        folded = unicodedata.normalize("NFKD", value or "")
        ascii_text = folded.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]", "", ascii_text.lower())

    @classmethod
    def _word_display_map(cls, text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._%+-]{1,}", text or ""):
            normalized = cls._normalized_word(token)
            if normalized and len(normalized) >= 3 and normalized not in out:
                out[normalized] = token.strip("._%+-")
        return out

    @classmethod
    def _name_search_tokens(cls, query: str) -> list[str]:
        if "@" in query:
            return []
        has_person_operator = bool(re.search(r"\b(from|sender|name|person):", query, flags=re.I))
        cleaned = re.sub(r"\b(from|sender|name|person):", " ", query, flags=re.I)
        tokens = [
            cls._normalized_word(token)
            for token in re.findall(r"[A-Za-z][A-Za-z'._-]{1,}", cleaned)
        ]
        tokens = [
            token
            for token in tokens
            if len(token) >= 3 and token not in {"from", "sender", "name", "person", "email", "mail"}
        ]
        return tokens if ((has_person_operator and tokens) or len(tokens) >= 2) and len(tokens) <= 5 else []

    @staticmethod
    def _distance_at_most(left: str, right: str, max_distance: int = 2) -> bool:
        if left == right:
            return True
        if abs(len(left) - len(right)) > max_distance:
            return False
        previous = list(range(len(right) + 1))
        for i, lc in enumerate(left, 1):
            current = [i]
            row_min = i
            for j, rc in enumerate(right, 1):
                cost = 0 if lc == rc else 1
                val = min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + cost,
                )
                current.append(val)
                row_min = min(row_min, val)
            if row_min > max_distance:
                return False
            previous = current
        return previous[-1] <= max_distance

    @classmethod
    def _candidate_words(cls, row: dict[str, Any]) -> list[str]:
        text = " ".join(
            str(row.get(key) or "")
            for key in ("sender_name", "sender_email")
        )
        return [
            normalized
            for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._%+-]{1,}", text)
            if (normalized := cls._normalized_word(token)) and len(normalized) >= 3
        ]

    @classmethod
    def _fuzzy_token_matches(cls, query_tokens: list[str], candidate_tokens: list[str]) -> tuple[bool, dict[str, str]]:
        interpreted: dict[str, str] = {}
        for query_token in query_tokens:
            best = ""
            for candidate_token in candidate_tokens:
                if query_token == candidate_token:
                    best = candidate_token
                    break
                max_distance = 1 if len(query_tokens) == 1 or len(query_token) <= 4 else 2
                if (
                    query_token[0] == candidate_token[0]
                    and cls._distance_at_most(query_token, candidate_token, max_distance=max_distance)
                ):
                    best = candidate_token
                    break
            if not best:
                return False, {}
            if best != query_token:
                interpreted[query_token] = best
        return True, interpreted

    @staticmethod
    def _fuzzy_note(interpreted: dict[str, str]) -> str:
        if not interpreted:
            return "Fuzzy fallback used."
        pairs = ", ".join(f"'{src}' as '{dst}'" for src, dst in interpreted.items())
        return f"Fuzzy fallback used: interpreted {pairs}."

    @staticmethod
    def _is_placeholder_email(local: str, domain: str) -> bool:
        normalized_domain = domain.strip().lower().rstrip(".")
        normalized_local = local.strip().lower()
        if normalized_domain in _PLACEHOLDER_DOMAINS:
            return True
        if normalized_domain == "bar" and normalized_local == "foo":
            return True
        if "." not in normalized_domain and normalized_local in _PLACEHOLDER_LOCAL_PARTS:
            return True
        return False

    @staticmethod
    def _name_from_email_local_part(local: str) -> str:
        cleaned = re.sub(r"[._%+\-]+", " ", local or "")
        cleaned = re.sub(r"\b(test|example|user|email|mail|foo|bar)\b", " ", cleaned, flags=re.I)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _normalize_email_search_args(self, provider: str, query: str, max_results: int) -> tuple[str, str, int, dict[str, Any] | None]:
        names: list[str] = []
        placeholder_count = 0
        for match in _PLACEHOLDER_EMAIL_RE.finditer(query):
            local = match.group("local") or ""
            domain = match.group("domain") or ""
            if not self._is_placeholder_email(local, domain):
                continue
            placeholder_count += 1
            name = self._name_from_email_local_part(local)
            if name:
                names.append(name)

        if placeholder_count == 0:
            return provider, query, max_results, None

        normalized_query = re.sub(r"\s+", " ", " ".join(names)).strip()

        guard = {
            "reason": "fabricated_placeholder_address",
            "original_provider": provider,
            "placeholder_count": placeholder_count,
        }
        if normalized_query:
            guard["normalized_query"] = normalized_query[:120]
        else:
            guard["status"] = "blocked"
            guard["message"] = "Could not derive a search term from placeholder address; give a name or a real email address."
        logger.info(
            "Clerk email_search normalized fabricated placeholder address: provider=%s normalized_name_present=%s placeholder_count=%d",
            provider,
            bool(normalized_query),
            placeholder_count,
        )
        return "all", normalized_query, max(max_results, 10), guard

    def _contexts_json(self, channel: str, contexts: list[Any], limit: int) -> str:
        results = []
        for ctx in contexts[:limit]:
            metadata = dict(getattr(ctx, "metadata", {}) or {})
            content = str(getattr(ctx, "content", "") or "")
            results.append({
                "source": getattr(ctx, "source", channel),
                "score": getattr(ctx, "score", None),
                "label": metadata.get("label") or metadata.get("type") or "",
                "date": metadata.get("date") or metadata.get("created_at") or metadata.get("ingested_at") or "",
                "metadata": metadata,
                "content": content[:_TOOL_TEXT_LIMIT],
            })
        return _safe_json({"channel": channel, "count": len(results), "results": results})

    def _baker_search(self, args: dict[str, Any]) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return _safe_json({"error": "query is required"})
        limit = self._clamped_limit(args.get("max_results"), default=8, upper=20)
        # CLERK_SEARCH_BACKEND_FAILSILENT_FIX_1 (C): reuse the SAME in-process
        # retrieval that GET /api/documents/search uses (PG `documents`
        # semantic+ILIKE — proven to return the real hits, e.g. 43 for "Peter
        # Storer") instead of SentinelRetriever.search_all_collections, whose
        # Qdrant-collection path returned 0 for the identical query. Lazy import:
        # clerk runs inside the dashboard process (POST /api/clerk/run background
        # task), so outputs.dashboard is already loaded at call time. A backend
        # outage raises SearchBackendUnavailable, surfaced fail-loud by execute().
        from outputs.dashboard import search_documents_core

        payload = search_documents_core(query, limit=limit)
        docs = payload.get("results", []) or []
        results = []
        for d in docs[:limit]:
            results.append({
                "source": d.get("source") or "document",
                "score": d.get("score"),
                "label": d.get("title") or "",
                "date": d.get("date") or "",
                "metadata": {
                    "id": d.get("id"),
                    "document_type": d.get("document_type"),
                    "matter": d.get("matter"),
                    "source_path": d.get("source_path"),
                },
                "content": str(d.get("summary") or "")[:_TOOL_TEXT_LIMIT],
            })
        return _safe_json({
            "channel": "baker_search",
            "count": payload.get("total", len(results)),
            "results": results,
            "mode": payload.get("mode"),
        })

    def _email_search(self, args: dict[str, Any]) -> str:
        provider = str(args.get("provider") or self._default_mail_provider()).strip().lower()
        query = str(args.get("query", "")).strip()
        max_results = self._clamped_limit(args.get("max_results"), default=10, upper=50)
        provider, query, max_results, query_guard = self._normalize_email_search_args(provider, query, max_results)
        if query_guard and query_guard.get("status") == "blocked":
            logger.info(
                "Clerk email_search placeholder guard completed: provider=all match_count=0 normalized_name_present=False"
            )
            return _safe_json({
                "provider": "all",
                "status": "blocked",
                "reason": query_guard["message"],
                "match_count": 0,
                "results": {},
                "errors": {},
                "query_guard": query_guard,
            })
        if provider == "all":
            return self._email_search_all(query, max_results, query_guard=query_guard)
        if provider == "graph":
            return self._graph_email_search(query, max_results)
        if provider == "store":
            return self._email_store_search(query, max_results)

        from tools.gmail import dispatch_gmail

        return dispatch_gmail("baker_gmail_search", {"query": query, "max_results": max_results})

    def _email_download(self, args: dict[str, Any]) -> str:
        provider = str(args.get("provider") or self._default_mail_provider()).strip().lower()
        message_id = str(args.get("message_id", "")).strip()
        if provider == "all":
            return self._email_download_all(message_id, bool(args.get("include_attachments")))
        if provider == "graph":
            return self._graph_email_download(message_id)
        if provider == "store":
            return self._email_store_download(message_id)

        from tools.gmail import dispatch_gmail

        raw = dispatch_gmail("baker_gmail_read_message", {"message_id": message_id})
        if not args.get("include_attachments"):
            return raw

        try:
            parsed = json.loads(raw)
        except Exception:
            return raw
        attachments = []
        for att in parsed.get("attachments") or []:
            filename = att.get("filename")
            if not filename:
                continue
            att_raw = dispatch_gmail(
                "baker_gmail_attachment_read",
                {"message_id": message_id, "filename": filename, "include_bytes": False},
            )
            try:
                attachments.append(json.loads(att_raw))
            except Exception:
                attachments.append({"filename": filename, "error": att_raw})
        parsed["attachment_texts"] = attachments
        return _safe_json(parsed)

    def _email_search_all(self, query: str, max_results: int, query_guard: dict[str, Any] | None = None) -> str:
        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        providers = (
            ("graph", lambda: self._graph_email_search(query, max_results)),
            ("gmail", lambda: self._gmail_email_search(query, max_results)),
            ("store", lambda: self._email_store_search(query, max_results)),
        )
        backend_unavailable = False
        for name, fn in providers:
            try:
                payload = self._parse_tool_json(fn())
                error = self._payload_error(payload)
                if error:
                    errors[name] = error
                results[name] = payload
            except BaseException as e:
                # CLERK_SEARCH_BACKEND_FAILSILENT_FIX_1 (B): distinguish a backend
                # OUTAGE (e.g. store provider's PG conn refused) from a provider
                # that ran and found nothing — the former must surface, not read
                # as "no emails found".
                try:
                    from memory.retriever import SearchBackendUnavailable
                    if isinstance(e, SearchBackendUnavailable):
                        backend_unavailable = True
                except Exception:
                    pass
                logger.warning("Clerk email_search provider failed (%s): %s", name, type(e).__name__)
                errors[name] = type(e).__name__
                results[name] = {"error": type(e).__name__}
        match_count = sum(self._payload_count(payload) for payload in results.values())
        if query_guard:
            logger.info(
                "Clerk email_search placeholder guard completed: provider=all match_count=%d normalized_name_present=%s",
                match_count,
                bool(query_guard.get("normalized_query")),
            )
        return _safe_json({
            "provider": "all",
            "query": query,
            "match_count": match_count,
            "results": results,
            "errors": errors,
            # B: when set, the model must say "search backend unavailable — retry",
            # NOT "no emails found" — a match_count of 0 here is NOT trustworthy.
            **({"backend_unavailable": True} if backend_unavailable else {}),
            **({"query_guard": query_guard} if query_guard else {}),
        })

    def _email_download_all(self, message_id: str, include_attachments: bool) -> str:
        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        providers = (
            ("graph", lambda: self._graph_email_download(message_id)),
            ("gmail", lambda: self._gmail_email_download(message_id, include_attachments)),
            ("store", lambda: self._email_store_download(message_id)),
        )
        for name, fn in providers:
            try:
                payload = self._parse_tool_json(fn())
                error = self._payload_error(payload)
                if error:
                    errors[name] = error
                results[name] = payload
            except BaseException as e:
                logger.warning("Clerk email_download provider failed (%s): %s", name, type(e).__name__)
                errors[name] = type(e).__name__
                results[name] = {"error": type(e).__name__}
        return _safe_json({"provider": "all", "message_id": message_id, "results": results, "errors": errors})

    @staticmethod
    def _gmail_email_search(query: str, max_results: int) -> str:
        from tools.gmail import dispatch_gmail

        return dispatch_gmail("baker_gmail_search", {"query": query, "max_results": max_results})

    def _gmail_email_download(self, message_id: str, include_attachments: bool) -> str:
        from tools.gmail import dispatch_gmail

        raw = dispatch_gmail("baker_gmail_read_message", {"message_id": message_id})
        if not include_attachments:
            return raw

        try:
            parsed = json.loads(raw)
        except Exception:
            return raw
        attachments = []
        for att in parsed.get("attachments") or []:
            filename = att.get("filename")
            if not filename:
                continue
            att_raw = dispatch_gmail(
                "baker_gmail_attachment_read",
                {"message_id": message_id, "filename": filename, "include_bytes": False},
            )
            try:
                attachments.append(json.loads(att_raw))
            except Exception:
                attachments.append({"filename": filename, "error": att_raw})
        parsed["attachment_texts"] = attachments
        return _safe_json(parsed)

    def _email_store_search(self, query: str, max_results: int) -> str:
        from memory.retriever import SentinelRetriever

        retriever = SentinelRetriever._get_global_instance()
        contexts = retriever.get_email_messages(query, limit=max_results) if query else retriever.get_recent_emails(limit=max_results)
        raw = self._contexts_json("email_store", contexts, max_results)
        if query:
            payload = self._parse_tool_json(raw)
            if isinstance(payload, dict) and self._payload_count(payload) == 0:
                fuzzy = self._email_store_fuzzy_search(query, max_results)
                fuzzy_payload = self._parse_tool_json(fuzzy)
                if isinstance(fuzzy_payload, dict) and self._payload_count(fuzzy_payload) > 0:
                    return fuzzy
        return raw

    def _email_store_fuzzy_search(self, query: str, max_results: int) -> str:
        query_tokens = self._name_search_tokens(query)
        if not query_tokens:
            return _safe_json({"channel": "email_store", "count": 0, "results": []})

        # Bounded candidate scan: this does not widen returned results. Rows are
        # emitted only when every requested name token fuzzy-matches a candidate token.
        candidate_limit = min(max(max_results * 100, 250), 1000)
        rows = self._query_rows(
            """
            SELECT message_id, thread_id, sender_name, sender_email, subject,
                   LEFT(full_body, %s) AS body_preview, received_date, priority, ingested_at
            FROM email_messages
            WHERE sender_name IS NOT NULL OR sender_email IS NOT NULL
            ORDER BY received_date DESC NULLS LAST, ingested_at DESC NULLS LAST
            LIMIT %s
            """,
            (_TOOL_TEXT_LIMIT, candidate_limit),
        )

        query_display = self._word_display_map(query)
        results: list[dict[str, Any]] = []
        interpreted_display: dict[str, str] = {}
        for row in rows:
            candidate_tokens = self._candidate_words(row)
            matched, interpreted = self._fuzzy_token_matches(query_tokens, candidate_tokens)
            if not matched:
                continue
            candidate_display = self._word_display_map(" ".join(
                str(row.get(key) or "")
                for key in ("sender_name", "sender_email")
            ))
            for src, dst in interpreted.items():
                interpreted_display.setdefault(
                    query_display.get(src, src),
                    candidate_display.get(dst, dst),
                )
            results.append(row)
            if len(results) >= max_results:
                break

        if not results:
            return _safe_json({"channel": "email_store", "count": 0, "results": []})
        note = self._fuzzy_note(interpreted_display)
        return _safe_json({
            "channel": "email_store",
            "count": len(results),
            "results": results,
            "fuzzy": {
                "triggered": True,
                "note": note,
                "interpreted": interpreted_display,
            },
        })

    def _email_store_download(self, message_id: str) -> str:
        rows = self._query_rows(
            """
            SELECT message_id, thread_id, sender_name, sender_email, subject,
                   full_body, received_date, priority, ingested_at
            FROM email_messages
            WHERE message_id = %s
            LIMIT 1
            """,
            (message_id,),
        )
        if not rows:
            return _safe_json({"error": "email not found in email_messages", "message_id": message_id})
        return _safe_json({"provider": "store", "message": rows[0]})

    def _graph_email_search(self, query: str, max_results: int) -> str:
        from kbl.graph_client import GraphClient

        client = GraphClient(GraphConfig())
        if not client.is_ready():
            return _safe_json({"error": "graph mailbox is not ready"})
        page = client.get(
            f"/users/{client.cfg.mail_user}/mailFolders/Inbox/messages",
            params={"$select": "id,conversationId,subject,from,receivedDateTime,bodyPreview", "$top": max_results},
        )
        if page is None:
            return _safe_json({"error": "graph search failed"})
        q = query.lower()
        matches = []
        for msg in page.get("value", []):
            sender = ((msg.get("from") or {}).get("emailAddress") or {})
            hay = " ".join([
                str(msg.get("subject", "")),
                str(msg.get("bodyPreview", "")),
                str(sender.get("address", "")),
                str(sender.get("name", "")),
            ]).lower()
            if not q or q in hay:
                matches.append(msg)
        return _safe_json({"provider": "graph", "match_count": len(matches), "matches": matches[:max_results]})

    def _graph_email_download(self, message_id: str) -> str:
        from kbl.graph_client import GraphClient

        client = GraphClient(GraphConfig())
        if not client.is_ready():
            return _safe_json({"error": "graph mailbox is not ready"})
        msg = client.get(
            f"/users/{client.cfg.mail_user}/messages/{message_id}",
            params={"$select": "id,conversationId,subject,from,receivedDateTime,body,bodyPreview"},
        )
        if msg is None:
            return _safe_json({"error": "graph message fetch failed"})
        return _safe_json(msg)

    def _channel_search(self, args: dict[str, Any]) -> str:
        channel = str(args.get("channel", "")).strip().lower()
        query = str(args.get("query", "")).strip()
        matter_slug = str(args.get("matter_slug", "")).strip()
        limit = self._clamped_limit(args.get("max_results"), default=5, upper=20)
        if channel not in set(_CHANNEL_SEARCH_CHANNELS):
            return _safe_json({"error": f"unsupported channel: {channel}", "allowed": list(_CHANNEL_SEARCH_CHANNELS)})
        if channel == "email_store":
            return self._email_store_search(query, limit)
        if channel == "whatsapp":
            from memory.retriever import SentinelRetriever

            retriever = SentinelRetriever._get_global_instance()
            contexts = retriever.get_whatsapp_messages(query, limit=limit) if query else retriever.get_recent_whatsapp(limit=limit)
            return self._contexts_json("whatsapp", contexts, limit)
        if channel == "transcripts":
            if matter_slug:
                return self._transcripts_by_matter({"matter_slug": matter_slug, "query": query, "max_results": limit})
            from memory.retriever import SentinelRetriever

            retriever = SentinelRetriever._get_global_instance()
            contexts = (
                retriever.get_meeting_transcripts(query, limit=limit)
                if query else retriever.get_recent_meeting_transcripts(limit=limit)
            )
            return self._contexts_json("transcripts", contexts, limit)
        if channel == "calendar":
            return self._calendar_search(query, limit)
        if channel == "documents":
            return self._documents_search(query, matter_slug, limit)
        if channel == "slack":
            return self._slack_search(query, limit)
        if channel == "sent_emails":
            return self._sent_emails_search(query, limit)
        if channel == "rss":
            return self._rss_search(query, limit)
        if channel == "substack":
            return self._substack_search(query, limit)
        return _safe_json({"error": f"unsupported channel: {channel}"})

    def _query_rows(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras

        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql, params)
            rows = [dict(row) for row in cur.fetchall()]
            cur.close()
            return rows
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            store._put_conn(conn)

    @staticmethod
    def _like(query: str) -> str:
        return f"%{query}%"

    def _rows_json(self, channel: str, rows: list[dict[str, Any]]) -> str:
        return _safe_json({"channel": channel, "count": len(rows), "results": rows})

    def _documents_search(self, query: str, matter_slug: str, limit: int) -> str:
        params: list[Any] = [query, self._like(query), self._like(query), self._like(query), self._like(query)]
        matter_clause = ""
        if matter_slug:
            matter_clause = " AND matter_slug ILIKE %s"
            params.append(self._like(matter_slug))
        params.append(limit)
        rows = self._query_rows(
            f"""
            SELECT id, filename, source_path, document_type, matter_slug, parties,
                   token_count, ingested_at, LEFT(full_text, %s) AS text
            FROM documents
            WHERE full_text IS NOT NULL
              AND (%s = '' OR filename ILIKE %s OR source_path ILIKE %s
                   OR matter_slug ILIKE %s OR full_text ILIKE %s)
              {matter_clause}
            ORDER BY ingested_at DESC NULLS LAST
            LIMIT %s
            """,
            (_TOOL_TEXT_LIMIT, *params),
        )
        return self._rows_json("documents", rows)

    def _slack_search(self, query: str, limit: int) -> str:
        like = self._like(query)
        rows = self._query_rows(
            """
            SELECT id, channel_id, channel_name, user_id, user_name,
                   full_text, thread_ts, received_at, ingested_at
            FROM slack_messages
            WHERE %s = '' OR channel_name ILIKE %s OR user_name ILIKE %s OR full_text ILIKE %s
            ORDER BY received_at DESC NULLS LAST, ingested_at DESC NULLS LAST
            LIMIT %s
            """,
            (query, like, like, like, limit),
        )
        return self._rows_json("slack", rows)

    def _sent_emails_search(self, query: str, limit: int) -> str:
        like = self._like(query)
        rows = self._query_rows(
            """
            SELECT id, to_address, subject, body_preview, gmail_message_id,
                   gmail_thread_id, channel, reply_received, reply_received_at,
                   reply_snippet, reply_from, created_at
            FROM sent_emails
            WHERE %s = '' OR to_address ILIKE %s OR subject ILIKE %s
                  OR body_preview ILIKE %s OR reply_snippet ILIKE %s OR reply_from ILIKE %s
            ORDER BY created_at DESC NULLS LAST
            LIMIT %s
            """,
            (query, like, like, like, like, like, limit),
        )
        return self._rows_json("sent_emails", rows)

    def _rss_search(self, query: str, limit: int) -> str:
        like = self._like(query)
        rows = self._query_rows(
            """
            SELECT a.id, a.title, a.url, a.author, a.summary, a.published_at,
                   a.ingested_at, f.title AS feed_title, f.category
            FROM rss_articles a
            LEFT JOIN rss_feeds f ON a.feed_id = f.id
            WHERE %s = '' OR a.title ILIKE %s OR a.summary ILIKE %s
                  OR a.author ILIKE %s OR f.title ILIKE %s OR f.category ILIKE %s
            ORDER BY a.published_at DESC NULLS LAST, a.ingested_at DESC NULLS LAST
            LIMIT %s
            """,
            (query, like, like, like, like, like, limit),
        )
        return self._rows_json("rss", rows)

    def _transcripts_by_matter(self, args: dict[str, Any]) -> str:
        matter_slug = str(args.get("matter_slug", "")).strip()
        query = str(args.get("query", "")).strip()
        limit = self._clamped_limit(args.get("max_results"), default=5, upper=20)
        if not matter_slug:
            return _safe_json({"error": "matter_slug is required"})
        like = self._like(query)
        rows = self._query_rows(
            """
            SELECT id, title, meeting_date, duration, organizer, participants,
                   summary, source, matter_slug, ingested_at,
                   LEFT(full_transcript, %s) AS transcript
            FROM meeting_transcripts
            WHERE matter_slug ILIKE %s
              AND (%s = '' OR title ILIKE %s OR organizer ILIKE %s
                   OR participants ILIKE %s OR summary ILIKE %s OR full_transcript ILIKE %s)
            ORDER BY meeting_date DESC NULLS LAST, ingested_at DESC NULLS LAST
            LIMIT %s
            """,
            (_TOOL_TEXT_LIMIT, self._like(matter_slug), query, like, like, like, like, like, limit),
        )
        return self._rows_json("transcripts_by_matter", rows)

    def _substack_search(self, query: str, limit: int) -> str:
        if not query:
            return _safe_json({"channel": "substack", "count": 0, "results": [], "note": "query is required for Substack vector search"})
        from memory.retriever import SentinelRetriever

        retriever = SentinelRetriever._get_global_instance()
        query_vector = retriever._embed_query(query)
        contexts = []
        errors: dict[str, str] = {}
        for collection in _SUBSTACK_COLLECTIONS:
            try:
                contexts.extend(
                    retriever.search_collection(
                        query_vector=query_vector,
                        collection=collection,
                        limit=limit,
                        score_threshold=0.2,
                    )
                )
            except Exception as e:
                errors[collection] = type(e).__name__
        contexts.sort(key=lambda ctx: getattr(ctx, "score", 0) or 0, reverse=True)
        payload = json.loads(self._contexts_json("substack", contexts, limit))
        payload["errors"] = errors
        return _safe_json(payload)

    def _calendar_search(self, query: str, limit: int) -> str:
        errors: dict[str, str] = {}
        meetings: list[dict[str, Any]] = []
        for name, fn in (
            ("google_today", self._poll_google_today),
            ("google_upcoming", self._poll_google_upcoming),
            ("exchange_today", self._poll_exchange_today),
        ):
            try:
                meetings.extend(fn())
            except BaseException as e:
                logger.warning("Clerk calendar source failed (%s): %s", name, type(e).__name__)
                errors[name] = type(e).__name__

        seen: set[tuple[str, str]] = set()
        deduped = []
        for meeting in meetings:
            key = (str(meeting.get("source", "")), str(meeting.get("id", "")))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(meeting)

        if query:
            q = query.lower()
            filtered = []
            for meeting in deduped:
                attendees = " ".join(
                    f"{a.get('name', '')} {a.get('email', '')}"
                    for a in meeting.get("attendees", [])
                    if isinstance(a, dict)
                )
                hay = " ".join([
                    str(meeting.get("title", "")),
                    str(meeting.get("description", "")),
                    str(meeting.get("location", "")),
                    str(meeting.get("organizer", "")),
                    attendees,
                ]).lower()
                if q in hay:
                    filtered.append(meeting)
            deduped = filtered

        deduped.sort(key=lambda item: str(item.get("start", "")))
        return _safe_json({"channel": "calendar", "count": len(deduped[:limit]), "results": deduped[:limit], "errors": errors})

    @staticmethod
    def _poll_google_today() -> list[dict[str, Any]]:
        from triggers.calendar_trigger import poll_todays_meetings

        return poll_todays_meetings()

    @staticmethod
    def _poll_google_upcoming() -> list[dict[str, Any]]:
        from triggers.calendar_trigger import poll_upcoming_meetings

        return poll_upcoming_meetings(hours_ahead=72)

    @staticmethod
    def _poll_exchange_today() -> list[dict[str, Any]]:
        from triggers.exchange_calendar_poller import poll_exchange_todays_meetings

        return poll_exchange_todays_meetings()

    def _document_fetch(self, args: dict[str, Any]) -> str:
        source = args.get("source", "dropbox")
        path = str(args.get("path", "")).strip()
        if not path or ".." in Path(path).parts:
            return _safe_json({"error": "invalid document path"})
        if not _is_allowed_dropbox_path(path, _ALLOWED_FETCH_PREFIXES):
            return _safe_json({
                "status": "blocked",
                "reason": "document path outside Clerk-readable Dropbox prefixes",
                "path": path,
            })
        if source != "dropbox":
            return _safe_json({"error": f"unsupported document source: {source}"})

        client = self._dropbox_client
        if client is None:
            from triggers.dropbox_client import DropboxClient
            client = DropboxClient._get_global_instance()

        tmpdir = tempfile.mkdtemp(prefix="clerk_doc_")
        local = client.download_file(path, Path(tmpdir))
        text = ""
        try:
            from tools.ingest.extractors import extract
            text = extract(local) or ""
        except Exception as e:
            logger.warning("document_fetch extraction failed: %s", type(e).__name__)
        return _safe_json({"source": "dropbox", "path": path, "local_path": str(local), "text": text})

    def _format_convert(self, args: dict[str, Any]) -> str:
        local_path = str(args.get("local_path", "")).strip()
        if local_path:
            p = Path(local_path)
            if not p.exists() or not p.is_file():
                return _safe_json({"error": "local_path does not exist"})
            if not _is_allowed_local_convert_path(p):
                return _safe_json({"status": "blocked", "reason": "local_path outside Clerk temp workspace"})
            from tools.ingest.extractors import extract
            return _safe_json({"target_format": args.get("target_format", "markdown"), "text": extract(p) or ""})

        raw = args.get("bytes_base64", "")
        filename = str(args.get("filename", "document.bin"))
        if not raw:
            return _safe_json({"error": "local_path or bytes_base64 is required"})
        ext = Path(filename).suffix.lower()
        file_bytes = base64.standard_b64decode(raw)
        from scripts.extract_gmail import _extract_text_from_bytes
        text = _extract_text_from_bytes(file_bytes, filename, ext) or ""
        return _safe_json({"target_format": args.get("target_format", "markdown"), "text": text})

    def _file_save(self, args: dict[str, Any]) -> str:
        content = str(args.get("content", ""))
        filename = Path(str(args.get("filename", "clerk-output.md"))).name or "clerk-output.md"
        dropbox_path = str(args.get("dropbox_path", "")).strip()
        if not dropbox_path:
            dropbox_path = f"{_DEFAULT_SAVE_PREFIX}/{filename}"
        if not dropbox_path.startswith("/"):
            return _safe_json({"error": "dropbox_path must be absolute"})
        normalized_path = _normalize_dropbox_path(dropbox_path)
        if not normalized_path:
            return _safe_json({"error": "invalid dropbox_path"})
        if (
            not _is_allowed_dropbox_path(normalized_path, _ALLOWED_SAVE_PREFIXES)
            and normalized_path not in self._approved_save_paths
        ):
            return _safe_json({
                "status": "blocked",
                "reason": "dropbox_path outside Clerk working folder",
                "dropbox_path": normalized_path,
            })
        dropbox_path = normalized_path

        client = self._dropbox_client
        if client is None:
            from triggers.dropbox_client import DropboxClient
            client = DropboxClient._get_global_instance()

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=Path(filename).suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            meta = client.upload_file(tmp_path, dropbox_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return _safe_json({"status": "ready", "path": meta.get("path_display", dropbox_path), "metadata": meta})

    # ── CLERK_FULL_CAPABILITY_POLICY_1 PR 2b — Baker MCP reads via governed _dispatch ──
    def _baker_mcp_read(self, name: str, args: dict[str, Any]) -> str:
        """Route a Baker MCP tool through baker_mcp.baker_mcp_server._dispatch — the
        SAME sync entrypoint the MCP server's call_tool uses. Serves the PG SELECT
        reads (PR 2b) AND the internal-bus inbox_read/post/ack (PR 2d-1, ALLOW =
        internal coordination). Only ALLOW-class names reach here (the policy gate
        blocks DENY/APPROVAL before execute); external sends are DENY and never wired.
        Returns _dispatch's text; the outer execute() try/except renders failures cleanly."""
        from baker_mcp.baker_mcp_server import _dispatch
        return _dispatch(name, args if isinstance(args, dict) else {})

    # ── CLERK_FULL_CAPABILITY_POLICY_1 PR 2c — gmail + claimsmax reads via dispatchers ──
    def _gmail_dispatch(self, name: str, args: dict[str, Any]) -> str:
        """Route Clerk's gmail reads through tools.gmail.dispatch_gmail — the governed
        sync entrypoint the MCP server uses. Only the read names reach here (policy
        gate + read-only registration); execute() try/except renders failures cleanly."""
        from tools.gmail import dispatch_gmail
        return dispatch_gmail(name, args if isinstance(args, dict) else {})

    def _claimsmax_dispatch(self, name: str, args: dict[str, Any]) -> str:
        """Route Clerk's claimsmax reads through tools.claimsmax.dispatch_claimsmax —
        the governed sync entrypoint. Only the 3 read names are registered + ALLOW;
        ask/investigate/save/convert (cost/side-effects) are DENY/APPROVAL and unwired."""
        from tools.claimsmax import dispatch_claimsmax
        return dispatch_claimsmax(name, args if isinstance(args, dict) else {})

    # ── CLERK_FULL_CAPABILITY_POLICY_1 PR 2a — live web/X search via Grok (xAI) ──
    def _grok_dispatch(self, name: str, args: dict[str, Any]) -> str:
        """Route Clerk's Grok tools through tools.grok.dispatch_grok so they inherit
        the SAME cost circuit-breaker + usage logging (source=grok_realtime) +
        timeout validation as every other Grok caller. Calling GrokClient directly
        would be an unmetered live-xAI path for an autonomous model (G0 #2391)."""
        from tools.grok import dispatch_grok
        return dispatch_grok(name, args)


_CLERK_SYSTEM_PROMPT = """You are Clerk, Brisen's document clerk.
Use read-only tools to search Baker memory across Gmail, Outlook/Graph, the stored
email index, WhatsApp, Slack, meeting transcripts (Plaud/Fireflies/YouTube),
calendar/events, Dropbox/documents, sent emails, RSS/Substack, and unified semantic
retrieval. Use conversion/document tools when a fetched document needs extraction,
and save only Director-reviewable files to Clerk's working folder.
When the user gives a person's name without an email address, search by the name
itself across provider="all" with max_results at least 10. Never invent, guess,
or fabricate email addresses or placeholder domains such as example.com or test.com;
if only a name is known, query the name itself, not a made-up from: filter.
If a name/person search comes back empty, use the fuzzy fallback exposed by email_search
instead of declaring not found; report any interpretation, e.g. interpreted a misspelled
first name as the matched name.
Never execute money/payment actions, impersonate the Director, change code/production systems,
create matter slugs, or restructure vault/folders. Posting to the internal Brisen agent bus
(lead, deputy, clerk, b1-b4, and other fleet agents) is internal coordination: allowed, not
an external send, and not Director impersonation. External send means email/WhatsApp/Slack or
other messages to humans outside the agent fleet. Delete/move/archive/mark-email, external send,
and irreversible actions require explicit Director approval and otherwise become draft/pending outputs.
Answer in plain text only. Do not use markdown syntax: no bold markers, markdown headers,
backticks, markdown tables, or fenced code blocks. Lead with the answer in one short line,
then add only the support needed. Use short labeled lines or simple numbered points when helpful.
Be terse, plain English, and avoid filler.
DIRECTOR-FACING REGISTER (CLERK_DIRECTOR_FACING_REGISTER_1): you are addressing the
Director directly. Lead with the bottom-line answer first, then the supporting detail.
Use plain English; spell out jargon and abbreviations. When — and ONLY when — you
surface a real choice for the Director (genuinely competing options or a recommended
next action), close with a single line: Recommendation: <option> - <one short why>.
Do NOT add a Recommendation line to a plain factual answer where there is no decision
to make. This is a light phrasing layer only; it never overrides the mandatory tool-use
rule below.
Return concise status with Ready: <path> / Source: <source> when complete.
MANDATORY TOOL USE FOR LOOKUPS (CLERK_QWEN3_TOOL_USE_ENFORCEMENT_1): for ANY request
to find, search, look up, count, list, or report what exists in Baker's data
(documents, emails, messages, transcripts, contacts, deals), you MUST call a search
tool (baker_search, email_search, channel_search, or transcripts_by_matter) BEFORE
answering. NEVER claim you searched, report a count, or say "no documents/results/
matches found" unless you actually called a search tool in this turn. If you have
not searched yet, call the tool now instead of answering from memory."""


# CLERK_QWEN3_TOOL_USE_ENFORCEMENT_1 — structural backstop for the system-prompt
# mandate above. Qwen3 on tool_choice="auto" sometimes answers a lookup WITHOUT
# calling a search tool and fabricates a "searched, found nothing" reply (observed:
# "No documents found", tool_calls=[], iterations=1). The agent loop detects that
# shape and forces ONE search retry; if a tool still doesn't fire it returns a clear
# non-answer — never the fabricated empty.
_FORCE_SEARCH_NUDGE = (
    "You answered without calling any search tool. That is not allowed for a lookup. "
    "Call the appropriate search tool now (baker_search / email_search / "
    "channel_search / transcripts_by_matter) with the query, then answer ONLY from "
    "the tool result. Do not claim a result you did not retrieve."
)
_CLERK_SEARCH_FAILLOUD_MSG = (
    "I couldn't run the search this turn — please retry. "
    "(I won't report results I didn't actually retrieve.)"
)
# CLERK_QWEN3_GUARD_COVERAGE_1 (re-architected per lead #2264 + codex G3): the
# PRIMARY trigger is STRUCTURAL — fire when the USER TASK is lookup-shaped AND zero
# search tools fired this turn. That catches a fabricated empty REGARDLESS of how
# the answer is phrased, ending the phrasing whack-a-mole. The answer-phrasing regex
# below is the SECONDARY safety net (for lookup tasks the classifier missed),
# tightened to require a data object so it stops over-triggering on chit-chat.

# A lookup is GROUNDED iff a search OR a fetch tool ran this turn.
# (codex G3 Finding B: a successful document_fetch/email_download retrieves real
# data and must NOT be forced into a search retry.)
_SEARCH_TOOLS = frozenset({"baker_search", "email_search", "channel_search", "transcripts_by_matter"})
# CLERK_FULL_CAPABILITY_POLICY_1 PR 2a: a live web/X retrieval also grounds a lookup
# answer (the model really did retrieve), so it must NOT trip the fabrication-retry.
# grok_ask is NOT here — it is training-knowledge Q&A, not retrieval.
_GROUNDING_TOOLS = _SEARCH_TOOLS | frozenset({
    "document_fetch", "email_download", "baker_grok_web_search", "baker_grok_x_search",
}) | frozenset(_CLERK_BAKER_READ_TOOLS) | frozenset(_CLERK_GMAIL_READ_TOOLS) | frozenset(_CLERK_CLAIMSMAX_READ_TOOLS)
# ^ PR 2b/2c: Baker MCP + gmail + claimsmax reads retrieve real data, so they ground a lookup answer

# Lookup INTENT in the user task (verbs/phrases that demand a retrieval). codex G3
# Finding A: added terse "what do we have on / anything on / what's on / got
# anything" forms that imply a lookup with no explicit data noun.
_LOOKUP_INTENT_RE = re.compile(
    r"\b(?:find|search|look\s*up|look\s+for|how\s+many|count|list|pull(?:\s+up)?|retrieve|"
    r"show\s+me|tell\s+me\s+about|dig\s+up|do\s+we\s+have|do\s+you\s+have|have\s+we\s+got|"
    r"got\s+anything|(?:anything|info|information|details|something|stuff)\s+(?:on|about)|"
    r"what(?:'s|\s+do\s+we\s+have)\s+on|"
    r"is\s+there|are\s+there|who\s+(?:is|are|sent|wrote|mentioned)|what\s+about|mentions?)\b",
    re.IGNORECASE,
)
# Baker DATA-context nouns in the user task (broad — what the lookup is over).
_DATA_CONTEXT_RE = re.compile(
    r"\b(?:documents?|docs?|emails?|e-mails?|mail|messages?|transcripts?|files?|records?|"
    r"results?|contacts?|deals?|meetings?|notes?|memos?|threads?|attachments?|correspondence|"
    r"whatsapp|slack|gmail|outlook|inbox|calendar|events?)\b",
    re.IGNORECASE,
)
# ACTION verbs — a data noun under one of these is a do-something task, NOT a
# lookup (so "draft an email" / "save this note" / "convert this file" do not
# trip the noun-only lookup branch below).
_ACTION_VERB_RE = re.compile(
    r"\b(?:draft|write|compose|reply|respond|forward|send|email|message|save|store|"
    r"convert|create|make|delete|remove|move|archive|rename|upload|attach|schedule|"
    r"post|file|sign|edit|update|summari[sz]e|translate)\b",
    re.IGNORECASE,
)


def _task_is_lookup_shaped(task: str) -> bool:
    """PRIMARY (structural): the user asked to find/count/list ... over Baker data.
    True when (a) explicit lookup intent is present, OR (b) a data-context noun is
    present with NO action verb (terse "Peter Storer emails", "X docs"). Phrasing-
    independent, so a fabricated empty on a lookup is caught by (lookup-task AND
    no-grounding-tool) no matter how the ANSWER is worded."""
    t = task or ""
    if _LOOKUP_INTENT_RE.search(t):
        return True
    return bool(_DATA_CONTEXT_RE.search(t)) and not bool(_ACTION_VERB_RE.search(t))


# Negated modals: couldn't/could not, cannot/can not/can't, don't/do not,
# doesn't/does not, didn't/did not. ("can't" = can+'t, so it needs its own arm.)
_NEG = r"(?:could\s*n[o']?t|can\s*n[o']?t|can[o']?t|do\s*n[o']?t|does\s*n[o']?t|did\s*n[o']?t)"
# Answer-side Baker-data nouns (tight) + an optional determiner/adjective run so
# "no relevant documents" / "any matching emails" / "the file" all resolve.
_DATA_NOUN = r"(?:documents?|results?|matches|emails?|messages?|records?|hits?|transcripts?|files?)"
_OBJ = rf"(?:any\s+|a\s+|an\s+|the\s+|relevant\s+|matching\s+|related\s+|such\s+|other\s+)*{_DATA_NOUN}"

# SECONDARY safety net. Tightened per codex G3: every verb arm REQUIRES a data
# object, so "I did not find that funny" / "I did not appear at the meeting" /
# "This does not appear to be a lookup request" / "I don't have any questions" all
# stay False. Curly apostrophes are normalized to ASCII before matching. Bounded
# alternations only (no ReDoS).
_LOOKUP_ASSERTION_RE = re.compile(
    rf"\bno\s+(?:relevant\s+|matching\s+|related\s+|such\s+|other\s+)*{_DATA_NOUN}\b"
    rf"|\bzero\s+{_DATA_NOUN}\b"
    r"|\bfound\s+(?:no|nothing|none|\d+)\b"
    r"|\bnothing\s+(?:found|came\s+back|turned\s+up)\b"
    r"|\b(?:came\s+up\s+empty|turned\s+up\s+(?:nothing|empty))\b"
    rf"|\b{_NEG}\s+(?:find|locate|spot|identify|see|have)\s+{_OBJ}\b"
    rf"|\b(?:do|does|did)\s*n[o']?t\s+(?:appear|seem)s?\s+to\s+(?:be\s+|exist\s+|contain\s+|have\s+|show\s+|include\s+)?{_OBJ}\b"
    rf"|\bunable\s+to\s+(?:find|locate|see|identify|retrieve)\s+{_OBJ}\b"
    rf"|\b\d+\s+{_DATA_NOUN}\b"
    r"|\bI\s+(?:searched|looked|checked)\b"
    r"|\bsearch(?:ed)?\s+(?:returned|came\s+back|found|yielded)\b"
    # CLERK_QWEN3_GUARD_COVERAGE_1 #2270 (3) — bias-toward-firing absence idioms
    # WITHOUT a hard data noun. Safe to loosen: grounding (any retrieval tool)
    # short-circuits the guard, so these can only over-fire on a no-tool task
    # (LOW per the convergence bar), never block a real workflow.
    rf"|\b{_NEG}\s+see\s+(?:any(?:thing)?|nothing)\b"
    r"|\bnothing\s+(?:on|about|regarding|matching|relevant\s+to)\b"
    r"|\bno\s+(?:relevant|matching|related)\b",
    re.IGNORECASE,
)


def _asserts_unsubstantiated_lookup(answer: str) -> bool:
    """SECONDARY: the answer claims a search outcome (count / 'no <data>' / 'I
    searched') with a data object — backup for lookup tasks the classifier missed."""
    normalized = (answer or "").replace("’", "'")  # curly -> ASCII apostrophe
    return bool(_LOOKUP_ASSERTION_RE.search(normalized))


def _verified_saved_path(file_save_result: str) -> str | None:
    """CLERK_READY_PATH_CONTRADICTION_FIX_1: return the real Dropbox path from a
    SUCCESSFUL file_save result ONLY. _file_save returns {"status":"ready","path":
    <real path_display>} on a genuine upload, or {"status":"blocked",...} when the
    requested path is outside Clerk's working folder. A Ready/draft path may be
    advertised to the Director only when it is grounded in a status:"ready" result —
    so a blocked/rejected path, or a path the model merely asserted in free text
    (it never reaches this function), can never be surfaced as a saved file."""
    try:
        data = json.loads(file_save_result)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("status") != "ready":
        return None
    path = data.get("path")
    return path if isinstance(path, str) and path.strip() else None


class ClerkAgent:
    """Bounded Clerk tool loop with Qwen default and Gemini Pro escalation."""

    def __init__(
        self,
        model_client: Any | None = None,
        escalation_client: Any | None = None,
        registry: ClerkToolRegistry | None = None,
        guardrails: ClerkGuardrails | None = None,
        cfg: Qwen3Config | None = None,
        clock: Any | None = None,
        approved_actions: set[str] | frozenset[str] | tuple[str, ...] | None = None,
    ):
        self.cfg = cfg or config.qwen3
        self.model_client = model_client
        self.escalation_client = escalation_client
        self.registry = registry or ClerkToolRegistry()
        self.guardrails = guardrails or ClerkGuardrails()
        self.clock = clock or time.monotonic
        # CLERK_FULL_CAPABILITY_POLICY_1: server-issued approval action-keys for THIS
        # run (the per-run set is the session boundary). Empty by default — the model
        # cannot populate it, so APPROVAL-class tools return pending_approval and
        # DENY-class tools refuse regardless.
        self._approved_actions = frozenset(approved_actions or ())

    def _client(self) -> Any:
        if self.model_client is not None:
            return self.model_client
        return Qwen3ToolClient(self.cfg)

    def run(self, task: str) -> dict[str, Any]:
        guard = self.guardrails.check(task)
        if not guard.allowed:
            return self._guardrail_result(guard)

        started = self.clock()
        timeout_s = max(int(self.cfg.task_timeout_s or 180), 1)
        max_steps = max(int(self.cfg.max_steps or 12), 1)
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        tool_log: list[dict[str, Any]] = []
        # CLERK_READY_PATH_CONTRADICTION_FIX_1: verified Dropbox paths from
        # SUCCESSFUL file_save results only — the sole grounded source for any
        # Ready/draft path the worker later surfaces to the Director.
        saved_paths: list[str] = []
        usage_totals = self._new_usage_totals()
        schema_failures = 0
        client = self._client()
        # CLERK_QWEN3_TOOL_USE_ENFORCEMENT_1: one bounded forced-search retry.
        forced_retry_used = False
        force_tool_choice = False

        for step in range(max_steps):
            remaining_s = timeout_s - (self.clock() - started)
            if remaining_s <= 0:
                return {"status": "timeout", "reason": "task timeout exceeded", "tool_calls": tool_log}

            try:
                response = client.messages.create(
                    model=self.cfg.model,
                    max_tokens=2000,
                    system=_CLERK_SYSTEM_PROMPT,
                    messages=messages,
                    tools=self.registry.tools,
                    timeout=max(0.001, remaining_s),
                    # "required" only on the forced retry — compels a real tool call.
                    tool_choice=("required" if force_tool_choice else "auto"),
                )
            except Exception as e:
                logger.warning("Clerk model call failed: %s", type(e).__name__)
                return {
                    "status": "blocked",
                    "reason": "model call failed",
                    "error_type": type(e).__name__,
                    "tool_calls": tool_log,
                }
            force_tool_choice = False  # consumed by the call above
            in_tok, out_tok = self._usage(response)
            self._record_usage(usage_totals, response)
            self._log_cost(self.cfg.model, in_tok, out_tok)

            if response.stop_reason == "end_turn":
                answer = _text_from_blocks(response.content)
                # CLERK_QWEN3_TOOL_USE_ENFORCEMENT_1 / _GUARD_COVERAGE_1 guard.
                # PRIMARY (structural, phrasing-independent): a lookup-shaped TASK
                # answered with NO search tool call cannot be trusted. SECONDARY net:
                # the answer asserts a search outcome with a data object. Either, when
                # no search tool fired, forces one retry then fails loud.
                grounded = any(c.get("name") in _GROUNDING_TOOLS for c in tool_log)
                if (not grounded) and (
                    _task_is_lookup_shaped(task) or _asserts_unsubstantiated_lookup(answer)
                ):
                    if not forced_retry_used:
                        forced_retry_used = True
                        force_tool_choice = True
                        logger.warning(
                            "Clerk: lookup answer with zero tool calls — forcing one search retry"
                        )
                        messages.append({"role": "user", "content": _FORCE_SEARCH_NUDGE})
                        continue
                    # Bounded: forced retry already used and STILL no tool call (e.g.
                    # backend ignored tool_choice='required'). Fail loud — never
                    # surface the fabricated empty/count.
                    logger.error(
                        "Clerk: forced search retry produced no tool call — failing loud"
                    )
                    return {
                        "status": "needs_retry",
                        "answer": _CLERK_SEARCH_FAILLOUD_MSG,
                        "iterations": step + 1,
                        "tool_calls": tool_log,
                        "usage": self._usage_payload(usage_totals),
                        "tool_enforcement": "forced_retry_no_tool_call",
                        "saved_paths": saved_paths,
                    }
                usage_payload = self._usage_payload(usage_totals)
                return {
                    "status": "ready",
                    "answer": answer,
                    "iterations": step + 1,
                    "tool_calls": tool_log,
                    "usage": usage_payload,
                    "saved_paths": saved_paths,
                }

            uses = _tool_uses(response.content)
            if not uses:
                return {
                    "status": "blocked",
                    "reason": f"unexpected stop_reason={response.stop_reason}",
                    "usage": self._usage_payload(usage_totals),
                }

            assistant_content = self._assistant_content(response.content)
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results: list[dict[str, Any]] = []
            for tool_use in uses:
                # CLERK_FULL_CAPABILITY_POLICY_1: capability gate runs FIRST —
                # DENY (incl. unknown, fail-closed) refuses outright even with a
                # valid approval key; APPROVAL returns pending_approval unless this
                # exact (tool,args) was server-approved for this run. ALLOW falls
                # through to schema validation + execute.
                policy_block = self._policy_gate(tool_use, tool_log, usage_totals, saved_paths)
                if policy_block is not None:
                    return policy_block
                valid, validation_error = self._validate_tool_use(tool_use)
                if not valid:
                    schema_failures += 1
                    if schema_failures >= 2:
                        remaining_s = timeout_s - (self.clock() - started)
                        if remaining_s <= 0:
                            return {"status": "timeout", "reason": "task timeout exceeded", "tool_calls": tool_log}
                        return self._escalate(
                            messages,
                            tool_log,
                            f"repeated schema/tool failure: {validation_error}",
                            usage_totals=usage_totals,
                            timeout_s=max(0.001, remaining_s),
                        )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": _safe_json({"error": validation_error, "retry": "call the tool again with valid JSON"}),
                        "is_error": True,
                    })
                    continue

                guard = self.guardrails.check(_safe_json(tool_use.input))
                if not guard.allowed:
                    return self._guardrail_result(guard, tool_log=tool_log, usage_totals=usage_totals)

                t0 = self.clock()
                result = self.registry.execute(tool_use.name, tool_use.input)
                elapsed_ms = int((self.clock() - t0) * 1000)
                tool_log.append({"name": tool_use.name, "input": tool_use.input, "duration_ms": elapsed_ms})
                if tool_use.name == "file_save":
                    verified = _verified_saved_path(result)
                    if verified:
                        saved_paths.append(verified)
                tool_results.append({"type": "tool_result", "tool_use_id": tool_use.id, "content": result})

            messages.append({"role": "user", "content": tool_results})

        return {
            "status": "blocked",
            "reason": "max_steps exceeded",
            "tool_calls": tool_log,
            "usage": self._usage_payload(usage_totals),
            "saved_paths": saved_paths,
        }

    def _escalate(
        self,
        messages: list[dict[str, Any]],
        tool_log: list[dict[str, Any]],
        reason: str,
        usage_totals: dict[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        usage_payload = self._usage_payload(usage_totals) if usage_totals is not None else None
        client = self.escalation_client
        if client is None:
            from orchestrator.gemini_client import GeminiToolClient
            client = GeminiToolClient()
        try:
            response = client.messages.create(
                model=config.gemini.pro_model,
                max_tokens=2000,
                system=f"{_CLERK_SYSTEM_PROMPT}\nEscalation reason: {reason}",
                messages=messages,
                tools=self.registry.tools,
                timeout=timeout_s,
            )
        except Exception as e:
            logger.warning("Clerk escalation call failed: %s", type(e).__name__)
            return {
                "status": "blocked",
                "reason": "escalation model call failed",
                "error_type": type(e).__name__,
                "tool_calls": tool_log,
                **({"usage": usage_payload} if usage_payload is not None else {}),
            }
        in_tok, out_tok = self._usage(response)
        self._log_cost(config.gemini.pro_model, in_tok, out_tok)
        if response.stop_reason == "tool_use":
            results = []
            saved_paths: list[str] = []
            for tool_use in _tool_uses(response.content):
                # CLERK_FULL_CAPABILITY_POLICY_1: the escalation (Gemini) path is gated
                # too, so it can never become a capability bypass.
                policy_block = self._policy_gate(tool_use, tool_log, usage_totals, saved_paths)
                if policy_block is not None:
                    return {**policy_block, "escalated": True, "reason": reason}
                valid, validation_error = self._validate_tool_use(tool_use)
                if not valid:
                    results.append({"tool": getattr(tool_use, "name", ""), "error": validation_error})
                    continue
                guard = self.guardrails.check(_safe_json(tool_use.input))
                if not guard.allowed:
                    return self._guardrail_result(guard, tool_log=tool_log, usage_totals=usage_totals)
                result = self.registry.execute(tool_use.name, tool_use.input)
                tool_log.append({"name": tool_use.name, "input": tool_use.input, "duration_ms": 0, "escalated": True})
                if tool_use.name == "file_save":
                    verified = _verified_saved_path(result)
                    if verified:
                        saved_paths.append(verified)
                results.append({"tool": tool_use.name, "result": result})
            return {
                "status": "ready",
                "answer": _safe_json(results),
                "escalated": True,
                "reason": reason,
                "tool_calls": tool_log,
                "saved_paths": saved_paths,
                **({"usage": usage_payload} if usage_payload is not None else {}),
            }
        return {
            "status": "ready",
            "answer": _text_from_blocks(response.content),
            "escalated": True,
            "reason": reason,
            "tool_calls": tool_log,
            "saved_paths": [],
            **({"usage": usage_payload} if usage_payload is not None else {}),
        }

    @staticmethod
    def _assistant_content(content: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for block in content:
            if getattr(block, "type", "") == "text":
                out.append({"type": "text", "text": block.text})
            elif getattr(block, "type", "") == "tool_use":
                out.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
        return out

    def _policy_gate(
        self,
        tool_use: Any,
        tool_log: list[dict[str, Any]],
        usage_totals: dict[str, Any],
        saved_paths: list[str],
    ) -> dict[str, Any] | None:
        """CLERK_FULL_CAPABILITY_POLICY_1 capability gate. Returns a TERMINAL result
        dict to abort the run when the tool is DENY (refuse, even with a valid key)
        or APPROVAL-without-approval (pending_approval); returns None to proceed."""
        name = getattr(tool_use, "name", "") or ""
        cls = _classify_tool(name)
        if cls == CLERK_DENY:
            logger.warning("Clerk: tool '%s' denied by capability policy", name)
            return {
                "status": "blocked",
                "reason": f"tool '{name}' is denied by Clerk capability policy",
                "denied_tool": name,
                "tool_calls": tool_log,
                "usage": self._usage_payload(usage_totals),
                "saved_paths": saved_paths,
            }
        if cls == CLERK_APPROVAL:
            args = getattr(tool_use, "input", {})
            args = args if isinstance(args, dict) else {}
            if _clerk_action_key(name, args) not in self._approved_actions:
                logger.info("Clerk: tool '%s' requires approval (pending)", name)
                return {
                    "status": "pending_approval",
                    "reason": f"tool '{name}' requires Director approval before it can run",
                    "pending_tool": name,
                    "tool_calls": tool_log,
                    "usage": self._usage_payload(usage_totals),
                    "saved_paths": saved_paths,
                }
        return None

    def _validate_tool_use(self, tool_use: Any) -> tuple[bool, str]:
        if not getattr(tool_use, "name", ""):
            return False, "tool call missing function name"
        # Capability denylist is enforced by _policy_gate (DENY class), not here.
        if tool_use.name not in {t["name"] for t in self.registry.tools}:
            return False, f"unknown tool: {tool_use.name}"
        if not isinstance(getattr(tool_use, "input", None), dict):
            return False, "tool input must be a JSON object"
        if "__malformed_json" in tool_use.input:
            return False, "tool arguments were malformed JSON"
        for key in ("action", "operation", "mode", "intent"):
            val = tool_use.input.get(key)
            if isinstance(val, str) and _FORBIDDEN_TOOL_ARG_VALUES.search(val):
                return False, f"forbidden tool operation: {val}"
        return True, ""

    @staticmethod
    def _usage(response: Any) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        return int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)

    def _new_usage_totals(self) -> dict[str, Any]:
        context_max = int(getattr(self.cfg, "context_window_max", 0) or 0) or None
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "context_window_used": None,
            "context_window_max": context_max,
            "session_cost_usd": None,
            "has_token_data": False,
        }

    def _record_usage(self, totals: dict[str, Any], response: Any) -> None:
        usage = getattr(response, "usage", None)
        prompt_tokens = _int_or_none(getattr(usage, "prompt_tokens", None))
        completion_tokens = _int_or_none(getattr(usage, "completion_tokens", None))
        total_tokens = _int_or_none(getattr(usage, "total_tokens", None))
        cost = _float_or_none(getattr(usage, "cost", None))

        if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens

        if prompt_tokens is not None:
            totals["prompt_tokens"] += prompt_tokens
            totals["context_window_used"] = max(totals["context_window_used"] or 0, prompt_tokens)
            totals["has_token_data"] = True
        if completion_tokens is not None:
            totals["completion_tokens"] += completion_tokens
            totals["has_token_data"] = True
        if total_tokens is not None:
            totals["total_tokens"] += total_tokens
            totals["has_token_data"] = True
        elif prompt_tokens is not None or completion_tokens is not None:
            totals["total_tokens"] += (prompt_tokens or 0) + (completion_tokens or 0)

        if cost is None:
            cost = self._configured_usage_cost(prompt_tokens, completion_tokens)
        if cost is not None:
            totals["session_cost_usd"] = float(totals["session_cost_usd"] or 0.0) + cost

    def _configured_usage_cost(self, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
        prompt_price = float(getattr(self.cfg, "prompt_price_per_m", 0.0) or 0.0)
        completion_price = float(getattr(self.cfg, "completion_price_per_m", 0.0) or 0.0)
        if prompt_price <= 0 or completion_price <= 0:
            return None
        if prompt_tokens is None or completion_tokens is None:
            return None
        return (prompt_tokens / 1_000_000.0) * prompt_price + (completion_tokens / 1_000_000.0) * completion_price

    @staticmethod
    def _usage_payload(totals: dict[str, Any]) -> dict[str, Any]:
        if totals.get("has_token_data"):
            input_tokens = int(totals["prompt_tokens"])
            output_tokens = int(totals["completion_tokens"])
            total_tokens = int(totals["total_tokens"])
            prompt_tokens: int | None = input_tokens
            completion_tokens: int | None = output_tokens
        else:
            input_tokens = 0
            output_tokens = 0
            total_tokens = None
            prompt_tokens = None
            completion_tokens = None
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "context_window_used": totals.get("context_window_used"),
            "context_window_max": totals.get("context_window_max"),
            "session_cost_usd": totals.get("session_cost_usd"),
        }

    @staticmethod
    def _log_cost(model: str, input_tokens: int, output_tokens: int) -> None:
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(model, input_tokens, output_tokens, source="clerk_runtime")
        except Exception:
            pass

    @staticmethod
    def _guardrail_result(
        decision: GuardrailDecision,
        tool_log: list[dict[str, Any]] | None = None,
        usage_totals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = {
            "status": decision.status,
            "reason": decision.reason,
            "denylist_item": decision.item,
            "tool_calls": tool_log or [],
        }
        if usage_totals is not None:
            result["usage"] = ClerkAgent._usage_payload(usage_totals)
        return result


def run_clerk_task(task: str) -> dict[str, Any]:
    """Convenience entry point for headless Clerk invocations."""
    return ClerkAgent().run(task)
