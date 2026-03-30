# BRIEF: Dropbox Watch Path Expansion — Baker-Project

**Priority:** Medium — documents filed in Baker-Project are invisible to Baker unless manually copied to Baker-Feed
**Ticket:** DROPBOX-EXPANSION-5
**Depends on:** BRIEF_DOCUMENT_DEDUP_1 (content-hash dedup MUST be deployed first)

## Problem

Baker only watches `/Baker-Feed/` in Dropbox. Documents filed properly in `Baker-Project/01_Projects/Hagenauer/` are invisible unless the Director manually copies them to Baker-Feed. This leads to:
1. Missed documents (Director forgets to copy)
2. Duplicates (Director copies same file twice weeks apart)
3. Extra manual work that shouldn't exist

## Solution

Expand the Dropbox watch path to include `Baker-Project`. Auto-detect the matter/project from the folder path. Content-hash dedup (from BRIEF_DOCUMENT_DEDUP_1) prevents duplicates.

## CRITICAL PRE-REQUISITE

**BRIEF_DOCUMENT_DEDUP_1 must be deployed and verified before this brief.** Without content-hash dedup, expanding the watch path WILL create duplicates from files that exist in both Baker-Feed and Baker-Project.

Check:
```sql
SELECT column_name FROM information_schema.columns WHERE table_name = 'documents' AND column_name = 'content_hash';
```
If `content_hash` column doesn't exist, STOP — deploy the dedup brief first.

## Implementation

### Change 1: Update Dropbox trigger for multiple paths

**File:** `triggers/dropbox_trigger.py`

Find where `config.dropbox.watch_path` is used. It's currently a single path string. Change to support comma-separated paths:

```python
# Before:
watch_path = config.dropbox.watch_path
# ... poll single path ...

# After:
watch_paths = [p.strip() for p in config.dropbox.watch_path.split(",") if p.strip()]
for watch_path in watch_paths:
    _poll_single_path(watch_path)
```

**IMPORTANT:** Read the full `run_dropbox_poll()` function first. Understand the watermark system — each path needs its own watermark. The watermark key should include the path:
```python
watermark_key = f"dropbox:{watch_path}"
```

Check if the existing code already handles this or needs modification.

### Change 2: Auto-detect matter from folder path

**File:** `triggers/dropbox_trigger.py`

When ingesting files from `Baker-Project`, extract the matter/project from the folder structure:

```python
def _detect_matter_from_path(file_path: str) -> str:
    """Extract matter slug from Baker-Project folder structure.
    /Baker-Project/01_Projects/Hagenauer-RG7/... → 'hagenauer'
    /Baker-Project/01_Projects/Kempinski/... → 'kempinski'
    """
    path_lower = file_path.lower()

    # Known project folders → matter slugs
    _PROJECT_MATTER_MAP = {
        'hagenauer': 'hagenauer',
        'kempinski': 'kempinski',
        'morv': 'mandarin-oriental',
        'mandarin': 'mandarin-oriental',
        'baden': 'baden-baden',
        'cap ferrat': 'cap-ferrat',
        'cap-ferrat': 'cap-ferrat',
        'alpengo': 'alpengo-davos',
        'davos': 'alpengo-davos',
        'lilienmatt': 'lilienmatt',
    }

    for keyword, slug in _PROJECT_MATTER_MAP.items():
        if keyword in path_lower:
            return slug
    return None
```

Then when storing the document, include the detected matter:

```python
matter = _detect_matter_from_path(file_path)
# Pass matter to the document storage/pipeline call
```

**IMPORTANT:** Check how the existing Dropbox trigger calls the document pipeline. The matter may be passed as metadata. Adapt accordingly.

### Change 3: Update Render environment variable

After code is deployed, update the env var on Render:

```
DROPBOX_WATCH_PATH=/Baker-Feed,/Baker-Project
```

Use the Render MCP tool or dashboard to update. Do NOT use raw PUT — use merge mode.

**NOTE:** This env var change should be done AFTER the code is deployed, not before. Otherwise the old code will try to poll Baker-Project without the multi-path support.

### Change 4: Per-path watermarks

Each watch path needs its own watermark to track what's been ingested:

```python
# When polling /Baker-Feed:
watermark_key = "dropbox:/Baker-Feed"

# When polling /Baker-Project:
watermark_key = "dropbox:/Baker-Project"
```

This prevents re-processing all of Baker-Feed when Baker-Project is added, and vice versa.

**IMPORTANT:** The existing watermark may be stored as just `"dropbox"`. Check:
```sql
SELECT source FROM trigger_watermarks WHERE source LIKE 'dropbox%';
```
If it's just `"dropbox"`, migrate it to `"dropbox:/Baker-Feed"` so the existing watermark isn't lost when switching to per-path keys.

## Files to Modify

| File | Change |
|------|--------|
| `triggers/dropbox_trigger.py` | Multi-path polling, matter detection, per-path watermarks |
| Render env vars | `DROPBOX_WATCH_PATH=/Baker-Feed,/Baker-Project` (after code deploy) |

## Verification

1. Confirm `content_hash` column exists in documents table (dedup pre-req)
2. Deploy code
3. Update `DROPBOX_WATCH_PATH` env var on Render
4. Drop a test PDF into `Baker-Project/01_Projects/Hagenauer/`
5. Wait 30 min (Dropbox poll interval) or check logs
6. Document appears in Documents section with matter=hagenauer, source=dropbox
7. Same file in Baker-Feed → dedup skips it (check logs for "skipping duplicate")

## Rules

- MUST verify dedup is deployed before activating this
- Check Dropbox trigger watermark system before changing it
- `conn.rollback()` in all except blocks
- Per-path watermarks — don't lose the existing Baker-Feed watermark
- Syntax check all modified files before commit
- Never force push
- git pull before starting
