# BRIEF: People Section + Chat Issue Cards

**Priority:** High — Director needs person-centric view of open issues
**Ticket:** PEOPLE-SECTION-1

## Overview

Three connected features shipping together:

1. **PEOPLE section** in sidebar (new top-level nav, like Projects/Operations/Inbox)
2. **Chat issue cards** — when Baker produces person-centric analyses in Ask Baker, each issue renders as a separate triage-able card
3. **Chat triage bar** — all substantive Baker responses get a triage bar (Save to Dossiers, Save to People, dynamic suggestions, Dismiss)

## Part 1: People Section in Sidebar

### Sidebar Addition

Add `PEOPLE` as a 4th collapsible section in the sidebar, between INBOX and Ask Baker:

```
▾ PROJECTS        52
  Hagenauer        21
  Kempinski...     12
  ...
▸ OPERATIONS      28
▸ INBOX           40
▸ PEOPLE          15    ← NEW
─────────────────────
Ask Baker
Ask Specialist
Search
Documents
Dossiers
...
```

### People List View

When PEOPLE is expanded or clicked, show people with open-issue counts:

```
▾ PEOPLE              15
  Balazs Csepregi      8 ●
  Thomas Leitner       5
  Sandra Luger         2 ●
  Edita                3
  Andrey Oskolkov      2
```

Red dot = has overdue items (same pattern as Projects).

**Data source:** New table `people_issues` (see Part 4 below). Count = number of non-dismissed issues per person.

### Person Detail View

Click on a person → right panel shows their issues as cards with triage:

```
Balazs Csepregi
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌ OVERDUE · Mar 27
│ Brief Balazs on MO Kitzbühel approach
│ Committed during March 13 meeting to brief him on MO's
│ position shift re Kitzbühel.
│ [Ask Baker] [Flag Critical] [Mark Done] [Dismiss]
├─────────────────────────────────────
│ OVERDUE · Mar 24
│ Sound out MO on Davos
│ ClickUp task: Balazs to sound out Mandarin Oriental on
│ Davos branding opportunity. Blocked until Rolf confirms.
│ [Ask Baker] [Delegate] [Mark Done] [Dismiss]
├─────────────────────────────────────
│ DUE · Mar 31
│ Meet Yurkovich/UBM sellers on Kitzbühel
│ Seller meeting set by Andrey. Balazs is lead executor.
│ [Ask Baker] [Add Deadline] [Mark Done] [Dismiss]
└─────────────────────────────────────
```

**Triage actions (same pattern as landing cards):**
- **Ask Baker** — pre-fills Ask Baker input with "Tell me more about [issue title] for [person]"
- **Flag Critical** — calls existing `/api/set-critical` endpoint
- **Mark Done** — marks issue as completed in `people_issues`
- **Dismiss** — soft-delete (hidden from view, kept in DB)
- **Delegate** — pre-fills "Delegate [issue] to [person] via WhatsApp/email"
- **Add Deadline** — pre-fills "Add deadline for [issue]"

Dynamic triage buttons chosen per-card based on issue content (same keyword matching as CHAT-TRIAGE-1).

## Part 2: Chat Issue Cards in Ask Baker

### The Problem

When Baker produces a person-centric analysis (like the Balazs issue map), it's a wall of markdown. You can't act on individual issues.

### The Solution

Baker outputs a **structured JSON block** at the end of its response. The frontend detects it, parses it, and renders each issue as a separate card with triage.

### Backend: Structured Output for Person Queries

**File:** `orchestrator/scan_prompt.py` or `orchestrator/prompt_builder.py`

When Baker detects a person-centric query (keywords: "issues connected with", "outstanding for", "what does X owe", "what do we owe X"), append this instruction to the scan prompt:

```
IMPORTANT: When listing issues connected to a person, ALSO append a JSON block at the very end
of your response, fenced with ```baker-issues ... ```. Format:

\```baker-issues
{
  "person": "Balazs Csepregi",
  "issues": [
    {
      "title": "Brief Balazs on MO Kitzbühel approach",
      "status": "overdue",
      "due_date": "2026-03-27",
      "detail": "Committed during March 13 meeting to brief him on MO position shift re Kitzbühel.",
      "source": "meeting_transcript",
      "matter": "kempinski-kitzbuehel"
    },
    {
      "title": "Sound out MO on Davos",
      "status": "overdue",
      "due_date": "2026-03-24",
      "detail": "ClickUp task: sound out Mandarin Oriental on Davos branding.",
      "source": "clickup",
      "matter": "alpengo-davos"
    }
  ]
}
\```

This block is machine-parsed by the frontend — the user sees the readable text above.
Always include this block when listing person-specific tasks/issues/commitments.
```

