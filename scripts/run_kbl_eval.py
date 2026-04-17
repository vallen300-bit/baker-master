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

# KBL Step-1 prompt. Uses production vocabulary (opportunity/threat/routine)
# then normalized to Buddhist vedana in comparison (see NORMALIZE_VEDANA).
STEP1_PROMPT = """You are a triage agent for a 28-matter business operation (real estate, hospitality, legal disputes, investment). Classify this signal. Output ONLY valid JSON, no commentary.

Signal: "{signal}"

Respond with exactly this JSON:
{{
  "matter": "which business matter (e.g. hagenauer-rg7, cupial, mo-vie, ao, brisen-lp, mrci)",
  "vedana": "opportunity | threat | routine",
  "triage_score": 0-100,
  "summary": "one line"
}}"""

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

# Matter slug aliases — model returns varied forms, map them to the allowlist.
MATTER_ALIASES = {
    "mo-vie": ["movie", "mo vienna", "mandarin", "mo-vienna", "mandarin oriental", "mohg"],
    "hagenauer-rg7": ["hagenauer", "rg7"],
    "cupial": ["cupial", "cupials"],
    "brisen-lp": ["brisen", "wertheimer"],
    "ao": ["oskolkov", "andrey"],
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


def normalize_matter(m: str | None) -> str | None:
    """Map any model-produced matter to an allowlist slug (or None)."""
    if not isinstance(m, str) or not m.strip():
        return None
    low = m.lower().strip()
    # Exact canonical
    for canon in MATTER_ALIASES:
        if low == canon:
            return canon
    # Alias contains
    for canon, aliases in MATTER_ALIASES.items():
        if any(a in low for a in aliases):
            return canon
    return low  # unknown, return as-is so comparison can fail clearly


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
    """Compare one model response to the Director label. Returns a result dict."""
    label_vedana = label.get("vedana_expected")
    label_pm = label.get("primary_matter_expected")
    label_pass = label.get("triage_threshold_pass_expected")

    out_vedana_raw = parsed.get("vedana")
    out_matter_raw = parsed.get("matter")
    out_score = parsed.get("triage_score")

    out_vedana = normalize_vedana(out_vedana_raw)
    out_matter = normalize_matter(out_matter_raw)

    vedana_ok = (out_vedana == label_vedana) if json_ok else False
    matter_ok = (out_matter == label_pm) if json_ok else False
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
        "label_vedana":     label_vedana,
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
    for i, label in enumerate(labels, start=1):
        signal = (label.get("raw_content") or label.get("signal_text") or "")[:3000]
        prompt = STEP1_PROMPT.format(signal=signal.replace('"', "'"))
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
        }, f, indent=2)
    logger.info("wrote full results -> %s", out_path)

    sys.exit(0 if primary_ok else 1)


if __name__ == "__main__":
    main()
