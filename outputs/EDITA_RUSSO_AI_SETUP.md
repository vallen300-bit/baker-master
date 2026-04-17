# Russo AI — Setup & Usage Guide for Edita

## Step 1: Install Claude Code

Open **Terminal** on your Mac (Spotlight → type "Terminal" → Enter).

**1a. Install Node.js** (if not already installed):
```
brew install node
```
If `brew` is not found, first install Homebrew:
```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**1b. Install Claude Code:**
```
npm install -g @anthropic-ai/claude-code
```
If you get a permission error:
```
sudo npm install -g @anthropic-ai/claude-code
```

## Step 2: Connect to Baker (One Command)

This gives Claude Code access to Baker's database — your wealth data, tax calendar, contacts, and all 25 Baker tools.

```
claude mcp add --transport http baker "https://baker-master.onrender.com/mcp?key=bakerbhavanga"
```

That's it. This is a one-time setup. Every future Claude Code session will have Baker access automatically.

## Step 3: Start Claude Code

Open Terminal and type:
```
claude
```

The first time, it will ask you to log in with an Anthropic account. Follow the prompts in your browser.

## Step 4: Select the Right Model

Once Claude Code is running, type:
```
/model opus
```

This selects Claude Opus 4.6 with 1M context — the most capable model.

## Step 5: Your Opening Prompt

Copy and paste this as your **first message** in every new session:

```
I am Edita Vallen. I'm using Baker's Russo AI wealth management system.

Baker has my wealth data (38 positions across 5 jurisdictions), tax calendar
(25 deadlines), and 7 specialist capabilities:
- Russo AI (global orchestrator)
- Swiss Tax (russo_ch) — Russo is our advisor
- Austrian Tax (russo_at) — Leitner is our CFO
- Cyprus Tax (russo_cy) — Constantinos is our contact
- German Tax (russo_de) — Steuerberater Wilpert, Lawyer Christian Merz
- Riviera Tax (russo_fr)
- Luxembourg Tax (russo_lu)

Use the Baker MCP tools to query my actual data before answering:
- baker_raw_query for wealth_positions, wealth_tax_calendar, conversation_memory
- baker_deadlines for upcoming deadlines
- baker_vip_contacts for advisor contacts
- baker_conversation_memory for past discussions
- baker_store_decision to save important conclusions

Always consider tax optimization opportunities across jurisdictions.
```

## Step 6: Start Asking Questions

After the opening prompt, just ask naturally. Examples:

- "What's our total net worth across all jurisdictions?"
- "When are the next tax deadlines in Austria and Cyprus?"
- "Can we optimize the LCG holding structure to reduce withholding tax?"
- "What's our exposure in Baden-Baden and what are the German tax implications?"
- "Compare the Swiss vs Austrian tax treatment of our real estate income"
- "Prepare a summary of all upcoming tax deadlines for the next 3 months"
- "What did we discuss about Cyprus restructuring last time?"

## Daily Workflow (Quick Reference)

```
1. Open Terminal
2. claude
3. /model opus
4. Paste opening prompt (Step 5)
5. Ask your questions
6. /exit when done
```

## Tips

- **Save important conclusions:** Tell Claude "save this as a decision" — it will use `baker_store_decision` to permanently record it
- **Ask about past work:** "What did we conclude about X?" — Claude will search conversation memory
- **Be specific with jurisdictions:** "What are the Austrian tax implications?" works better than "what about taxes?"
- **Request cross-border analysis:** "Compare how this would be taxed in Switzerland vs Cyprus" triggers multi-jurisdiction thinking
- **Update portfolio data:** Tell Claude "update the Baden-Baden property value to EUR 2.5M" — it can write to the database

---

## Where Your Work Is Stored

Everything you discuss with Russo AI is automatically saved in Baker's memory. Nothing is lost between sessions.

### 4 Memory Layers

**1. Conversation Memory**
Every question you ask and every answer you receive is stored in Baker's database, tagged as yours (`owner: edita`). Next time you ask a related question, Baker can recall what was discussed before.

*Example: You ask about Cyprus holding tax in March. In June, you ask "what did we conclude about Cyprus?" — Baker finds the March conversation.*

**2. Insights (Auto-Extracted)**
After every specialist analysis, Baker automatically extracts the key facts and conclusions — amounts, dates, decisions, deadlines — and stores them as "insights." These insights are injected into every future specialist prompt, so Baker's knowledge accumulates over time.

*Example: Russo AI concludes "the Cyprus restructuring saves EUR 180K/year." Next time any specialist runs, they already know this fact.*

**3. Documents**
Every Russo AI analysis is automatically saved as a full document in Baker's document library. These are browsable, searchable, and permanent.

*Example: You ask for a comprehensive Swiss vs Austrian tax comparison. The full analysis is saved as "Russo AI (Swiss Tax): Compare Swiss vs Austrian treatment..." — retrievable months later.*

**4. Structured Data**
Your actual portfolio positions (38 rows) and tax calendar (25 deadlines) are stored as structured data that Russo AI queries directly. This data can be updated as positions change.

*Example: Russo AI knows you have EUR 2.1M in Austrian real estate and EUR 850K in Cyprus holdings — it uses real numbers, not estimates.*

### What This Means in Practice

- **Nothing disappears.** Every conversation, every analysis, every conclusion is permanently stored.
- **Baker gets smarter.** Each session adds insights that improve future answers.
- **You can pick up where you left off.** Ask "what did we discuss about German property tax?" and Baker will recall.
- **Dimitry can see the work too.** The wealth data is shared — both of you benefit from Russo AI's accumulated knowledge.