### Frontend: Parse and Render Issue Cards

**File:** `outputs/static/app.js`

After Baker's SSE response completes, check if the response contains a ` ```baker-issues ``` ` block:

```javascript
function renderBakerResponse(answer) {
  const issueBlockMatch = answer.match(/```baker-issues\s*([\s\S]*?)```/);

  if (issueBlockMatch) {
    // Remove the JSON block from visible text
    const cleanAnswer = answer.replace(/```baker-issues[\s\S]*?```/, '').trim();

    // Render the readable text first
    renderMarkdown(cleanAnswer);

    // Parse and render issue cards
    try {
      const data = JSON.parse(issueBlockMatch[1]);
      renderIssueCards(data.person, data.issues);
    } catch (e) {
      console.warn('Failed to parse baker-issues block:', e);
      // Fallback: just show the text, no cards
    }
  } else {
    // Normal response — render markdown + general triage bar
    renderMarkdown(answer);
    maybeShowTriageBar(answer);
  }
}
```

### Frontend: Issue Card Rendering

```javascript
function renderIssueCards(person, issues) {
  const container = document.createElement('div');
  container.className = 'issue-cards-container';

  // Header
  const header = document.createElement('div');
  header.className = 'issue-cards-header';
  header.innerHTML = `
    <span>${issues.length} issue${issues.length !== 1 ? 's' : ''} for <strong>${person}</strong></span>
    <button class="triage-btn triage-save-all" onclick="saveAllToPeople('${person}', this)">
      Save All to People
    </button>
  `;
  container.appendChild(header);

  // Individual cards
  issues.forEach((issue, idx) => {
    const card = document.createElement('div');
    card.className = `issue-card issue-${issue.status || 'open'}`;
    card.dataset.index = idx;
    card.dataset.person = person;

    const statusBadge = issue.status === 'overdue'
      ? '<span class="badge badge-overdue">OVERDUE</span>'
      : issue.due_date
        ? `<span class="badge badge-due">DUE ${issue.due_date}</span>`
        : '<span class="badge badge-open">OPEN</span>';

    card.innerHTML = `
      <div class="issue-card-header">
        ${statusBadge}
        ${issue.matter ? `<span class="issue-matter">${issue.matter}</span>` : ''}
      </div>
      <div class="issue-card-title">${issue.title}</div>
      <div class="issue-card-detail">${issue.detail || ''}</div>
      <div class="issue-card-triage">
        <button class="triage-btn" onclick="saveIssueToPeople('${person}', ${idx}, this)">
          Save to People
        </button>
        <button class="triage-btn" onclick="askBakerAbout('${issue.title}', '${person}')">
          Ask Baker
        </button>
        <button class="triage-btn" onclick="flagIssue(${idx}, 'critical', this)">
          Flag Critical
        </button>
        <button class="triage-btn triage-dismiss" onclick="dismissIssueCard(this)">
          ✕
        </button>
      </div>
    `;
    container.appendChild(card);
  });

  // Append to chat area
  document.querySelector('.chat-messages').appendChild(container);
}
```

## Part 3: General Chat Triage Bar

For NON-issue responses (summaries, briefings, analyses), show a simple triage bar:

```
[💾 Save to Dossiers] [Baker suggestion] [Baker suggestion] [✕]
```

**Rules:**
- Only show if answer > 300 characters
- Don't show for action confirmations ("✅", "📧 Draft ready", "❌", "Noted")
- "Save to Dossiers" → POST `/api/dossiers/save` → appears in Dossiers section
- Dynamic suggestions: keyword-matched (see CHAT-TRIAGE-1 brief for details)
- "✕" → hides triage bar

## Part 4: Database — `people_issues` Table

**File:** `outputs/dashboard.py` (startup migration block)

```sql
CREATE TABLE IF NOT EXISTS people_issues (
    id SERIAL PRIMARY KEY,
    person_name TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    status TEXT DEFAULT 'open',        -- open, overdue, done, dismissed
    due_date DATE,
    source TEXT,                        -- ask_baker, clickup, deadline, manual
    matter TEXT,                        -- project tag
    is_critical BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_people_issues_person ON people_issues(person_name);
CREATE INDEX IF NOT EXISTS idx_people_issues_status ON people_issues(status);
```

## Part 5: API Endpoints

**File:** `outputs/dashboard.py`

### GET /api/people — List people with issue counts

