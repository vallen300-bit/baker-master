"""Headless Clerk runtime on Qwen3-Coder.

Phase 1 of CLERK_WORKBENCH_1: model client, bounded tool loop, tool registry,
and hard guardrails. Browser workbench surfaces are intentionally out of scope.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import logging
import posixpath
import re
import socket
import tempfile
import time
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
_FORBIDDEN_TOOL_NAME_FRAGMENTS = frozenset({
    "send",
    "delete",
    "remove",
    "move",
    "archive",
    "mark",
    "pay",
    "payment",
    "wire",
    "transfer",
})
_FORBIDDEN_TOOL_ARG_VALUES = re.compile(
    r"\b(send|delete|remove|move|archive|mark\s+read|mark\s+unread|pay|payment|wire|transfer)\b",
    re.I,
)


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
    def __init__(self, input_tokens: int = 0, output_tokens: int = 0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _ToolResponse:
    def __init__(
        self,
        content: list[Any],
        stop_reason: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Usage(input_tokens, output_tokens)


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
            payload["tool_choice"] = "auto"

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

        usage = data.get("usage") or {}
        stop_reason = "tool_use" if _tool_uses(content) else "end_turn"
        return _ToolResponse(
            content=content,
            stop_reason=stop_reason,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
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

    def __init__(self, dropbox_client: Any | None = None):
        self._dropbox_client = dropbox_client

    @property
    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "email_search",
                "description": "Search Gmail or the ready Graph mailbox by query/sender/subject/date/message id.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "provider": {"type": "string", "enum": ["gmail", "graph"], "default": "gmail"},
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
                        "provider": {"type": "string", "enum": ["gmail", "graph"], "default": "gmail"},
                        "include_attachments": {"type": "boolean", "default": False},
                    },
                    "required": ["message_id"],
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
        ]

    def execute(self, name: str, args: dict[str, Any]) -> str:
        try:
            if name == "email_search":
                return self._email_search(args)
            if name == "email_download":
                return self._email_download(args)
            if name == "document_fetch":
                return self._document_fetch(args)
            if name == "format_convert":
                return self._format_convert(args)
            if name == "file_save":
                return self._file_save(args)
            return _safe_json({"error": f"unknown tool: {name}"})
        except Exception as e:
            logger.warning("Clerk tool failed (%s): %s", name, type(e).__name__)
            return _safe_json({"error": f"{name} failed: {type(e).__name__}"})

    def _email_search(self, args: dict[str, Any]) -> str:
        provider = args.get("provider", "gmail")
        query = str(args.get("query", "")).strip()
        max_results = min(max(int(args.get("max_results", 10) or 10), 1), 50)
        if provider == "graph":
            return self._graph_email_search(query, max_results)

        from tools.gmail import dispatch_gmail

        return dispatch_gmail("baker_gmail_search", {"query": query, "max_results": max_results})

    def _email_download(self, args: dict[str, Any]) -> str:
        provider = args.get("provider", "gmail")
        message_id = str(args.get("message_id", "")).strip()
        if provider == "graph":
            return self._graph_email_download(message_id)

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
        if not _is_allowed_dropbox_path(dropbox_path, _ALLOWED_SAVE_PREFIXES):
            return _safe_json({
                "status": "blocked",
                "reason": "dropbox_path outside Clerk working folder",
                "dropbox_path": dropbox_path,
            })

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


_CLERK_SYSTEM_PROMPT = """You are Clerk, Brisen's document clerk.
Use tools to fetch email/documents, convert content, and save a Director-reviewable file.
Never execute money/payment actions, impersonate the Director, change code/production systems,
create matter slugs, or restructure vault/folders. Delete/move/archive/mark-email, external send,
and irreversible actions require explicit Director approval and otherwise become draft/pending outputs.
Return concise status with Ready: <path> / Source: <source> when complete."""


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
    ):
        self.cfg = cfg or config.qwen3
        self.model_client = model_client
        self.escalation_client = escalation_client
        self.registry = registry or ClerkToolRegistry()
        self.guardrails = guardrails or ClerkGuardrails()
        self.clock = clock or time.monotonic

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
        total_in = 0
        total_out = 0
        schema_failures = 0
        client = self._client()

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
                )
            except Exception as e:
                logger.warning("Clerk model call failed: %s", type(e).__name__)
                return {
                    "status": "blocked",
                    "reason": "model call failed",
                    "error_type": type(e).__name__,
                    "tool_calls": tool_log,
                }
            in_tok, out_tok = self._usage(response)
            total_in += in_tok
            total_out += out_tok
            self._log_cost(self.cfg.model, in_tok, out_tok)

            if response.stop_reason == "end_turn":
                return {
                    "status": "ready",
                    "answer": _text_from_blocks(response.content),
                    "iterations": step + 1,
                    "tool_calls": tool_log,
                    "usage": {"input_tokens": total_in, "output_tokens": total_out},
                }

            uses = _tool_uses(response.content)
            if not uses:
                return {"status": "blocked", "reason": f"unexpected stop_reason={response.stop_reason}"}

            assistant_content = self._assistant_content(response.content)
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results: list[dict[str, Any]] = []
            for tool_use in uses:
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
                    return self._guardrail_result(guard, tool_log=tool_log)

                t0 = self.clock()
                result = self.registry.execute(tool_use.name, tool_use.input)
                elapsed_ms = int((self.clock() - t0) * 1000)
                tool_log.append({"name": tool_use.name, "input": tool_use.input, "duration_ms": elapsed_ms})
                tool_results.append({"type": "tool_result", "tool_use_id": tool_use.id, "content": result})

            messages.append({"role": "user", "content": tool_results})

        return {"status": "blocked", "reason": "max_steps exceeded", "tool_calls": tool_log}

    def _escalate(
        self,
        messages: list[dict[str, Any]],
        tool_log: list[dict[str, Any]],
        reason: str,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
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
            }
        in_tok, out_tok = self._usage(response)
        self._log_cost(config.gemini.pro_model, in_tok, out_tok)
        if response.stop_reason == "tool_use":
            results = []
            for tool_use in _tool_uses(response.content):
                valid, validation_error = self._validate_tool_use(tool_use)
                if not valid:
                    results.append({"tool": getattr(tool_use, "name", ""), "error": validation_error})
                    continue
                guard = self.guardrails.check(_safe_json(tool_use.input))
                if not guard.allowed:
                    return self._guardrail_result(guard, tool_log=tool_log)
                result = self.registry.execute(tool_use.name, tool_use.input)
                tool_log.append({"name": tool_use.name, "input": tool_use.input, "duration_ms": 0, "escalated": True})
                results.append({"tool": tool_use.name, "result": result})
            return {"status": "ready", "answer": _safe_json(results), "escalated": True, "reason": reason, "tool_calls": tool_log}
        return {
            "status": "ready",
            "answer": _text_from_blocks(response.content),
            "escalated": True,
            "reason": reason,
            "tool_calls": tool_log,
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

    def _validate_tool_use(self, tool_use: Any) -> tuple[bool, str]:
        if not getattr(tool_use, "name", ""):
            return False, "tool call missing function name"
        lowered_name = tool_use.name.lower()
        if any(fragment in lowered_name for fragment in _FORBIDDEN_TOOL_NAME_FRAGMENTS):
            return False, f"forbidden tool capability: {tool_use.name}"
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

    @staticmethod
    def _log_cost(model: str, input_tokens: int, output_tokens: int) -> None:
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(model, input_tokens, output_tokens, source="clerk_runtime")
        except Exception:
            pass

    @staticmethod
    def _guardrail_result(decision: GuardrailDecision, tool_log: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "status": decision.status,
            "reason": decision.reason,
            "denylist_item": decision.item,
            "tool_calls": tool_log or [],
        }


def run_clerk_task(task: str) -> dict[str, Any]:
    """Convenience entry point for headless Clerk invocations."""
    return ClerkAgent().run(task)
