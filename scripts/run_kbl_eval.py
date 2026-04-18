"""
KBL Pre-Shadow Eval — Runner

Reads a labeled JSONL, runs each signal through the KBL Step-1 triage prompt
on macmini via Ollama, compares model output to Director's labels, and
reports accuracy against D1 acceptance thresholds.

Reuses prompt + JSON-parser patterns from scripts/benchmark_ollama_triage.py.
Talks to Ollama over Tailscale (http://macmini:11434) by default; falls back
to SSH + local curl on macmini if direct HTTP fails.

Usage:
  python3 scripts/run_kbl_eval.py outputs/kbl_eval_set_20260417_labeled.jsonl
  python3 scripts/run_kbl_eval.py <labeled.jsonl> --model gemma4:latest
  python3 scripts/run_kbl_eval.py <labeled.jsonl> --compare-qwen   # also run Qwen
  python3 scripts/run_kbl_eval.py <labeled.jsonl> --dry-run        # parse + count only

Outputs:
  outputs/kbl_eval_results_<YYYYMMDD>.json
    Full per-signal results + summary + pass/fail against D1 thresholds.

Exit codes:
  0 = all models under test PASS all D1 thresholds
  1 = at least one threshold failed on primary model (D1 failure-path entered)
"""
from __future__ import annotations

import argparse
import json
import logging
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kbl import slug_registry  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("run_kbl_eval")

OLLAMA_HOST_DEFAULT = "http://macmini:11434"
SSH_HOST_DEFAULT = "macmini"

# D1 locks — MUST match production runtime config.
D1_OPTIONS = {
    "temperature": 0.0,
    "seed": 42,
    "top_p": 0.9,
    "num_predict": 512,
}

# KBL Step-1 prompt — v3 content, built dynamically from the slug registry.
#
# v2 eval root-caused matter miss to the model seeing slug names without
# knowing what each MEANS (hagenauer-rg7 → brisen-lp was 13/33 Gemma misses —
# the model anchored on "Brisen" in email headers). v3 fixes this with a
# per-slug semantic glossary, a disambiguation block for the most common
# errors, and STRICT vedana rules. SLUGS-1 moves the slug list + descriptions
# to baker-vault's slugs.yml so the prompt never drifts from the validator /
# production router. Built once at process start; if registry.reload() fires
# mid-process, call _build_step1_prompt() again.
def _build_step1_prompt() -> str:
    slugs_sorted = sorted(slug_registry.active_slugs())
    width = max((len(s) for s in slugs_sorted), default=0) + 2
    glossary_lines = [
        f"  {s:<{width}}— {slug_registry.describe(s)}" for s in slugs_sorted
    ]
    glossary_lines.append(
        f"  {'null':<{width}}— no matter applies "
        "(automated noise, newsletters, FYI with no business link)"
    )
    glossary = "\n".join(glossary_lines)
    return (
        "You are a triage agent for a Baker business operation (real estate, "
        "hospitality, legal disputes, investment). Classify this signal. "
        "Output ONLY valid JSON, no commentary.\n\n"
        'Signal: "{signal}"\n\n'
        "Respond with exactly this JSON:\n"
        "{{\n"
        '  "matter": "<slug from allowed list below, or the literal string null if no matter applies>",\n'
        '  "vedana": "opportunity | threat | routine",\n'
        '  "triage_score": 0-100,\n'
        '  "summary": "one line"\n'
        "}}\n\n"
        "Matter slugs (pick ONE slug whose description best matches the "
        "signal, or null if none apply):\n\n"
        f"{glossary}\n\n"
        "Never invent new slugs. Never return generic category strings like "
        '"hospitality", "investment", "legal" — those are invalid; return '
        "null instead.\n\n"
        "Disambiguation notes (IMPORTANT — common errors):\n"
        "- A brisengroup.com email header or \"Brisen\" in a sender name does NOT imply brisen-lp.\n"
        "  brisen-lp is ONLY for fund/LP vehicle matters. A Hagenauer-project email from a\n"
        "  brisengroup.com address is hagenauer-rg7, not brisen-lp.\n"
        "- hagenauer-rg7 vs cupial: both relate to the RG7 project, but cupial is specifically\n"
        "  the buyer-side dispute over Tops 4,5,6,18. If the signal mentions Cupial(s), Hassa,\n"
        "  Ofenheimer in a buyer-contract context → cupial. If it's about the contractor (Heidenauer),\n"
        "  Schlussabrechnung, or general project-level → hagenauer-rg7.\n"
        "- kitzbuhel-six-senses vs steininger: both share the court case. Choose the slug that\n"
        "  the signal's main subject is about — the project development vs the family credibility.\n\n"
        "vedana classification rules (STRICT):\n"
        "- opportunity: NEW strategic gains ONLY — a new deal, investor interest, unrequested "
        "approach, favorable market shift, novel capability revealed. Defensive wins inside an "
        "ongoing threat arc (e.g., court ruling in our favor on a dispute) stay in threat, not opportunity.\n"
        "- threat: risks, problems, disputes, deadlines, unpaid invoices, regulatory issues, "
        "counterparty demands, anything requiring defensive action.\n"
        "- routine: noise — receipts, automated notifications, newsletters, FYI emails, admin "
        "correspondence with no action required."
    )