```python
@app.get("/api/people")
async def list_people(request: Request):
    _check_auth(request)
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT person_name,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status = 'overdue') AS overdue_count,
               MAX(updated_at) AS last_updated
        FROM people_issues
        WHERE status NOT IN ('done', 'dismissed')
        GROUP BY person_name
        ORDER BY overdue_count DESC, total DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"name": r[0], "total": r[1], "overdue": r[2], "last_updated": str(r[3])} for r in rows]
```

### GET /api/people/{name}/issues — Get issues for a person

```python
@app.get("/api/people/{name}/issues")
async def get_person_issues(name: str, request: Request):
    _check_auth(request)
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, detail, status, due_date, source, matter, is_critical, created_at
        FROM people_issues
        WHERE LOWER(person_name) = LOWER(%s)
          AND status NOT IN ('dismissed')
        ORDER BY
          CASE WHEN status = 'overdue' THEN 0
               WHEN due_date IS NOT NULL THEN 1
               ELSE 2 END,
          due_date ASC NULLS LAST,
          created_at DESC
    """, (name,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "title": r[1], "detail": r[2], "status": r[3],
             "due_date": str(r[4]) if r[4] else None, "source": r[5],
             "matter": r[6], "is_critical": r[7], "created_at": str(r[8])} for r in rows]
```

### POST /api/people/issues — Save issue(s) to a person

```python
@app.post("/api/people/issues")
async def save_people_issues(request: Request):
    _check_auth(request)
    body = await request.json()
    person = body.get("person_name")
    issues = body.get("issues", [])  # list of {title, detail, status, due_date, source, matter}

    if not person or not issues:
        return JSONResponse({"error": "person_name and issues required"}, status_code=400)

    conn = get_pg_connection()
    cur = conn.cursor()
    saved = 0
    try:
        for issue in issues:
            # Dedup: skip if same person + title exists and is not dismissed
            cur.execute("""
                SELECT id FROM people_issues
                WHERE LOWER(person_name) = LOWER(%s)
                  AND LOWER(title) = LOWER(%s)
                  AND status NOT IN ('dismissed', 'done')
                LIMIT 1
            """, (person, issue.get("title", "")))
            if cur.fetchone():
                continue  # Already exists

            cur.execute("""
                INSERT INTO people_issues (person_name, title, detail, status, due_date, source, matter)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                person,
                issue.get("title", "Untitled"),
                issue.get("detail"),
                issue.get("status", "open"),
                issue.get("due_date"),
                issue.get("source", "ask_baker"),
                issue.get("matter")
            ))
            saved += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Save people issues failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        cur.close()
        conn.close()
    return {"saved": saved, "person": person}
```

### PATCH /api/people/issues/{id} — Triage an issue

```python
@app.patch("/api/people/issues/{issue_id}")
async def triage_people_issue(issue_id: int, request: Request):
    _check_auth(request)
    body = await request.json()
    # Allowed fields: status, is_critical
    updates = []
    params = []
    if "status" in body:
        updates.append("status = %s")
        params.append(body["status"])
    if "is_critical" in body:
        updates.append("is_critical = %s")
        params.append(body["is_critical"])
    if not updates:
        return JSONResponse({"error": "Nothing to update"}, status_code=400)

    updates.append("updated_at = NOW()")
    params.append(issue_id)

    conn = get_pg_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"""
            UPDATE people_issues SET {', '.join(updates)} WHERE id = %s RETURNING id
        """, params)
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not row:
            return JSONResponse({"error": "Issue not found"}, status_code=404)
        return {"updated": issue_id}
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return JSONResponse({"error": str(e)}, status_code=500)
```

### POST /api/dossiers/save — Save to Dossiers (from triage bar)

```python
@app.post("/api/dossiers/save")
async def save_to_dossiers(request: Request):
    _check_auth(request)
    body = await request.json()
    question = body.get("question", "Baker Analysis")
    answer = body.get("answer", "")

    if not answer or len(answer) < 100:
        return JSONResponse({"error": "Answer too short to save"}, status_code=400)

    import re
    topic = re.sub(r'https?://\S+', '', question).strip()[:120]
    if not topic:
        topic = "Baker Analysis"

    conn = get_pg_connection()
    cur = conn.cursor()
    try:
        # Dedup: skip if same topic saved in last 1 hour
        cur.execute("""
            SELECT id FROM deep_analyses
            WHERE topic = %s AND created_at > NOW() - INTERVAL '1 hour'
            LIMIT 1
        """, (topic,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return {"status": "already_saved"}

        cur.execute("""
            INSERT INTO deep_analyses (topic, analysis_text, prompt, source_documents, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            RETURNING id
        """, (topic, answer, question, "ask_baker"))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "saved", "id": row[0]}
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        cur.close()
        conn.close()
        return JSONResponse({"error": str(e)}, status_code=500)
```

