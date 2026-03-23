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
    model: str = "claude-opus-4-6"
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
        "https://www.googleapis.com/auth/gmail.readonly",
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
class PostgresConfig:
    host: str = os.getenv("POSTGRES_HOST", "localhost")
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
class WhoopConfig:
    client_id: str = os.getenv("WHOOP_CLIENT_ID", "")
    client_secret: str = os.getenv("WHOOP_CLIENT_SECRET", "")
    refresh_token: str = os.getenv("WHOOP_REFRESH_TOKEN", "")
    base_url: str = "https://api.prod.whoop.com/developer/v2"
    token_url: str = "https://api.prod.whoop.com/oauth/oauth2/token"
    rate_limit_per_min: int = 100
    rate_limit_per_day: int = 10000


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
    api_key: str = os.getenv("WHATSAPP_API_KEY", "")
    webhook_secret: str = os.getenv("WAHA_WEBHOOK_SECRET", "")


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
    # Email check interval
    email_check_interval: int = 300  # 5 minutes
    # WhatsApp: migrated to WAHA webhook (Session 26) — polling removed
    # Todoist polling interval
    todoist_check_interval: int = 1800  # 30 minutes
    # Dropbox polling interval
    dropbox_check_interval: int = int(os.getenv("DROPBOX_CHECK_INTERVAL", "1800"))  # 30 minutes
    # Whoop polling interval
    whoop_check_interval: int = int(os.getenv("WHOOP_CHECK_INTERVAL", "86400"))  # 24 hours
    # RSS polling interval
    rss_check_interval: int = int(os.getenv("RSS_CHECK_INTERVAL", "3600"))  # 60 minutes
    # Slack polling interval
    slack_check_interval: int = int(os.getenv("SLACK_CHECK_INTERVAL", "300"))  # 5 minutes
    # Browser task polling interval (BROWSER-1)
    browser_check_interval: int = int(os.getenv("BROWSER_CHECK_INTERVAL", "1800"))  # 30 minutes
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
    fast_model: str = "claude-haiku-4-5-20251001"
    deep_model: str = "claude-opus-4-6"
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
    gmail: GmailConfig = field(default_factory=GmailConfig)
    fireflies: FirefliesConfig = field(default_factory=FirefliesConfig)
    todoist: TodoistConfig = field(default_factory=TodoistConfig)
    dropbox: DropboxConfig = field(default_factory=DropboxConfig)
    whoop: WhoopConfig = field(default_factory=WhoopConfig)
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
