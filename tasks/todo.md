# DROPBOX-1 — Dropbox Sentinel Implementation

## Plan (order matches brief)

1. [x] Read brief + reference implementations
2. [x] `config/settings.py` — Add DropboxConfig, wire into SentinelConfig + TriggerConfig, add baker-documents to default collections
3. [x] `triggers/state.py` — ALTER TABLE add cursor_data TEXT, add get_cursor/set_cursor methods
4. [x] `triggers/dropbox_client.py` — CREATE: OAuth2 refresh, list_folder (delta + pagination), download_file, rate limiting
5. [x] `triggers/dropbox_trigger.py` — CREATE: run_dropbox_poll() — download, ingest_file, pipeline feed, temp cleanup
6. [x] `triggers/scheduler.py` — Register dropbox_poll job, add "dropbox" to --run-once choices
7. [x] Verify: `python -m triggers.scheduler --run-once dropbox`
8. [ ] Commit + push to main
