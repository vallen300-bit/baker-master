---
paths:
  - "main.py"
  - "outputs/email_router.py"
  - "outputs/whatsapp_sender.py"
  - "outputs/slack_notifier.py"
  - "triggers/**/*.py"
---

# API & Output Safety Rules

- Auth: all API endpoints require `X-Baker-Key` header
- CORS: respect ALLOWED_ORIGINS env var
- Audit: all writes must log to `baker_actions` table
- ClickUp writes: BAKER space (901510186446) only. Max 10 writes/cycle
- Email: internal auto-sends OK. External always drafts first (Director approval required)
- Proactive emails DISABLED — all emails require Director approval (draft flow only)