# Production uses opportunity/threat/routine; Director labels use Buddhist
# vedana pleasant/unpleasant/neutral. Map both to a canonical form for comparison.
NORMALIZE_VEDANA = {
    "opportunity": "pleasant",
    "pleasant":    "pleasant",
    "threat":      "unpleasant",
    "unpleasant":  "unpleasant",
    "routine":     "neutral",
    "neutral":     "neutral",
}

# Triage threshold used to decide "would this have alerted Director?"
# Matches DECISIONS_PRE_KBL_A_V2_DRAFT.md env var KBL_TRIAGE_THRESHOLD (default 40).
TRIAGE_ALERT_THRESHOLD = 40

# D1 acceptance thresholds
ACCEPT = {
    "vedana_overall":    0.90,
    "vedana_per_source": 0.85,
    "json_validity":     1.00,
    "primary_matter":    0.80,
}


def normalize_vedana(v: str | None) -> str | None:
    if not isinstance(v, str):
        return None
    return NORMALIZE_VEDANA.get(v.lower().strip())


def parse_json_response(text: str) -> tuple[dict, bool]:
    """Reused from benchmark_ollama_triage.py — three fallback strategies."""
    text = (text or "").strip()
    try:
        return json.loads(text), True
    except json.JSONDecodeError:
        pass
    for marker in ("```json", "```"):
        if marker in text:
            start = text.index(marker) + len(marker)
            end = text.index("```", start) if "```" in text[start:] else len(text)
            try:
                return json.loads(text[start:end].strip()), True
            except json.JSONDecodeError:
                pass
    b0, b1 = text.find("{"), text.rfind("}") + 1
    if b0 >= 0 and b1 > b0:
        try:
            return json.loads(text[b0:b1]), True
        except json.JSONDecodeError:
            pass
    return {"raw": text[:500]}, False


def ollama_generate_http(model: str, prompt: str, host: str) -> tuple[str, float]:
    """Direct HTTP to Ollama over Tailscale. Requires `requests`."""
    import requests  # local import — not used in SSH fallback
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": D1_OPTIONS,
    }
    start = time.time()
    r = requests.post(f"{host}/api/generate", json=payload, timeout=120)
    elapsed = time.time() - start
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:200]}", elapsed
    return r.json().get("response", ""), elapsed


