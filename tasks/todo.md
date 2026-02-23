# RSS-1 — RSS Sentinel Implementation

## Plan (dependency order)

1. [ ] `requirements.txt` — Add `feedparser>=6.0.0`
2. [ ] `config/settings.py` — Add `RssConfig` dataclass + wire into `SentinelConfig` and `TriggerConfig`
3. [ ] `triggers/state.py` — Add `rss_feeds` and `rss_articles` CREATE TABLE to `_ensure_tables()`
4. [ ] `triggers/rss_client.py` — CREATE (~120 lines) — Singleton RSS client, OPML parser, feed fetcher
5. [ ] `triggers/rss_trigger.py` — CREATE (~180 lines) — Polling trigger, watermark-based, dedup, pipeline feed, OPML import
6. [ ] `outputs/dashboard.py` — Add `POST /api/rss/import-opml` endpoint
7. [ ] `triggers/embedded_scheduler.py` — Register `rss_poll` job
8. [ ] Commit + push to main