## Part 6: Scan Prompt Addition

**File:** `orchestrator/scan_prompt.py`

Add to the system prompt (or to the `build_mode_aware_prompt()` additions):

```
## Structured Issue Output

When listing tasks, issues, or commitments connected to a specific person, ALSO output
a machine-readable JSON block at the very end of your answer. Fence it with triple backticks
and the language tag `baker-issues`. The frontend uses this to render individual triage-able cards.

Format:
\```baker-issues
{
  "person": "Full Name",
  "issues": [
    {
      "title": "Short issue title (imperative)",
      "status": "overdue|open|due_soon",
      "due_date": "YYYY-MM-DD or null",
      "detail": "1-2 sentence context",
      "source": "meeting|clickup|email|deadline|whatsapp",
      "matter": "project-slug or null"
    }
  ]
}
\```

Rules:
- Only include this block for person-centric queries (issues for X, what does X owe, outstanding with X)
- The readable text above remains the primary output — the JSON is supplementary
- Keep titles short and actionable
- Include ALL issues you found, even minor ones — the Director will triage
```

## Files to Modify

| File | Change |
|------|--------|
| `outputs/dashboard.py` | Table migration, 5 new endpoints, scan prompt hook |
| `outputs/static/app.js` | Issue card rendering, triage functions, People nav, Save to Dossiers |
| `outputs/static/index.html` | People section in sidebar HTML + CSS for issue cards + triage bars |
| `outputs/static/mobile.js` | Same issue card + triage for mobile |
| `outputs/static/mobile.html` | Mobile People section |
| `orchestrator/scan_prompt.py` | Structured issue output instruction |

## CSS for Issue Cards

```css
.issue-cards-container {
  margin-top: 16px;
  border-top: 1px solid rgba(255,255,255,0.1);
  padding-top: 12px;
}
.issue-cards-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-size: 14px;
  color: #999;
}
.issue-card {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 8px;
}
.issue-card.issue-overdue {
  border-left: 3px solid #e74c3c;
}
.issue-card.issue-due_soon {
  border-left: 3px solid #d4af37;
}
.issue-card.issue-open {
  border-left: 3px solid #4ecdc4;
}
.issue-card-header {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
}
.badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  text-transform: uppercase;
}
.badge-overdue { background: rgba(231,76,60,0.2); color: #e74c3c; }
.badge-due { background: rgba(212,175,55,0.2); color: #d4af37; }
.badge-open { background: rgba(78,205,196,0.2); color: #4ecdc4; }
.issue-matter {
  font-size: 11px;
  color: #666;
}
.issue-card-title {
  font-size: 15px;
  font-weight: 500;
  color: #e0e0e0;
  margin-bottom: 4px;
}
.issue-card-detail {
  font-size: 13px;
  color: #999;
  margin-bottom: 10px;
  line-height: 1.4;
}
.issue-card-triage {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
/* Reuse .triage-btn styles from CHAT-TRIAGE-1 */
.chat-triage, .issue-card-triage {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.triage-btn {
  padding: 5px 12px;
  border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.04);
  color: #aaa;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}
.triage-btn:hover {
  background: rgba(255,255,255,0.10);
  color: #fff;
}
.triage-save-all {
  border-color: rgba(78,205,196,0.3);
  color: #4ecdc4;
}
```

## Implementation Sequence

1. **DB migration** — create `people_issues` table
2. **API endpoints** — all 5 endpoints
3. **Scan prompt** — structured issue output instruction
4. **Frontend: issue card renderer** — parse `baker-issues` block, render cards
5. **Frontend: triage bar** — for non-issue responses (Save to Dossiers + suggestions)
6. **Frontend: People sidebar section** — nav item, list view, detail view
7. **Mobile** — same patterns adapted for touch
8. **Verify** — test full flow: ask about person → cards render → triage → appears in People

## Testing

1. Ask Baker: "What issues are connected with Balazs?" → should render issue cards with triage
2. Click "Save to People" on one card → card shows "✓ Saved"
3. Click People in sidebar → Balazs appears with count
4. Click Balazs → see saved issues with triage
5. Click "Mark Done" on an issue → disappears from active list
6. Click "Dismiss" → hidden
7. Ask Baker a non-person question → should show general triage bar (Save to Dossiers, etc.)
8. Ask a short question → no triage bar

## Verification

```bash
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('orchestrator/scan_prompt.py', doraise=True)"
```
