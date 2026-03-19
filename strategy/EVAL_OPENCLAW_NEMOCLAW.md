# OpenClaw + NemoClaw for Baker v2: Technical Evaluation

**For:** Chairman | **From:** AI Head | **Date:** 19 March 2026 | **Verdict: NO-GO (for now)**

---

## The Bottom Line

OpenClaw is a personal AI agent. Baker is already an enterprise AI agent. Layering OpenClaw on Baker would mean *replacing* Baker's brain with a less customized one, then rebuilding all of Baker's custom integrations as OpenClaw skills. That's a rewrite disguised as an upgrade. The security posture is unacceptable for our data.

**What Baker actually needs** is a better agent loop — multi-step reasoning chains where Baker can plan, execute, and verify autonomously. This can be achieved with the Anthropic Agent SDK or by extending Baker's existing 17-tool agent loop. No new framework required.

---

## Evaluation Summary

| Question | Finding |
|----------|---------|
| **1. Claude as primary LLM?** | Yes. Claude is OpenClaw's *default recommended* model. NemoClaw Privacy Router explicitly supports Anthropic as cloud provider. No compatibility issue. |
| **2. Baker endpoints as skills?** | Possible but painful. Baker's 17 agent tools + FastAPI endpoints would need to be wrapped as OpenClaw SKILL.md files. Each skill = a natural-language API contract. Estimate: 2-3 weeks just for the wrapping, then debugging the agent's ability to use them correctly. |
| **3. Mac compatibility?** | Yes for development. OpenClaw runs natively on Apple Silicon. NemoClaw works in cloud-only mode (no local inference). Local Nemotron models require NVIDIA GPU. Cloud-only is fine for prototyping. |
| **4. Migration path?** | **Full rewrite.** OpenClaw is not a library you layer on — it IS the agent. Baker's pipeline, decision engine, capability framework, and scoring logic would all need to be re-expressed as OpenClaw constructs. Estimate: 8-12 weeks for a prototype that matches Baker's current capabilities. |
| **5. Alpha stability?** | **Unacceptable.** OpenClaw core is stable (250K+ stars), but the ecosystem is compromised. NemoClaw is early alpha — no security audits, no pen testing, no production benchmarks. |
| **6. Privacy Router value?** | **High concept, low readiness.** Routing sensitive legal/financial data to local models while complex reasoning goes to Claude is architecturally sound. But it requires NVIDIA GPU hardware (DGX Spark ~$3-5K) and alpha software. Baker can implement the same routing pattern natively with a model selector in pipeline.py (we already did this for COST-OPT-1). |
| **7. Best framework for Baker?** | **Anthropic Agent SDK** or **native enhancement.** See below. |

---

## The Security Problem

This is the dealbreaker. In February-March 2026:

- **20% of OpenClaw's skill registry was malicious** (824+ entries). Bitdefender, Koi Security, and Snyk all confirmed independently.
- **CVE-2026-25253**: One-click remote code execution (CVSS 8.8) affecting 17,500+ exposed instances. Exfiltrates auth tokens via WebSocket.
- **511 additional vulnerabilities** across the platform, 8 rated critical.
- **Meta banned OpenClaw company-wide.** Microsoft classified it as "untrusted code execution."
- Peter Steinberger (creator) **left for OpenAI** in February 2026. Project governance transferred to an unnamed foundation.

Baker handles contracts, financials, legal disputes, investor data, and personal communications. Running this through a framework with active CVEs and compromised skill registries is a non-starter. NemoClaw was announced specifically to address this, but it's alpha — no independent security audits exist.

---

## What Baker Already Has (vs. What OpenClaw Adds)

| Capability | Baker Today | OpenClaw Would Add |
|-----------|------------|-------------------|
| Tool-calling agent loop | 17 tools, streaming, tier-based routing | Similar (different runtime) |
| Autonomous reasoning | Single-pass + agentic RAG (5-iteration loop) | Multi-step planning with tool use |
| Data integrations | 10 custom triggers (email, WA, ClickUp, Dropbox, calendar, Fireflies, RSS, Slack, Todoist, Browser) | Would need to rebuild all as skills |
| Decision engine | 4-step classifier, 3-component scorer, VIP SLA | None — OpenClaw relies on LLM judgment |
| Capability framework | 13 specialists, decomposer/synthesizer | None — OpenClaw is single-persona |
| Security | Safety rules, audit log, kill switches, CORS, API auth | NemoClaw sandbox + policy engine (alpha) |
| Memory | PostgreSQL + Qdrant, 15 collections, structured + vector | Basic persistent memory |
| Cost control | Circuit breaker, per-capability cost tracking, Haiku routing | None built-in |

