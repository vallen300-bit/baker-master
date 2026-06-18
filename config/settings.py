"""
Baker AI — Configuration
All secrets loaded from environment variables.
Copy .env.example → .env and fill in your credentials.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

# Detect Render environment (Render sets IS_RENDER=true or RENDER=true)
_ON_RENDER = os.path.exists("/etc/secrets")
from typing import List, Optional

from dotenv import load_dotenv

# Load .env before any os.getenv() calls in dataclass defaults
_ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(_ENV_PATH, override=True)


def _env_int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _env_choice(name: str, default: str, allowed: set[str]) -> str:
    value = (os.getenv(name, default) or default).strip().lower()
    return value if value in allowed else default


@dataclass
class QdrantConfig:
    url: str = os.getenv("QDRANT_URL", "")
    api_key: str = os.getenv("QDRANT_API_KEY", "")
    collections: List[str] = field(default_factory=lambda: [
        c.strip() for c in os.getenv(
            "BAKER_COLLECTIONS",
            "baker-people,baker-deals,baker-projects,baker-conversations,baker-whatsapp,baker-clickup,baker-todoist,baker-documents,baker-health,sentinel-interactions,baker-slack"
        ).split(",")
    ])
    collection_whatsapp: str = "baker-whatsapp"
    collection_email: str = "baker-conversations"
    collection_meetings: str = "sentinel-meetings"
    collection_documents: str = "sentinel-documents"


@dataclass
class VoyageConfig:
    api_key: str = os.getenv("VOYAGE_API_KEY", "")
    model: str = "voyage-3"
    dimensions: int = 1024


@dataclass
class ClaudeConfig:
    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    # OPUS_4_8_UPGRADE_1 (2026-05-31): env-overridable via KBL_ANTHROPIC_MODEL.
    model: str = os.getenv("KBL_ANTHROPIC_MODEL", "claude-opus-4-8")
    beta_header: str = "context-1m-2025-08-07"
    max_context_tokens: int = 1_000_000
    max_output_tokens: int = 128_000
    # Cost per million tokens
    cost_per_m_input_standard: float = 5.00
    cost_per_m_input_premium: float = 10.00
    cost_per_m_output_standard: float = 25.00
    cost_per_m_output_premium: float = 37.50
    # Token budget allocation (from Sentinel architecture)
    budget_system_prompt: int = 50_000
    budget_retrieved_context: int = 800_000
    budget_output: int = 128_000
    budget_buffer: int = 22_000  # safety margin


@dataclass
class GeminiConfig:
    """GEMINI-MIGRATION-1: Gemini API configuration."""
    api_key: str = os.getenv("GEMINI_API_KEY", "")
    flash_model: str = "gemini-2.5-flash"
    pro_model: str = "gemini-2.5-pro"
    enabled: bool = os.getenv("BAKER_USE_GEMINI", "true").lower() == "true"


@dataclass
class Qwen3Config:
    """CLERK_WORKBENCH_1: Qwen3-Coder runtime configuration for Clerk."""
    base_url: str = os.getenv("CLERK_QWEN_BASE_URL", "")
    api_key: str = os.getenv("CLERK_QWEN_API_KEY", "")
    model: str = os.getenv("CLERK_QWEN_MODEL", "qwen3-coder")
    backend: str = os.getenv("CLERK_MODEL_BACKEND", "qwen3_hosted")
    max_steps: int = int(os.getenv("CLERK_MAX_STEPS", "12"))
    task_timeout_s: int = int(os.getenv("CLERK_TASK_TIMEOUT_S", "180"))
    context_window_max: int = _env_int("CLERK_QWEN_CONTEXT_WINDOW_MAX", 0)
    prompt_price_per_m: float = _env_float("CLERK_QWEN_PROMPT_PRICE_PER_M", 0.0)
    completion_price_per_m: float = _env_float("CLERK_QWEN_COMPLETION_PRICE_PER_M", 0.0)
    default_mail_provider: str = field(
        default_factory=lambda: _env_choice("CLERK_DEFAULT_MAIL_PROVIDER", "all", {"all", "gmail", "graph"})
    )

    @property
    def enabled(self) -> bool:
        if self.backend == "qwen3_ollama_local":
            return bool(self.base_url and self.model)
        return bool(self.base_url and self.api_key and self.model)


@dataclass(init=False)
class GraphConfig:
    """M365_GRAPH_CLIENT_FOUNDATION_1: Microsoft Graph (M365) configuration.
    Dormant until Phase 0 creds + BAKER_USE_GRAPH=true.

    Env-derived values are properties so long-lived imports do not freeze Graph
    toggles or credentials. Explicit constructor values still override env for
    tests and callers that need a stable config snapshot.
    """
    base_url: str = "https://graph.microsoft.com/v1.0"
    authority_tmpl: str = "https://login.microsoftonline.com/{tenant}"
    scope: List[str] = field(default_factory=lambda: ["https://graph.microsoft.com/.default"])

    def __init__(
        self,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        cert_private_key: Optional[str] = None,
        cert_path: Optional[str] = None,
        cert_thumbprint: Optional[str] = None,
        base_url: str = "https://graph.microsoft.com/v1.0",
        authority_tmpl: str = "https://login.microsoftonline.com/{tenant}",
        scope: Optional[List[str]] = None,
        enabled: Optional[bool] = None,
        mail_user: Optional[str] = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._cert_private_key = cert_private_key
        self._cert_path = cert_path
        self._cert_thumbprint = cert_thumbprint
        self.base_url = base_url
        self.authority_tmpl = authority_tmpl
        self.scope = scope if scope is not None else ["https://graph.microsoft.com/.default"]
        self._enabled = enabled
        self._mail_user = mail_user

    @staticmethod
    def _env_flag(name: str, default: bool = False) -> bool:
        fallback = "true" if default else "false"
        return os.getenv(name, fallback).lower() == "true"

    @property
    def tenant_id(self) -> str:
        return self._tenant_id if self._tenant_id is not None else os.getenv("M365_TENANT_ID", "")

    @tenant_id.setter
    def tenant_id(self, value: str) -> None:
        self._tenant_id = value

    @property
    def client_id(self) -> str:
        return self._client_id if self._client_id is not None else os.getenv("M365_CLIENT_ID", "")

    @client_id.setter
    def client_id(self, value: str) -> None:
        self._client_id = value

    @property
    def client_secret(self) -> str:
        return self._client_secret if self._client_secret is not None else os.getenv("M365_CLIENT_SECRET", "")

    @client_secret.setter
    def client_secret(self, value: str) -> None:
        self._client_secret = value

    @property
    def cert_private_key(self) -> str:
        return (
            self._cert_private_key
            if self._cert_private_key is not None
            else os.getenv("M365_CERT_PRIVATE_KEY", "")
        )

    @cert_private_key.setter
    def cert_private_key(self, value: str) -> None:
        self._cert_private_key = value

    @property
    def cert_path(self) -> str:
        return self._cert_path if self._cert_path is not None else os.getenv("M365_CERT_PATH", "")

    @cert_path.setter
    def cert_path(self, value: str) -> None:
        self._cert_path = value

    @property
    def cert_thumbprint(self) -> str:
        return (
            self._cert_thumbprint
            if self._cert_thumbprint is not None
            else os.getenv("M365_CERT_THUMBPRINT", "")
        )

    @cert_thumbprint.setter
    def cert_thumbprint(self, value: str) -> None:
        self._cert_thumbprint = value

    @property
    def enabled(self) -> bool:
        return self._enabled if self._enabled is not None else self._env_flag("BAKER_USE_GRAPH")

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def mail_user(self) -> str:
        return (
            self._mail_user
            if self._mail_user is not None
            else os.getenv("M365_MAIL_USER", "dvallen@brisengroup.com")
        )

    @mail_user.setter
    def mail_user(self, value: str) -> None:
        self._mail_user = value


@dataclass
class GmailConfig:
    # OAuth2 credentials file (downloaded from Google Cloud Console)
    # Render Secret Files live at /etc/secrets/; fall back to config/ for local dev
    credentials_path: str = (
        "/etc/secrets/gmail_credentials.json"
        if os.path.exists("/etc/secrets/gmail_credentials.json")
        else str(Path(__file__).parent / "gmail_credentials.json")
    )
    # Token file (auto-generated after first OAuth2 flow)
    token_path: str = (
        "/etc/secrets/gmail_token.json"
        if os.path.exists("/etc/secrets/gmail_token.json")
        else str(Path(__file__).parent / "gmail_token.json")
    )
    # Writable dir for refreshed tokens & poll state (Render /etc/secrets is read-only)
    writable_state_dir: str = "/tmp" if _ON_RENDER else str(Path(__file__).parent)
    # Scopes needed for Gmail read + Calendar access
    scopes: List[str] = field(default_factory=lambda: [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar",
    ])
    # Default query to exclude noise categories
    # NOTE: -category:updates REMOVED — it was filtering travel bookings,
    # receipts, and other operational emails. Noise senders list handles junk.
    default_query: str = (
        "-category:promotions -category:social "
        "-category:forums"
    )
    # Newsletter / noise sender patterns (regex-matched against From header)
    noise_senders: List[str] = field(default_factory=lambda: [
        # Generic no-reply / automated
        r"noreply@", r"no-reply@", r"no\.reply@",
        r"mailer-daemon@", r"postmaster@",
        r"do-not-reply@", r"donotreply@",
        r"notifications@", r"notification@",
        r"notify@", r"alert@", r"alerts@",
        r"newsletter@", r"news@",
        r"marketing@", r"promo@",
        # Productivity / SaaS platforms
        r"@clickup\.com$", r"@slack\.com$", r"@asana\.com$",
        r"@trello\.com$", r"@notion\.so$", r"@monday\.com$",
        r"@linear\.app$", r"@jira", r"@atlassian",
        r"@github\.com$", r"@gitlab\.com$",
        # Cloud / infrastructure
        r"@google\.com$", r"@accounts\.google\.com$",
        r"@apple\.com$", r"@microsoft\.com$", r"@amazon\.com$",
        r"@zoom\.us$", r"@calendly\.com$", r"@fireflies\.ai$",
        # Financial / transactional
        r"@stripe\.com$", r"@paypal", r"@wise\.com$",
        r"@revolut\.com$",
        # Calendar invites pattern (accept/decline bots)
        r"calendar-notification@", r"calendar-server@",
    ])
    # Max messages per thread to prevent runaway threads
    max_messages_per_thread: int = 50
    # Qdrant collection for email
    collection: str = "baker-conversations"


@dataclass
class FirefliesConfig:
    api_key: str = os.getenv("FIREFLIES_API_KEY", "")
    endpoint: str = "https://api.fireflies.ai/graphql"


@dataclass
class PlaudConfig:
    api_token: str = os.getenv("PLAUD_TOKEN", "")
    api_domain: str = os.getenv("PLAUD_API_DOMAIN", "https://api-euc1.plaud.ai")


@dataclass
class PostgresConfig:
    host: str = os.getenv("POSTGRES_HOST", "localhost")
    host_direct: str = os.getenv("POSTGRES_HOST_DIRECT", "")
    port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    database: str = os.getenv("POSTGRES_DB", "sentinel")
    user: str = os.getenv("POSTGRES_USER", "sentinel")
    password: str = os.getenv("POSTGRES_PASSWORD", "")
    sslmode: str = os.getenv("POSTGRES_SSLMODE", "prefer")

    @property
    def connection_string(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}?sslmode={self.sslmode}"

    @property
    def dsn_params(self) -> dict:
        """Return connection params dict for psycopg2."""
        params = {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
            # EMAIL_STORE_CONN_HARDEN_1: mirror the SCHEDULER_NEON_IDLE_HARDEN_1
            # keepalives (below, direct_dsn_params) onto the pooled path. The
            # pooled path had none, so Neon idle-killed cached connections
            # (retriever shared conn + store_back pool) and the first caller
            # after an idle gap ate "SSL connection has been closed
            # unexpectedly" — ~2/hr, Director-visible (RCA bus #2813).
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        }
        if self.sslmode and self.sslmode != "disable":
            params["sslmode"] = self.sslmode
        return params

    @property
    def direct_dsn_params(self) -> dict:
        """Return connection params for the NON-POOLED Neon endpoint.

        Required for session-level advisory locks: pgbouncer transaction-mode
        resets session state on every commit, releasing the lock. Direct
        compute keeps the connection 1:1 with a backend for the process
        lifetime. Falls back to ``host`` if ``host_direct`` is unset; callers
        MUST handle the case where the lock cannot be held under the pooler.
        """
        host = self.host_direct or self.host
        params = {
            "host": host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
            # SCHEDULER_NEON_IDLE_HARDEN_1: keep the long-lived non-pooled lock
            # connection alive so Neon does not idle-disconnect it between the
            # 5-min heartbeat probes (root of the ~18-min scheduler restart loop).
            # Shared across every direct-conn consumer (reingest/OCR locks benefit too).
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        }
        if self.sslmode and self.sslmode != "disable":
            params["sslmode"] = self.sslmode
        return params


@dataclass
class TodoistConfig:
    api_token: str = os.getenv("TODOIST_API_TOKEN", "")
    base_url: str = "https://api.todoist.com/api/v1"
    # Rate limit: 450 requests/15 min = 30/min (conservative)
    rate_limit_per_min: int = 30


@dataclass
class DropboxConfig:
    app_key: str = os.getenv("DROPBOX_APP_KEY", "")
    app_secret: str = os.getenv("DROPBOX_APP_SECRET", "")
    refresh_token: str = os.getenv("DROPBOX_REFRESH_TOKEN", "")
    watch_path: str = os.getenv("DROPBOX_WATCH_PATH", "/Baker-Feed")
    max_file_size: int = 104_857_600  # 100 MB


@dataclass
class SlackConfig:
    bot_token: str = os.getenv("SLACK_BOT_TOKEN", "")
    # Signing secret for Events API request verification
    signing_secret: str = os.getenv("SLACK_SIGNING_SECRET", "")
    # events | polling (default: polling — Events API is additive, polling stays as fallback)
    mode: str = os.getenv("SLACK_MODE", "polling")
    # Comma-separated channel IDs to poll for ingest (default: #cockpit)
    channel_ids: List[str] = field(default_factory=lambda: [
        c.strip() for c in os.getenv("SLACK_CHANNEL_IDS", "C0AF4FVN3FB").split(",") if c.strip()
    ])
    # Channel where Baker posts alerts/briefings (CEO Cockpit = #cockpit)
    cockpit_channel_id: str = os.getenv("SLACK_COCKPIT_CHANNEL", "C0AF4FVN3FB")
    # Baker's Slack bot user ID — used to detect @Baker mentions (e.g. U01ABCDEF)
    baker_bot_user_id: str = os.getenv("SLACK_BAKER_USER_ID", "")
    # Qdrant collection for Slack messages
    collection: str = "baker-slack"


@dataclass
class WahaConfig:
    base_url: str = os.getenv("WAHA_BASE_URL", "https://baker-waha.onrender.com")
    session: str = os.getenv("WAHA_SESSION", "default")
    # Scoped keys (WAHA 2026.4+). Each consumer reads its scope-matched key.
    api_key_read: str = os.getenv("WAHA_API_KEY_READ", "")
    api_key_send: str = os.getenv("WAHA_API_KEY_SEND", "")
    api_key_monitor: str = os.getenv("WAHA_API_KEY_MONITOR", "")
    webhook_secret: str = os.getenv("WAHA_WEBHOOK_SECRET", "")
    # Legacy admin key — kept ONLY for fallback chain in code paths +
    # ad-hoc ops/CLI scripts. Will be removed in fold-back PR after 7 days
    # of stable scoped-key operation.
    api_key: str = os.getenv("WHATSAPP_API_KEY", "")


@dataclass
class RssConfig:
    check_interval: int = int(os.getenv("RSS_CHECK_INTERVAL", "3600"))  # 60 min default
    max_article_age_days: int = 7  # skip articles older than 7 days on first poll
    max_articles_per_feed: int = 50  # safety cap per feed per poll
    request_timeout: int = 30  # seconds per feed fetch
    collection: str = "baker-documents"  # reuse existing collection


@dataclass
class BrowserConfig:
    cloud_api_key: str = os.getenv("BROWSER_USE_API_KEY", "")
    cloud_base_url: str = "https://api.browser-use.com/api/v1"
    chrome_cdp_url: str = os.getenv("CHROME_BROWSER_URL", "")  # Tailscale Funnel URL to Chrome DevTools
    simple_timeout: int = 30  # seconds for httpx fetch
    browser_timeout: int = 120  # seconds for browser-use cloud task
    max_retries: int = 2
    collection: str = "baker-browser"


@dataclass
class WebPushConfig:
    vapid_private_key: str = os.getenv("VAPID_PRIVATE_KEY", "")
    vapid_public_key: str = os.getenv("VAPID_PUBLIC_KEY", "")
    vapid_contact_email: str = os.getenv("VAPID_CONTACT_EMAIL", "")
    # Notification throttling
    quiet_start_utc: int = int(os.getenv("PUSH_QUIET_START_UTC", "21"))   # 22:00 CET
    quiet_end_utc: int = int(os.getenv("PUSH_QUIET_END_UTC", "6"))       # 07:00 CET
    daily_cap: int = int(os.getenv("PUSH_DAILY_CAP", "8"))
    cooldown_minutes: int = int(os.getenv("PUSH_COOLDOWN_MINUTES", "15"))


@dataclass
class TriggerConfig:
    # Fireflies scanning interval (seconds)
    fireflies_scan_interval: int = 900  # 15 minutes (was 7200; FIREFLIES-FIX-1)
    # Fireflies auto-ingest scan toggle (FIREFLIES_SCAN_GATE_1). Default TRUE in
    # code to preserve behavior + tests; prod disable is via env
    # FIREFLIES_SCAN_ENABLED=false (Director switched to Plaud-only 2026-06-09).
    fireflies_scan_enabled: bool = os.getenv("FIREFLIES_SCAN_ENABLED", "true").lower() == "true"
    # Email check interval
    email_check_interval: int = 300  # 5 minutes
    # M365_GRAPH_MAIL_POLL_2: Microsoft Graph inbound mail poll interval
    graph_mail_check_interval: int = int(os.getenv("GRAPH_MAIL_CHECK_INTERVAL", "300"))  # 5 minutes
    # WhatsApp: migrated to WAHA webhook (Session 26) — polling removed
    # Todoist polling interval
    todoist_check_interval: int = 1800  # 30 minutes
    # Todoist poll toggle (TODOIST_RETIRE_1). Default TRUE in code to preserve
    # behavior + tests; prod disable is via env TODOIST_POLL_ENABLED=false
    # (Director retired Todoist 2026-06-18 — "I don't use it; keep on-demand
    # access"). Mirrors FIREFLIES_SCAN_ENABLED. The on-demand MCP path
    # (baker_todoist_tasks) and the valid env token are untouched.
    todoist_poll_enabled: bool = os.getenv("TODOIST_POLL_ENABLED", "true").lower() == "true"
    # Dropbox polling interval
    dropbox_check_interval: int = int(os.getenv("DROPBOX_CHECK_INTERVAL", "1800"))  # 30 minutes
    # RSS polling interval
    rss_check_interval: int = int(os.getenv("RSS_CHECK_INTERVAL", "3600"))  # 60 minutes
    # Slack polling interval
    slack_check_interval: int = int(os.getenv("SLACK_CHECK_INTERVAL", "300"))  # 5 minutes
    # Browser task polling interval (BROWSER-1)
    browser_check_interval: int = int(os.getenv("BROWSER_CHECK_INTERVAL", "1800"))  # 30 minutes
    # Plaud Note Pro scanning interval
    plaud_scan_interval: int = int(os.getenv("PLAUD_SCAN_INTERVAL", "900"))  # 15 minutes
    # Daily briefing time (UTC)
    daily_briefing_hour: int = 6  # 06:00 UTC = 08:00 CET
    # Pending approval reminder interval
    approval_reminder_interval: int = 10800  # 3 hours


@dataclass
class OutputConfig:
    # Slack webhook for coworker chat
    slack_webhook_url: str = os.getenv("SLACK_WEBHOOK_URL", "")
    slack_bot_token: str = os.getenv("SLACK_BOT_TOKEN", "")
    # Push notification service
    push_service_url: str = os.getenv("PUSH_SERVICE_URL", "")
    # Dashboard
    dashboard_url: str = os.getenv("DASHBOARD_URL", "http://localhost:8080")


@dataclass
class DecisionEngineConfig:
    """DECISION-ENGINE-1A: Scoring and routing configuration."""
    family_contacts: List[str] = field(default_factory=lambda: ["edita", "kira", "nona", "philip"])
    vip_sla_tier1_minutes: int = 15
    vip_sla_tier2_minutes: int = 240  # 4 hours
    financial_threshold_high: int = 100_000
    financial_threshold_medium: int = 10_000
    haiku_model: str = "claude-haiku-4-5-20251001"


@dataclass
class ChainConfig:
    """AUTONOMOUS-CHAINS-1: Plan-execute-verify configuration."""
    enabled: bool = os.getenv("BAKER_CHAINS_ENABLED", "false").lower() == "true"
    max_steps: int = 5
    timeout_seconds: float = float(os.getenv("BAKER_CHAIN_TIMEOUT", "120"))
    notify_mode: str = "write_actions_only"  # "always" | "write_actions_only" | "t1_only"
    max_chains_per_hour: int = 10  # prevent runaway loops


@dataclass
class ComplexityConfig:
    """COMPLEXITY-ROUTER-1: Fast/deep routing configuration."""
    shadow_mode: bool = os.getenv("COMPLEXITY_SHADOW_MODE", "false").lower() == "true"
    fast_model: str = "gemini-2.5-flash"
    # OPUS_4_8_UPGRADE_1 (2026-05-31): env-overridable via KBL_ANTHROPIC_MODEL.
    deep_model: str = os.getenv("KBL_ANTHROPIC_MODEL", "claude-opus-4-8")
    fast_max_tokens: int = 1024
    deep_max_tokens: int = 4096
    fast_tool_limit: int = 3
    fast_timeout: int = 10
    deep_timeout: int = 120


@dataclass
class SentinelConfig:
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    voyage: VoyageConfig = field(default_factory=VoyageConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    qwen3: Qwen3Config = field(default_factory=Qwen3Config)
    gmail: GmailConfig = field(default_factory=GmailConfig)
    fireflies: FirefliesConfig = field(default_factory=FirefliesConfig)
    plaud: PlaudConfig = field(default_factory=PlaudConfig)
    todoist: TodoistConfig = field(default_factory=TodoistConfig)
    dropbox: DropboxConfig = field(default_factory=DropboxConfig)
    rss: RssConfig = field(default_factory=RssConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    waha: WahaConfig = field(default_factory=WahaConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    web_push: WebPushConfig = field(default_factory=WebPushConfig)
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    triggers: TriggerConfig = field(default_factory=TriggerConfig)
    outputs: OutputConfig = field(default_factory=OutputConfig)
    decision_engine: DecisionEngineConfig = field(default_factory=DecisionEngineConfig)
    chains: ChainConfig = field(default_factory=ChainConfig)
    complexity: ComplexityConfig = field(default_factory=ComplexityConfig)
    # Baker personality
    baker_persona: str = "chief_of_staff"
    debug: bool = os.getenv("SENTINEL_DEBUG", "false").lower() == "true"


# Global config instance
config = SentinelConfig()


def _assert_waha_scoped_keys() -> None:
    """WAHA-KEY-SPLIT-1: surface missing scoped keys as a soft warning.

    Production code paths fall back to the legacy WHATSAPP_API_KEY admin key
    when scoped keys are absent (see triggers/waha_client.py and
    outputs/whatsapp_sender.py). The fallback is load-bearing for fast rollback
    via Render env-var flip — so a missing scoped key is a warning, not a hard
    fail. Hard fail would brick Baker during the rollout window before Step 2.4
    env-var rotation lands.
    """
    try:
        if os.getenv("WAHA_REQUIRE_SCOPED_KEYS", "true").lower() != "true":
            return
        missing = [
            n for n, v in [
                ("WAHA_API_KEY_READ", config.waha.api_key_read),
                ("WAHA_API_KEY_SEND", config.waha.api_key_send),
                ("WAHA_API_KEY_MONITOR", config.waha.api_key_monitor),
            ] if not v
        ]
        if missing:
            import logging
            logging.getLogger("baker.config").warning(
                f"WAHA scoped keys missing: {missing}. "
                f"Code paths fall back to legacy WHATSAPP_API_KEY when scoped keys absent."
            )
    except Exception:
        # Never raise from a soft warning. Brick-safety > observability here.
        pass


_assert_waha_scoped_keys()