def ollama_generate_ssh(model: str, prompt: str, ssh_host: str) -> tuple[str, float]:
    """SSH fallback — pipe payload to curl on macmini. Slower per-call."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": D1_OPTIONS,
    })
    cmd = f"ssh {shlex.quote(ssh_host)} 'curl -s -X POST http://localhost:11434/api/generate -d @-'"
    start = time.time()
    try:
        proc = subprocess.run(cmd, input=payload, capture_output=True, text=True,
                              timeout=120, shell=True)
    except subprocess.TimeoutExpired:
        return "TIMEOUT (120s)", 120.0
    elapsed = time.time() - start
    if proc.returncode != 0:
        return f"SSH failure: {proc.stderr[:200]}", elapsed
    try:
        return json.loads(proc.stdout).get("response", ""), elapsed
    except json.JSONDecodeError:
        return proc.stdout[:500], elapsed


def ollama_generate(model: str, prompt: str, *,
                    use_http: bool, host: str, ssh_host: str) -> tuple[str, float]:
    if use_http:
        try:
            return ollama_generate_http(model, prompt, host)
        except Exception as e:
            logger.warning("direct HTTP to %s failed (%s) — falling back to SSH", host, e)
    return ollama_generate_ssh(model, prompt, ssh_host)


def score_row(label: dict, parsed: dict, json_ok: bool) -> dict:
    """Compare one model response to the Director label. Returns a result dict.

    Canonical Director-labeling vocab is production (opportunity/threat/routine).
    Normalizer maps both production and Buddhist (pleasant/unpleasant/neutral)
    synonyms to one internal key so the comparison is robust if the model
    defies the prompt and emits the other vocabulary.
    """
    label_vedana_raw = label.get("vedana_expected")
    label_pm = label.get("primary_matter_expected")
    label_pass = label.get("triage_threshold_pass_expected")

    out_vedana_raw = parsed.get("vedana")
    out_matter_raw = parsed.get("matter")
    out_score = parsed.get("triage_score")

    label_vedana = normalize_vedana(label_vedana_raw)
    out_vedana = normalize_vedana(out_vedana_raw)
    out_matter = slug_registry.normalize(out_matter_raw)

    # Preserve pre-registry semantic: a non-empty model string that fails to
    # normalize (e.g. "hospitality") is "unknown" — it must NOT equal a
    # label of None. Only empty / null-ish inputs are treated as legitimately None.
    model_returned_non_empty = (
        isinstance(out_matter_raw, str)
        and out_matter_raw.strip() != ""
        and out_matter_raw.strip().lower() not in {"none", "null"}
    )
    unknown_non_canonical = model_returned_non_empty and out_matter is None

    vedana_ok = (out_vedana is not None and out_vedana == label_vedana) if json_ok else False
    matter_ok = (
        (out_matter == label_pm) and not unknown_non_canonical
    ) if json_ok else False
    score_bucket_ok = False
    if json_ok and isinstance(out_score, (int, float)) and isinstance(label_pass, bool):
        model_would_alert = out_score >= TRIAGE_ALERT_THRESHOLD
        score_bucket_ok = (model_would_alert == label_pass)

    return {
        "signal_id":        label.get("signal_id"),
        "source":           label.get("source"),
        "json_ok":          json_ok,
        "vedana_ok":        vedana_ok,
        "matter_ok":        matter_ok,
        "score_bucket_ok":  score_bucket_ok,
        "model_vedana":     out_vedana_raw,
        "model_matter":     out_matter_raw,
        "model_score":      out_score,
        "label_vedana":     label_vedana_raw,   # as Director labeled (e.g. "threat")
        "label_matter":     label_pm,
        "label_pass":       label_pass,
    }


def summarize(results: list[dict]) -> dict:
    total = len(results)
    if total == 0:
        return {"total": 0}

    def pct(n: int, d: int) -> float:
        return (n / d) if d else 0.0

    by_source: dict[str, list[dict]] = {}
    for r in results:
        by_source.setdefault(r["source"], []).append(r)

    summary = {
        "total": total,
        "json_validity":   pct(sum(r["json_ok"] for r in results), total),
        "vedana_overall":  pct(sum(r["vedana_ok"] for r in results), total),
        "primary_matter":  pct(sum(r["matter_ok"] for r in results), total),
        "score_bucket":    pct(sum(r["score_bucket_ok"] for r in results), total),
        "per_source":      {},
    }
    for src, rs in by_source.items():
        n = len(rs)
        summary["per_source"][src] = {
            "n": n,
            "json_validity":  pct(sum(r["json_ok"] for r in rs), n),
            "vedana":         pct(sum(r["vedana_ok"] for r in rs), n),
            "primary_matter": pct(sum(r["matter_ok"] for r in rs), n),
            "score_bucket":   pct(sum(r["score_bucket_ok"] for r in rs), n),
        }
    return summary


def pass_fail(summary: dict) -> tuple[bool, list[str]]:
    """Return (all_passed, list_of_failures)."""
    fails: list[str] = []
    if summary.get("vedana_overall", 0) < ACCEPT["vedana_overall"]:
        fails.append(f"vedana_overall {summary['vedana_overall']:.2%} < {ACCEPT['vedana_overall']:.0%}")
    if summary.get("json_validity", 0) < ACCEPT["json_validity"]:
        fails.append(f"json_validity {summary['json_validity']:.2%} < {ACCEPT['json_validity']:.0%}")
    if summary.get("primary_matter", 0) < ACCEPT["primary_matter"]:
        fails.append(f"primary_matter {summary['primary_matter']:.2%} < {ACCEPT['primary_matter']:.0%}")
    for src, s in summary.get("per_source", {}).items():
        if s["vedana"] < ACCEPT["vedana_per_source"]:
            fails.append(f"vedana[{src}] {s['vedana']:.2%} < {ACCEPT['vedana_per_source']:.0%}")
    return (len(fails) == 0, fails)


def print_report(model: str, summary: dict, fails: list[str]) -> None:
    print(f"\n=== KBL Pre-Shadow Eval — {model} === ")
    print(f"total: {summary['total']}")
    print(f"  json_validity:  {summary['json_validity']:.1%}")
    print(f"  vedana overall: {summary['vedana_overall']:.1%}")
    print(f"  primary_matter: {summary['primary_matter']:.1%}")
    print(f"  score_bucket:   {summary['score_bucket']:.1%}")
    print("per-source:")
    for src, s in summary["per_source"].items():
        print(f"  {src:8s} n={s['n']:2d}  vedana={s['vedana']:.0%}  "
              f"pm={s['primary_matter']:.0%}  json={s['json_validity']:.0%}  "
              f"bucket={s['score_bucket']:.0%}")
    if fails:
        print(f"RESULT: {model} — FAIL:")
        for f in fails:
            print(f"  - {f}")
    else:
        print(f"RESULT: {model} — PASS (all D1 thresholds met)")


def run_model(labels: list[dict], model: str, *, use_http: bool,
              host: str, ssh_host: str) -> list[dict]:
    results: list[dict] = []
    step1_prompt_tmpl = _build_step1_prompt()
    for i, label in enumerate(labels, start=1):
        signal = (label.get("raw_content") or label.get("signal_text") or "")[:3000]
        prompt = step1_prompt_tmpl.format(signal=signal.replace('"', "'"))
        text, elapsed = ollama_generate(
            model, prompt, use_http=use_http, host=host, ssh_host=ssh_host,
        )
        parsed, json_ok = parse_json_response(text)
        scored = score_row(label, parsed, json_ok)
        scored["elapsed_s"] = round(elapsed, 2)
        results.append(scored)
        logger.info("  [%2d/%d] %s %-8s elapsed=%.1fs  vedana_ok=%s matter_ok=%s json_ok=%s",
                    i, len(labels), scored["signal_id"], scored["source"],
                    elapsed, scored["vedana_ok"], scored["matter_ok"], scored["json_ok"])
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("labeled_path")
    parser.add_argument("--model", default="gemma4:latest")
    parser.add_argument("--compare-qwen", action="store_true",
                        help="After primary model, also run qwen2.5:14b")
    parser.add_argument("--http", default=OLLAMA_HOST_DEFAULT,
                        help="Direct Ollama HTTP endpoint; fallback SSH if unreachable")
    parser.add_argument("--ssh-host", default=SSH_HOST_DEFAULT)
    parser.add_argument("--no-http", action="store_true",
                        help="Skip direct HTTP, always SSH (slower but universal)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse labeled file, report counts, do not call Ollama")
    parser.add_argument("--out-dir", default="outputs")
    args = parser.parse_args()

    p = Path(args.labeled_path)
    if not p.exists():
        logger.error("%s not found", p); sys.exit(1)

    labels: list[dict] = []
    with open(p) as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                labels.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.error("line %d: invalid JSON (%s)", line_no, e); sys.exit(1)

    logger.info("loaded %d labeled signals from %s", len(labels), p)

    if args.dry_run:
        by_source: dict[str, int] = {}
        for lbl in labels:
            by_source[lbl.get("source", "unknown")] = by_source.get(lbl.get("source", "unknown"), 0) + 1
        for src, n in sorted(by_source.items()):
            logger.info("  %s: %d", src, n)
        logger.info("--dry-run: skipping Ollama calls")
        return

    # Sanity-check that labels are filled
    filled = [l for l in labels if l.get("vedana_expected") is not None]
    if len(filled) != len(labels):
        logger.error("labels not fully filled: %d/%d have vedana_expected — "
                     "run scripts/validate_eval_labels.py first",
                     len(filled), len(labels))
        sys.exit(1)

    use_http = not args.no_http
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_path = out_dir / f"kbl_eval_results_{date_str}.json"

    all_results: dict[str, dict] = {}

    # Primary model
    logger.info("running primary: %s", args.model)
    primary_results = run_model(labels, args.model,
                                use_http=use_http, host=args.http, ssh_host=args.ssh_host)
    primary_summary = summarize(primary_results)
    primary_ok, primary_fails = pass_fail(primary_summary)
    print_report(args.model, primary_summary, primary_fails)
    all_results[args.model] = {
        "results":  primary_results,
        "summary":  primary_summary,
        "passed":   primary_ok,
        "failures": primary_fails,
    }

    # Optional Qwen comparison (D1 failure-path)
    if args.compare_qwen and args.model != "qwen2.5:14b":
        logger.info("running comparison: qwen2.5:14b")
        qwen_results = run_model(labels, "qwen2.5:14b",
                                 use_http=use_http, host=args.http, ssh_host=args.ssh_host)
        qwen_summary = summarize(qwen_results)
        qwen_ok, qwen_fails = pass_fail(qwen_summary)
        print_report("qwen2.5:14b", qwen_summary, qwen_fails)
        all_results["qwen2.5:14b"] = {
            "results":  qwen_results,
            "summary":  qwen_summary,
            "passed":   qwen_ok,
            "failures": qwen_fails,
        }

    with open(out_path, "w") as f:
        json.dump({
            "run_at":   datetime.now(timezone.utc).isoformat(),
            "labeled_path": str(p),
            "models":   all_results,
            "acceptance_thresholds": ACCEPT,
            "triage_alert_threshold": TRIAGE_ALERT_THRESHOLD,
            "slugs_version": slug_registry.registry_version(),
        }, f, indent=2)
    logger.info("wrote full results -> %s", out_path)

    sys.exit(0 if primary_ok else 1)


if __name__ == "__main__":
    main()