Baker's actual gap is narrow: **multi-step autonomous action chains.** The EVOK example from the brief (email arrives → check calendar → cross-ref matter → draft briefing → alert Director) requires Baker to execute a *plan* with multiple tool calls in sequence, verifying each step. Today, Baker can do this in agentic mode (agent.py) but only when explicitly triggered — not proactively.

---

## Recommended Path: Enhance Baker Natively

**Option A: Anthropic Agent SDK** (recommended)
- Purpose-built for Claude, Baker's primary LLM
- Same agent loop and tool infrastructure that powers Claude Code
- Python SDK available, integrates cleanly with FastAPI
- Baker's existing tools can be registered directly — no SKILL.md wrapping
- Security is Anthropic's responsibility, not an open-source community
- Effort: **2-3 weeks** to prototype autonomous action chains
- Cost: API calls only (no new infrastructure)

**Option B: Extend Baker's Agent Loop**
- Baker's `agent.py` already has a working tool-calling loop with 17 tools
- Add a "planner" step: before executing, Baker generates a multi-step plan, then executes it step-by-step with verification
- This is what the capability framework's decomposer/synthesizer already does for complex questions — extend it to actions
- Effort: **1-2 weeks** to add plan-execute-verify to the agent loop
- Risk: Lower than any framework adoption

**Option C: Wait for NemoClaw GA** (hedge)
- Monitor NemoClaw maturity (target: Q3 2026 for beta)
- If Bellboy/NVIDIA partnership materializes, revisit with development hardware
- The Privacy Router pattern is valuable — implement it natively now, swap in NemoClaw later if it matures
- Cost: Zero until decision point

---

## Recommendation

**Go with Option B now, Option A next.** Extend Baker's existing agent loop with multi-step planning (1-2 weeks). If that hits limits, adopt Anthropic Agent SDK (2-3 weeks). Revisit NemoClaw when it exits alpha and gets independent security audits (likely Q4 2026).

**Do not buy hardware.** Cloud-only mode works for everything Baker needs. Hardware decision only if Bellboy/NVIDIA deal provides development units.

**Do not adopt OpenClaw.** The security posture is disqualifying for Baker's data sensitivity. The framework adds complexity without capability that Baker doesn't already have or can't build faster natively.

---

## Sources

- [NVIDIA NemoClaw Announcement](https://nvidianews.nvidia.com/news/nvidia-announces-nemoclaw)
- [NemoClaw Architecture Deep Dive — Particula](https://particula.tech/blog/nvidia-nemoclaw-openclaw-enterprise-security)
- [OpenClaw Security Crisis: 20% Malicious Skills — Particula](https://particula.tech/blog/openclaw-security-crisis-malicious-ai-agents)
- [TechCrunch: NemoClaw Solves OpenClaw's Security Problem](https://techcrunch.com/2026/03/16/nvidias-version-of-openclaw-could-solve-its-biggest-problem-security/)
- [OpenClaw Wikipedia](https://en.wikipedia.org/wiki/OpenClaw)
- [OpenClaw Anthropic/Claude Integration Docs](https://docs.openclaw.ai/providers/anthropic)
- [AI Agent Framework Comparison 2026 — ClawTank](https://clawtank.dev/blog/ai-agent-frameworks-comparison-2026)
- [Anthropic Agent SDK Overview](https://platform.claude.com/docs/en/agent-sdk/overview)
- [GTC 2026: RTX PCs + NemoClaw — NVIDIA Blog](https://blogs.nvidia.com/blog/rtx-ai-garage-gtc-2026-nemoclaw/)
- [CNBC: NVIDIA NemoClaw Plans](https://www.cnbc.com/2026/03/10/nvidia-open-source-ai-agent-platform-nemoclaw-wired-agentic-tools-openclaw-clawdbot-moltbot.html)
